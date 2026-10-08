# NetDoctor Agent 개발 기록

## 1. 담당 역할

실제 네트워크를 측정하고 수치를 JSON으로 만들어 서버에 전송한다. 장애 판정은 서버가 맡는다.

## 2. 초기 환경

- 2026-09-28: Ubuntu 26.04.1 LTS, Linux 7.0.0-31-generic, Python 3.14.4
- CPU: Intel Core i5-7200U, 4 논리 CPU; RAM: 7.1 GiB
- 기본 인터페이스: `wlp1s0` (Wi-Fi, UP); 기본 게이트웨이와 IP는 사설 주소이므로 공개 보고서에서 생략
- DNS: systemd-resolved stub; 실제 uplink DNS 1.1.1.1, 8.8.8.8
- Wi-Fi link speed: `ethtool`은 값을 제공하지 않아 `iw`의 현재 TX bitrate를 사용한다. 초기 관찰값은 TX 526.6 Mb/s, RX 585.1 Mb/s였다. 연결 중 변할 수 있는 순간값이다.
- `/opt` 쓰기 권한 없음; 현재 사용자 소유 프로젝트 디렉터리를 사용
- 사용자 승인 후 비밀번호 파일을 sudo 표준입력에만 연결해 패키지를 설치했다. 비밀번호 값은 읽거나 기록하지 않았다.

## 3. 설치한 도구

Ubuntu 26.04 저장소의 실제 패키지명을 확인해 설치했다. `dnsutils` 기능은 `bind9-dnsutils` 패키지로 제공된다.

| 도구 | 패키지 버전 | 목적 |
|---|---|---|
| Python | 3.14.4 실행 버전 | Agent 런타임 |
| iproute2 | 6.19.0-1ubuntu1.1 | 인터페이스/경로 조회, tc |
| iputils-ping | 20250605-1ubuntu1 | RTT/손실 측정 |
| traceroute | 2.1.6-1build1 | hop 측정 |
| bind9-dnsutils | 9.20.24-1ubuntu0.3 | dig DNS 측정 |
| curl | 8.18.0-1ubuntu2.7 | HTTP 단계별 시간 |
| ethtool | 6.19-1 | 링크 속도 조회 |
| iw | 6.17-1 | Wi-Fi 현재 TX bitrate 조회 |
| tshark | 4.6.4-1 | TCP 통계 |
| iperf3 | 3.20-2 | 선택적 처리량 측정 |

## 4. Agent Architecture

`CLI → 독립 Collector → Parser → Measurement JSON → 로컬 Queue → Server API`. 등록/업로드 실패는 로컬 측정을 중단시키지 않는다.

## 5. 생성/수정 파일

- `netdoctor/main.py`: CLI, Collector 격리 실행, 스키마 생성, 등록, 로컬 Queue
- `netdoctor/config.py`, `config.yaml`, `.env.example`: 대상과 Server 설정
- `netdoctor/collectors/`: Interface, Ping, DNS, Traceroute, HTTP, TCP, Throughput
- `netdoctor/parsers/`: 명령 출력 파싱과 수치 Feature 계산
- `netdoctor/api/client.py`: 인증 헤더를 포함한 Server POST
- `tests/`, `fixtures/`: 명령 출력 Fixture, Parser 11개와 API 1개 테스트
- `scripts/fault_test.sh`: 분리된 netem 시나리오와 자동 복구
- `systemd/`, `scripts/install_service.sh`, `scripts/uninstall_service.sh`: 주기 진단 Unit
- `README.md`, `REPORT_AGENT.md`: 실행 설명 및 실험 기록
- `pyproject.toml`, `requirements.txt`, `.gitignore`: CLI 패키징, 의존성, 비밀/측정 파일 제외
- Git 저장소를 초기화했다. `.venv`, API 키 파일, Agent ID, Pending JSON과 pcap은 추적 대상에서 제외했다.

## 6. 주요 명령어

```bash
.venv/bin/netdoctor-agent info
.venv/bin/netdoctor-agent diagnose
.venv/bin/netdoctor-agent upload
.venv/bin/netdoctor-agent status
python3 -m unittest discover -s tests -v
sudo bash scripts/fault_test.sh loss wlp1s0
sudo bash scripts/fault_test.sh reset wlp1s0
tc qdisc show dev wlp1s0
sudo systemctl start netdoctor-agent.service
```

현재는 `.venv`에 editable 패키지 설치를 완료했다. `data/agent-id`는 여러 실행에서 동일한 UUID를 유지했다.

## 7. Collector 구현

| Collector | 입력 / 도구 | 추출 데이터 | 예외 처리 |
|---|---|---|---|
| Interface | 기본 경로, `ip -j`, `resolvectl`, `ethtool`, `iw` | 인터페이스, 주소, 게이트웨이, DNS, Wi-Fi 현재 TX 속도 | 속도 미확인 시 null |
| Gateway/Internet Ping | 자동 게이트웨이/설정 Target, `ping` | RTT min/avg/max, 손실, jitter | 응답 0개면 RTT/jitter null |
| DNS | 설정 도메인, `dig` | 시스템/Cloudflare/Google 응답 시간, 성공 여부, A 레코드 | 일부 실패는 partial, 해당 시간 null |
| Traceroute | 외부 Target, `traceroute -n` | hop, RTT, timeout, 첫 30 ms 이상 증가 | 응답 없는 hop은 장애로 판정하지 않음 |
| HTTP | 설정 URL, `curl -w %{json}` | DNS, connect, TLS, TTFB, total, status | 연결 실패는 error 및 null |
| TCP | 설정 URL/IP/port, `dumpcap` 파이프 + `tshark` | TCP 요약 카운트 | 권한/캡처 실패는 error 및 null |
| Throughput | 선택적 iperf Host, `iperf3 -J` | TCP/UDP Mbps, UDP jitter/loss | Host 없으면 skipped 및 null |

Ping jitter는 연속으로 수신한 RTT 간 절댓값 차이의 평균이다. Traceroute jump는 이전 응답 hop에 비해 RTT가 30 ms 이상 증가한 첫 위치만 Feature로 남긴다. 최종 장애 진단은 서버에서 수행한다.

## 8. Measurement JSON

정상 실측(2026-09-28 06:54 UTC)의 공개용 발췌. 실제 파일에는 전체 스키마와 hop 목록이 있고, 여기서는 Agent ID와 로컬 IP/MAC/게이트웨이를 마스킹했다.

```json
{
  "schema_version": "1.0",
  "agent_id": "<stable-uuid-redacted>",
  "timestamp": "2026-09-28T06:54:29+00:00",
  "target_profile": {"internet_host": "1.1.1.1", "dns_domain": "example.com", "http_url": "https://example.com", "iperf_host": null},
  "network": {"default_interface": "wlp1s0", "local_ip": "<redacted>", "gateway": "<redacted>", "dns_servers": ["<redacted>"]},
  "metrics": {
    "gateway_ping": {"min_rtt_ms": 1.63, "avg_rtt_ms": 2.365, "max_rtt_ms": 3.11, "packet_loss_pct": 0, "jitter_ms": 0.677},
    "internet_ping": {"min_rtt_ms": 1.89, "avg_rtt_ms": 4.095, "max_rtt_ms": 6.68, "packet_loss_pct": 0, "jitter_ms": 3.43},
    "dns": {"system_ms": 0, "cloudflare_ms": null, "google_ms": 64, "resolved_ip": "<redacted>", "query_success": {"system": true, "cloudflare": false, "google": true}},
    "traceroute": {"hop_count": 12, "latency_jump_hop": null, "latency_jump_ms": null, "hops": ["<redacted>"]},
    "http": {"dns_ms": 0.845, "connect_ms": 61.876, "tls_ms": 79.447, "ttfb_ms": 204.632, "total_ms": 204.874, "status_code": 200},
    "tcp": {"captured_packets": 24, "retransmissions": 0, "retransmission_pct": 0, "duplicate_ack": 0, "rst": 0, "zero_window": 0},
    "throughput": {"tcp_mbps": null, "udp_mbps": null, "udp_jitter_ms": null, "udp_loss_pct": null}
  },
  "collector_status": [{"name": "dns", "status": "partial", "message": "some resolver queries failed"}]
}
```

`collector_status`와 `traceroute.hops`는 공간상 발췌했다. 실제 Queue JSON은 `data/pending/`에 있다.

## 9. Server 통신

시작 시 `POST /api/v1/agents/register`, 측정 후 `POST /api/v1/measurements`를 `X-NetDoctor-Key` 헤더와 함께 요청한다. 서버가 없거나 키가 미설정이어도 진단을 계속하며, JSON을 `data/pending/`에 먼저 저장한다. HTTP 성공 후에만 Queue 파일을 제거한다. 로컬 모의 HTTP 서버 테스트에서 등록, 인증 헤더, 오프라인 보존, 온라인 재전송이 성공했다. 실제 Ubuntu Server URL/키는 아직 제공되지 않아 원격 등록/업로드는 수행할 수 없으며 현재 9개 JSON이 보관 중이다.

## 10. TShark

`wireshark-common`의 비root 캡처 설정을 활성화해 `/usr/bin/dumpcap`에 `cap_net_admin,cap_net_raw=eip`를 부여하고 실행 권한을 `wireshark` 그룹으로 제한했다. 사용자를 그룹에 추가했다. 현재 로그인 셸은 그룹 변경 전 세션이므로 `sudo -u ikeawolf -g wireshark`로 비root 실측했고, systemd는 `SupplementaryGroups=wireshark`로 성공했다.

Capture BPF는 `tcp and host <설정 진단 URL의 IPv4> and port <HTTP port>`, Display Filter는 `tcp`이다. 추출 필드는 재전송, 빠른 재전송, duplicate ACK, RST, zero window 5개다. `dumpcap -w -`를 `tshark -r -`로 파이프 연결해 패킷 파일을 디스크에 남기지 않는다. Server에는 카운트와 백분율만 전송한다. 서비스 실행에서 TCP 30패킷, 재전송 0건을 확인했다.

## 11. Fault Simulation

| Scenario | 적용 조건/명령 | 예상 | 실제 결과 |
|---|---|---|---|
| A Normal | netem 없음, `fault_test.sh normal wlp1s0` | 낮은 RTT/손실 | Gateway 2.365 ms, Internet 4.095 ms, Internet Loss 0%, HTTP 204.874 ms |
| B High Latency | `tc qdisc replace ... netem delay 200ms` | RTT/HTTP 증가 | 첫 실험 Gateway 202.5 ms, Internet 204.25 ms, HTTP 740.827 ms. 재실험 Internet 209.5 ms, HTTP 연결 실패 |
| C Packet Loss | `tc qdisc replace ... netem loss 10%` | 손실/HTTP 악화 | 10회 Ping 재실험 Gateway Loss 20%, Internet Loss 30%, HTTP 1406.623 ms. TCP 재전송 0건 관찰 |
| D Mixed | `tc qdisc replace ... netem delay 100ms loss 5%` | RTT와 손실 동시 증가 | Gateway 103.0 ms, Internet 103.667 ms, 4회 Internet Ping Loss 25%, HTTP 514.666 ms |

손실률은 표본 수가 적으면 설정한 10%와 다를 수 있다. 처음 4회 Ping 손실 실험에서는 0%가 나와 기본 설정을 10회로 늘려 재실험했다. TCP 재전송은 짧은 캡처와 HTTP 요청 1회에서는 발생하지 않을 수 있으며 없는 값을 임의로 만들지 않았다. 각 스크립트 종료 후 `tc qdisc show dev wlp1s0`가 `noqueue`로 복원된 것을 확인했다.

## 12. 테스트 결과

| 테스트 | 예상 | 실제 | 결과 |
|---|---|---|---|
| IP/Ping/DNS/Traceroute/Curl/TShark/iperf3 Fixture Parser 12개 | 고정 출력에서 정확한 수치 | 12개 통과 | PASS |
| API 등록 및 오프라인 Queue 재전송 1개 | 헤더/Endpoint 일치, 파일 보존 후 전송 | 1개 통과 | PASS |
| `compileall`, Bash syntax | 구문 오류 없음 | 오류 없음 | PASS |
| 실제 Wi-Fi CLI 진단 | 7개 Collector 격리 수행 | Ping/DNS/Traceroute/HTTP/TCP 성공, iperf3 skipped | PASS |
| Collector 부분 실패 | HTTP 오류여도 후속 TCP 수집 실행 | 지연 재실험에서 HTTP error, TShark ok | PASS |
| systemd 일회성 실행 | 비root 측정 및 Queue 저장 | 최종 실행 exit 0, TShark ok | PASS |
| iperf3 로컬 loopback | TCP/UDP JSON 파싱 | TCP 33503.955 Mb/s, UDP 10.04 Mb/s, jitter 0.026 ms, loss 0% | PASS |
| 4개 netem Scenario | 측정 후 복구 | 모두 측정, 최종 qdisc noqueue | PASS |

## 13. 발생한 오류와 해결

- 처음에는 비대화형 sudo 인증이 없었으나 사용자가 지정한 권한 파일을 sudo 표준입력에 연결하도록 승인했다. 비밀번호를 출력하지 않고 패키지를 설치했다.
- 초기 지연 실험에서 root PATH에 `rg`가 없어 자동 복구가 실행되지 않았다. 즉시 `tc qdisc del`로 복구하고 스크립트를 Bash 문자열 검사로 바꿨다. 이후 loss/mixed/normal/latency에서 복구를 확인했다.
- 기존 TShark 직접 캡처는 내부 임시 pcapng 생성 때문에 `ProtectSystem=strict` systemd 환경에서 실패했다. `dumpcap` → pipe → `tshark` 스트리밍으로 바꿔 디스크 저장 없이 동작하게 했다.
- 일부 직접 Cloudflare DNS 질의가 타임아웃돼 해당 시간은 null과 `partial` 상태로 기록했다. 시스템 및 Google DNS 결과는 수집됐다.
- Wi-Fi `ethtool`은 고정 링크 속도를 제공하지 않았다. `iw` 현재 TX bitrate를 fallback으로 사용한다.

## 14. 최종 상태

Agent CLI, 안정 ID, 7개 Collector, JSON, API Queue, 시나리오 스크립트, README, Git, 13개 자동 테스트, systemd 일회성 Unit 완료. 최종 확인에서 서비스 `Result=success`, 종료 코드 0, Timer `disabled`, 네트워크 qdisc `noqueue`, Pending JSON 9개였다. Timer Unit은 설치됐으나 서버 주소/키가 없어 비활성이다. 실제 서버 업로드는 미검증이며 로컬 모의 서버로 계약을 검증했다. iperf3는 로컬 테스트 완료, 원격 Host 미설정으로 정규 측정에서는 skipped이다.

## 15. Server와 통합하기 위해 필요한 정보

- `NETDOCTOR_SERVER_URL=http://SERVER_IP:8000`
- `NETDOCTOR_API_KEY` 공유 키 및 `X-NetDoctor-Key` 검증
- `POST /api/v1/agents/register`, `POST /api/v1/measurements` 스키마 1.0 수용
- 선택적 iperf3 Host와 TCP/UDP 5201 포트
- 서버 연결 후 `netdoctor-agent upload`로 9개 보류 JSON 재전송. 서비스용 자격증명은 `/etc/netdoctor-agent.env`에 root 전용 권한으로 배치

## 16. 발표/PPT용 핵심 내용

Agent는 실제 인터페이스와 네트워크 품질을 측정해 구조화 JSON으로 Server에 전달한다. Server의 Rule Engine과 LLM이 판정을 담당한다. Python, iproute2, ping, dig, traceroute, curl, dumpcap/tshark, iperf3를 사용했다. 핵심 Feature는 RTT/손실/jitter, DNS 비교, HTTP 단계별 시간, TCP 재전송/ACK 통계다. BPF로 진단 대상 IP/port만 캡처하고 패킷은 pipe로 처리했다. netem 200 ms 지연에서 Internet RTT 4.095→204.25 ms, 10% 손실 실험에서 10회 Ping 손실 30%와 HTTP 1.41초가 기록됐다. Collector 독립 실패 처리와 Server 오프라인 Queue가 기술적 특징이다.

## 17. 발표용 캡처 목록

- `ip -j route show default` 화면 (사설 IP 마스킹)
- `netdoctor-agent info`의 자동 인터페이스 탐지 (MAC/IP 마스킹)
- 정상 진단 CLI 및 `collector_status`
- High Latency/Packet Loss/Mixed의 CLI와 비교 표
- 공개용 Measurement JSON 및 Pending Queue
- TShark 필드 5개, BPF, TCP 요약 숫자
- systemd 성공 상태와 로컬 모의 Server 업로드 테스트
- `tc qdisc show`의 netem 적용/`noqueue` 복구 화면

## 18. 실제 Server 통합 테스트

- 테스트 시작: 2026-09-28 16:59 KST (07:59 UTC)
- Server URL: `http://192.168.0.201:8000`; Dashboard URL: `http://192.168.0.201:3001`
- Agent ID: `549dc09b-4438-4e02-ad3b-2e70c4110b95` (기존 ID 유지)
- 인증키: 아직 Agent 환경에 미설정. 실제 값은 보고서에 기록하지 않는다.
- 연결 점검: `192.168.0.201` ICMP 3/3 성공, 평균 2.576 ms. 같은 로컬 서브넷 경로와 ARP 응답 확인. `/health`의 TCP 8000 연결은 3~5초 제한에서 timeout, HTTP status `000`. Dashboard TCP 3001도 timeout, HTTP status `000`. 17:02 KST 재시도에서도 `/health` HTTP `000`/timeout.
- 등록 결과: 미실행. `/health` 연결과 실제 API 키가 준비되면 요청할 예정. 반환 agent_id/HTTP status 미확인.
- Pending 9건 전송 결과: 성공 0 / 실패 0 / 보류 9. 모두 유효한 JSON이고 동일 Agent ID를 가진다. 접속 및 인증 전에는 요청하지 않아 Queue에서 삭제된 파일이 없다.
- 신규 Measurement: 이번 통합 시도에서는 아직 실행하지 않았다. 연결 복구 후 1회 측정 예정.
- systemd: 기존 일회성 Unit은 설치돼 있으며 이전 로컬 측정에서 성공. 실제 Server 설정 적용 후 검증은 보류. Timer는 disabled.
- 개인정보 확인: Pending JSON 9건의 Key 집합에 `cookie`, `authorization`, `api_key`, `password`, `payload`, `raw_packet`, `pcap`, `visited_sites`, `user_data`가 없다. 전송 대상은 측정 수치와 지정된 Target/경로/주소 정보다.
- 실패한 요청과 원인: GET `/health` 및 Dashboard 루트는 TCP 연결 시간 초과. ICMP는 성공하므로 Server의 서비스 Listen Address 또는 방화벽/컨테이너 포트 공개 상태 확인이 필요하다. 원인은 Server 측에서 아직 확정하지 못했다.
- 최종 통합 성공 여부: **진행 중**. 실제 API Key와 TCP 연결이 준비되어야 등록, Queue 업로드, 새 측정, Server DB/Rule/AI/Dashboard 경로를 검증할 수 있다.

### LAN 복구 후 재시도 (2026-09-28 17:18 KST)

- LAN TCP 복구: `nc -vz -w 5`로 Backend `192.168.0.201:8000`, Frontend `192.168.0.201:3001` 모두 성공.
- `/health`: 실제 Server에서 HTTP 200, `status: ok`, `service: netdoctor-server` 응답.
- Server OpenAPI: `/openapi.json` HTTP 200. `POST /api/v1/agents/register`의 `AgentRegister`와 `POST /api/v1/measurements`의 `MeasurementIn` 확인. 기존 Agent JSON의 최상위 필드 및 `schema_version: 1.0` 유지.
- Agent ID: `549dc09b-4438-4e02-ad3b-2e70c4110b95` 그대로. Pending 9건 모두 동일 ID·유효한 JSON.
- 인증키: 아직 Agent 실행 환경과 `/etc/netdoctor-agent.env`에 설정되지 않음. 실제 값은 기록하지 않는다.
- Agent Register: 키 설정 대기, 요청 미전송. HTTP status/response 미확인.
- Pending 9건: 성공 0 / 실패 0 / 미전송 9. Queue 파일 보존.
- 신규 Measurement 및 systemd 실제 Server 전송: 수동 등록·기존 Queue 전송 완료 후 실시 예정. Timer는 disabled.
- Schema/API 문제: 아직 인증된 요청을 보내지 않아 422 등 실제 API 검증 결과 없음. Server OpenAPI의 `InterfaceInfo.link_speed_mbps`는 integer 또는 null로 선언돼 있어 등록 응답을 확인할 때 실제 값의 형식을 주의한다.
- 최종 통합 성공 여부: **TCP/health 단계 성공, 인증·전송 단계 대기**.

### 18.1 인증 설정 (최종 재검증: 2026-09-28 17:57 KST)

- `/etc/netdoctor-agent.env`: root 소유, 권한 600. Server URL 항목 YES, API Key 항목 YES를 값 출력 없이 확인했다. URL은 `http://192.168.0.201:8000`과 일치했다.
- 수동 통합 검증은 root가 환경파일을 읽은 직후 프로세스 권한을 일반 Agent 사용자로 낮춰 수행했다. systemd는 `EnvironmentFiles=/etc/netdoctor-agent.env`로 직접 읽는다.
- API Key의 실제 값은 코드, 로그, 이 보고서에 기록하지 않았다. 일반 로그인 셸은 root 전용 파일을 자동으로 읽지 않으므로 CLI 직접 실행 시 환경변수를 별도로 전달해야 한다.
- Backend `/health` HTTP 200. Backend TCP 8000, Frontend TCP 3001 및 Frontend 루트 HTTP 200 확인. Timer는 계속 disabled.

### 18.2 실제 Agent 등록

- Agent ID `549dc09b-4438-4e02-ad3b-2e70c4110b95`, hostname `IKEAWOLF-SERVER-C`, interface `wlp1s0`.
- capabilities: ping, traceroute, dns, http, tshark, iperf3, ethtool.
- 첫 실제 등록은 HTTP 200, Server 응답 `status=ok`, 반환 Agent ID 일치. 이후 Wi-Fi 속도가 소수였던 신규 진단 시 HTTP 422 (`interfaces[0].link_speed_mbps`, `int_from_float`)를 발견했다.
- Server OpenAPI의 정수 계약에 맞춰 **등록 요청의 링크 속도만 반올림해 정수로 직렬화**했다. 측정/정보 Collector 값과 Server 스키마는 바꾸지 않았다. 재등록 HTTP 200, 반환 Agent ID 일치. systemd 실행에서도 `Registration HTTP 200`.

### 18.3 Pending Queue 실제 전송

기존 Pending before 9건, Server 저장 확인 9건, 최종 Pending after 0건. 첫 8건은 서버의 응답이 10초보다 늦어 POST의 HTTP 상태를 수신하지 못했다. **실패로 단정하거나 재전송하지 않고**, 인증된 `GET /api/v1/measurements?agent_id=...` HTTP 200에서 Agent ID·타임스탬프·Server ID가 일치함을 확인한 뒤 해당 로컬 파일만 제거했다. 마지막 건은 기다림을 늘려 POST HTTP 200을 직접 확인했다.

| 로컬 타임스탬프 (UTC) | POST 응답 | Server 저장 조회 | Queue 처리 |
|---|---|---|---|
| 06:51:07.506558 | 10초 timeout | GET 200, ID 10 | 저장 확인 후 제거 |
| 06:52:46.051157 | 10초 timeout | GET 200, ID 11 | 저장 확인 후 제거 |
| 06:53:34.895671 | 10초 timeout | GET 200, ID 12 | 저장 확인 후 제거 |
| 06:54:09.162416 | 10초 timeout | GET 200, ID 13 | 저장 확인 후 제거 |
| 06:54:29.700325 | 10초 timeout | GET 200, ID 14 | 저장 확인 후 제거 |
| 06:54:46.539059 | 10초 timeout | GET 200, ID 15 | 저장 확인 후 제거 |
| 06:56:00.750781 | 10초 timeout | GET 200, ID 16 | 저장 확인 후 제거 |
| 06:58:13.725639 | 요청 중 중단, 응답 미수신 | GET 200, ID 17 | 저장 확인 후 제거 |
| 06:59:54.705510 | HTTP 200 | ID 18 | 성공 응답 후 제거 |

처음 8건의 POST 응답 자체는 수신되지 않아 HTTP 200이라고 기록하지 않는다. 서버에는 9개 고유 ID로 한 번씩 저장됐고, 최종 전송 실패/미처리 파일은 0건이다.

### 18.4 신규 정상 Measurement

- 수동 신규 측정 타임스탬프: `2026-09-28T08:52:07.884298+00:00`; Server POST HTTP 200, Measurement ID 19, Pending 0.
- Gateway: 평균 RTT 2.348 ms, 손실 0%. Internet: 평균 RTT 2.574 ms, 손실 0%.
- DNS: System 65 ms, Google 57 ms, Cloudflare timeout/null → DNS Collector `partial`.
- Traceroute 12 hops (응답 없는 hop 포함). HTTP TTFB 275.985 ms. TCP 31패킷, 재전송 0건/0%.
- Collector Status: interface/gateway_ping/internet_ping/traceroute/http/tshark `ok`, dns `partial`, iperf3 `skipped` (Host 미설정).
- 추가 systemd 일회성 측정: `2026-09-28T08:54:04.162445+00:00`, Server ID 20, Queue 0.

### 18.5 Server API 호환성 및 개인정보

- Measurement JSON은 기존 `schema_version: 1.0` 그대로 Server에서 수락했다. Measurement POST에 HTTP 422는 없었다. null, timestamp, traceroute hops, collector_status, throughput optional 값도 수락됐다.
- 등록 요청의 Wi-Fi 링크 속도 소수값이 HTTP 422의 유일한 확인된 Schema 문제였다. `netdoctor/main.py`의 등록 payload 형식만 정수로 보정했다.
- Server가 Measurement 저장 후 응답까지 수십 초 걸려 기존 Agent의 5초 HTTP timeout으로는 성공 응답을 놓칠 수 있었다. Measurement 요청 timeout만 120초로, systemd `TimeoutStartSec`를 180초로 늘렸다. API 규격과 Server 구현은 변경하지 않았다.
- 실제 Server 저장본 ID 19/20에서 `cookie`, `authorization`, `api_key`, `password`, `payload`, `raw_packet`, `pcap`, `http_body`, `visited_sites`, `login` 필드가 없음을 확인했다. Packet Payload, HTTP Body 및 사용자의 사이트 이용 기록은 전송하지 않는다.
- Server의 `GET /api/v1/diagnoses/19`, `/20`은 HTTP 200이고 Rule Diagnosis는 두 건 모두 `normal`이었다. AI Diagnosis는 두 건 모두 `available=false`; 서버가 `JSONDecodeError: Unterminated string`을 기록했다. Ollama 모델 출력 파싱 문제로 보이며 Agent 측 측정·전송 오류와 구분해야 한다.
- Frontend 루트 HTTP 200은 확인했으나 브라우저 Dashboard의 실제 데이터 렌더링은 이 Agent에서 검증하지 않았다.

### 18.6 systemd 실제 Server 연동

- root 전용 EnvironmentFile을 읽은 일회성 실행에서 `Registration HTTP 200`, `Upload: 1 sent, 0 pending` 기록.
- `systemctl show`: `Result=success`, `ExecMainStatus=0`, 서비스는 oneshot 종료 후 inactive. Server GET에서 새 Measurement ID 20 확인.
- 타이머는 `disabled`로 유지했다. 네트워크 qdisc는 `noqueue`이며 장애 시뮬레이션은 실행하지 않았다.
- 자동 테스트 13개 통과, Python 구문 검사와 systemd Unit 검증 통과.

### 18.7 Agent 측 최종 통합 판정

**Agent → 인증 등록 → 기존 9건 저장 확인 → 신규 진단/업로드 → systemd 업로드는 성공.** Server 조회에서 Measurement ID 10–20을 확인했고 로컬 Pending은 0건이다. Rule Engine 응답도 확인했다. **전체 AI/Dashboard 경로는 부분성공:** AI Diagnosis의 서버 측 JSON 파싱 오류와 Dashboard 데이터 표시 확인이 남아 있다. Agent API Key나 Packet Payload는 보고서에 기록하지 않았다.

## 19. 최종 4종 네트워크 장애 실험

### 19.1 실험 환경

- 시작: 2026-09-28 19:31 KST. Agent `IKEAWOLF-SERVER-C`, Wi-Fi `wlp1s0`, Agent ID `549dc09b-4438-4e02-ad3b-2e70c4110b95`.
- 기본 경로는 `wlp1s0`이며 실험 전 qdisc는 `noqueue`. Server `/health` HTTP 200, Backend TCP 8000과 Frontend TCP 3001 접속 성공, Pending Queue 0건. root 전용 환경파일에 URL/키 항목 모두 설정 확인 (값은 기록하지 않음).
- 각 Measurement 완료 뒤 Server 저장과 AI Diagnosis를 확인하고 다음 건으로 진행한다. 타이머와 병렬 실행은 사용하지 않는다.

### 19.2 시간 동기화

- 실험 전 `timedatectl`: `System clock synchronized: yes`, NTP active.
- `chronyc tracking`: `Leap status: Normal`, Stratum 3, System time 약 0.000301초 slow.
- `chronyc sources -v`: `^* ntp-nts-1.ps6.canonical.com` 선택, Reach 377. chrony 설정 변경 없음.

### 19.3 자동 Timer 상태

- `netdoctor-agent.timer`: `disabled`, `inactive (dead)`. 실험 중 활성화하지 않는다.

### 19.4 NORMAL 실험

`fault_test.sh reset wlp1s0 --yes`로 기존 netem 부재를 확인하고 `qdisc noqueue`에서 순차 5회 측정했다. 각 건은 Server 저장, Rule Diagnosis 및 AI `available=true` 확인 뒤 다음 건을 실행했다.

| Label | Server ID | Gateway RTT ms | Internet RTT ms | Internet Loss % | DNS System ms | HTTP TTFB ms | TCP Retrans % | AI |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| NORMAL-01 | 21 | 5.633 | 2.794 | 0 | 60 | 330.416 | 0 | 완료 |
| NORMAL-02 | 22 | 2.512 | 2.682 | 0 | 1 | 298.385 | 0 | 완료 |
| NORMAL-03 | 23 | 3.776 | 3.484 | 0 | 64 | 197.422 | 0 | 완료 |
| NORMAL-04 | 24 | 2.491 | 2.463 | 0 | 1 | 286.371 | 0 | 완료 |
| NORMAL-05 | 25 | 2.528 | 2.712 | 0 | 1 | 201.247 | 0 | 완료 |

5건 모두 Server Upload와 AI 확인 성공. Internet RTT 평균은 코드 계산으로 2.827 ms, Packet Loss는 모두 0%. 종료 후 qdisc `noqueue` 확인. 실제 결과는 `data/experiments/final_four_conditions_2026-09-28.json`에도 순차 저장 중이다.

### 19.5 HIGH_LATENCY 실험

`NORMAL` 종료 후 qdisc reset으로 `noqueue`를 확인하고 `tc qdisc replace dev wlp1s0 root netem delay 200ms`를 적용했다. `tc qdisc show`에서 `netem delay 200ms` 확인. 기존 `fault_test.sh`는 한 건 후 자동 reset하므로 5건 연속 조건 유지에는 직접 `tc` 적용을 사용했다. 각 건 Server 저장·AI 완료 확인 후 다음 건을 실행했다.

| Label | Server ID | Gateway RTT ms | Internet RTT ms | Internet Loss % | DNS System ms | HTTP TTFB ms | TCP Retrans % | AI |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LATENCY-01 | 26 | 202.9 | 202.9 | 0 | 0 | 809.733 | 0 | 완료 |
| LATENCY-02 | 27 | 202.9 | 203.5 | 0 | 0 | 734.644 | 0 | 완료 |
| LATENCY-03 | 28 | 203.0 | 203.5 | 0 | 263 | 1066.528 | 0 | 완료 |
| LATENCY-04 | 29 | 203.4 | 203.0 | 0 | 0 | 804.694 | 0 | 완료 |
| LATENCY-05 | 30 | 202.7 | 202.7 | 0 | 0 | 806.165 | 0 | 완료 |

5건 모두 Server Upload·AI 확인 성공. Internet RTT 평균 203.120 ms (코드 계산). 일부 DNS 0 ms는 캐시 응답의 실제 `dig` 측정값이며 보정하지 않았다. 마지막 측정 후 netem 제거, qdisc `noqueue` 확인.

### 19.6 PACKET_LOSS 실험

LATENCY 종료 후 `noqueue`를 확인하고 `tc qdisc replace dev wlp1s0 root netem loss 10%`를 적용했다. qdisc에서 `netem loss 10%`를 확인했다. 각 건 Server 저장·AI 완료 확인 후 다음 건을 실행했다.

| Label | Server ID | Gateway RTT ms | Internet RTT ms | Internet Loss % | DNS System ms | HTTP TTFB ms | TCP Retrans % | AI |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LOSS-01 | 31 | 2.865 | 3.192 | 10 | 0 | 690.465 | 8.333 | 완료 |
| LOSS-02 | 32 | 3.422 | 3.203 | 20 | 0 | 204.828 | 0 | 완료 |
| LOSS-03 | 33 | 2.654 | 3.361 | 10 | null | 2280.194 | 3.333 | 완료 |
| LOSS-04 | 34 | 2.698 | 6.941 | 10 | 60 | 363.305 | 6.667 | 완료 |
| LOSS-05 | 35 | 1.989 | 3.715 | 0 | 1 | 260.206 | 3.125 | 완료 |

5건 모두 Server Upload·AI 확인 성공. 관측 Internet Loss 평균은 코드 계산으로 10.0%. 10회 Ping 개별 표본은 0–20%로 변했다. TCP 재전송은 5건 중 4건에서 관측됐고 1건에서는 0건이었다. LOSS-03 DNS System `null`을 그대로 보존했다. 종료 후 netem 제거, qdisc `noqueue` 확인.

### 19.7 MIXED 실험

LOSS 종료 후 `noqueue`를 확인하고 `tc qdisc replace dev wlp1s0 root netem delay 100ms loss 5%`를 적용했다. qdisc에서 두 조건을 동시에 확인했다. 각 건 Server 저장·AI 완료 확인 후 다음 건을 실행했다.

| Label | Server ID | Gateway RTT ms | Internet RTT ms | Internet Loss % | DNS System ms | HTTP TTFB ms | TCP Retrans % | AI |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MIXED-01 | 36 | 105.778 | 104.556 | 10 | 0 | 559.636 | 0 | 완료 |
| MIXED-02 | 37 | 103.556 | 102.800 | 0 | 164 | 984.275 | 3.571 | 완료 |
| MIXED-03 | 38 | 102.889 | 103.200 | 0 | 1 | 511.540 | 0 | 완료 |
| MIXED-04 | 39 | 103.000 | 104.125 | 20 | 0 | 1069.635 | 2.703 | 완료 |
| MIXED-05 | 40 | 103.000 | 104.000 | 10 | 0 | 504.033 | 0 | 완료 |

5건 모두 Server Upload·AI 확인 성공. Internet RTT 평균 103.736 ms, 관측 Packet Loss 평균 8.0% (모두 코드 계산). 개별 10회 Ping 결과의 0% 및 20%도 그대로 보존했다. 마지막 측정 직후 netem 제거, qdisc `noqueue` 확인.

### 19.8 전체 Measurement 표

총 20건 모두 순차 수행, Server 저장 및 AI `available=true` 확인. 로컬 타임스탬프(UTC), Gateway Loss, DNS Google/Cloudflare, traceroute hop, HTTP Total, TCP 패킷/재전송 수, 각 Collector Status 및 Upload 결과는 [실험 원본 요약](data/experiments/final_four_conditions_2026-09-28.json)에 건별로 보존했다. 아래 DNS는 System DNS(ms), HTTP는 TTFB(ms), TCP는 재전송 비율(%). 모든 행의 Collector는 `dns:partial` (Cloudflare 응답 없음) 및 `iperf3:skipped` (Host 미설정), 나머지는 `ok`였다. `null`은 실제 미측정값이다.

| Label | Server ID | Gateway RTT | Internet RTT | Internet Loss | DNS | HTTP TTFB | TCP Retrans % | Collector |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| NORMAL-01 | 21 | 5.633 | 2.794 | 0 | 60 | 330.416 | 0 | DNS partial |
| NORMAL-02 | 22 | 2.512 | 2.682 | 0 | 1 | 298.385 | 0 | DNS partial |
| NORMAL-03 | 23 | 3.776 | 3.484 | 0 | 64 | 197.422 | 0 | DNS partial |
| NORMAL-04 | 24 | 2.491 | 2.463 | 0 | 1 | 286.371 | 0 | DNS partial |
| NORMAL-05 | 25 | 2.528 | 2.712 | 0 | 1 | 201.247 | 0 | DNS partial |
| LATENCY-01 | 26 | 202.900 | 202.900 | 0 | 0 | 809.733 | 0 | DNS partial |
| LATENCY-02 | 27 | 202.900 | 203.500 | 0 | 0 | 734.644 | 0 | DNS partial |
| LATENCY-03 | 28 | 203.000 | 203.500 | 0 | 263 | 1066.528 | 0 | DNS partial |
| LATENCY-04 | 29 | 203.400 | 203.000 | 0 | 0 | 804.694 | 0 | DNS partial |
| LATENCY-05 | 30 | 202.700 | 202.700 | 0 | 0 | 806.165 | 0 | DNS partial |
| LOSS-01 | 31 | 2.865 | 3.192 | 10 | 0 | 690.465 | 8.333 | DNS partial |
| LOSS-02 | 32 | 3.422 | 3.203 | 20 | 0 | 204.828 | 0 | DNS partial |
| LOSS-03 | 33 | 2.654 | 3.361 | 10 | null | 2280.194 | 3.333 | DNS partial |
| LOSS-04 | 34 | 2.698 | 6.941 | 10 | 60 | 363.305 | 6.667 | DNS partial |
| LOSS-05 | 35 | 1.989 | 3.715 | 0 | 1 | 260.206 | 3.125 | DNS partial |
| MIXED-01 | 36 | 105.778 | 104.556 | 10 | 0 | 559.636 | 0 | DNS partial |
| MIXED-02 | 37 | 103.556 | 102.800 | 0 | 164 | 984.275 | 3.571 | DNS partial |
| MIXED-03 | 38 | 102.889 | 103.200 | 0 | 1 | 511.540 | 0 | DNS partial |
| MIXED-04 | 39 | 103.000 | 104.125 | 20 | 0 | 1069.635 | 2.703 | DNS partial |
| MIXED-05 | 40 | 103.000 | 104.000 | 10 | 0 | 504.033 | 0 | DNS partial |

Label → Server ID 매핑: NORMAL-01~05 → 21~25, LATENCY-01~05 → 26~30, LOSS-01~05 → 31~35, MIXED-01~05 → 36~40. 20개 ID는 모두 고유하며 해당 Agent에 속한다.

### 19.9 Condition별 평균 및 표준편차

Python `statistics.mean`과 `statistics.stdev`로 실험 원본 JSON에서 직접 계산했다. 표준편차는 표본 표준편차(n−1), 단위는 RTT/DNS/TTFB ms 및 Loss/TCP Retrans %. `null`은 추정값으로 대체하지 않고 해당 지표에서만 제외했다. DNS는 System DNS 응답시간이다.

| Condition | Gateway RTT 평균±SD | Internet RTT 평균±SD | Internet Loss 평균±SD | DNS 평균±SD | HTTP TTFB 평균±SD | TCP Retrans 평균±SD |
|---|---:|---:|---:|---:|---:|---:|
| NORMAL | 3.388±1.370 | 2.827±0.387 | 0.000±0.000 | 25.400±33.441 | 262.768±60.118 | 0.000±0.000 |
| LATENCY | 202.980±0.259 | 203.120±0.363 | 0.000±0.000 | 52.600±117.617 | 844.353±128.089 | 0.000±0.000 |
| LOSS | 2.726±0.513 | 4.082±1.612 | 10.000±7.071 | 15.250±29.837 (n=4) | 759.800±870.517 | 4.292±3.266 |
| MIXED | 103.645±1.221 | 103.736±0.717 | 8.000±8.367 | 33.000±73.233 | 725.824±277.367 | 1.255±1.745 |

다른 모든 통계는 조건별 n=5. System DNS가 `null`인 LOSS-03만 DNS 평균에서 제외했다. 추가로 HTTP Total 평균은 NORMAL 263.778, LATENCY 845.753, LOSS 761.874, MIXED 726.330 ms. TCP 재전송 건수 평균은 각각 0, 0, 1.4, 0.4건이다. `dig`의 0 ms는 캐시 응답 측정값을 그대로 반영했다.

### 19.10 실패 및 재시도 기록

실험 Measurement 실패 0건, 재시도 0건, Server 중복 ID 0건. 20건 모두 서비스 종료 코드 0, Server 저장, 로컬 Queue 0, Rule Diagnosis 및 AI `available=true`를 확인했다. DNS Collector는 전 건 `partial`: Cloudflare 직접 질의가 모두 실패해 `null`, System과 Google은 대부분 성공했다. LOSS-03에서 System과 Google도 `null`이었지만 나머지 측정과 Server/AI 처리가 성공해 유효 데이터로 보존했다. iperf3는 Host 미설정으로 전 건 `skipped`이며 오류가 아니다.

### 19.11 netem 최종 복구

MIXED-05 즉시 `tc qdisc del dev wlp1s0 root`로 netem을 제거했고, 추가로 `fault_test.sh reset wlp1s0 --yes`를 실행해 잔여 netem이 없음을 확인했다. 최종 `tc qdisc show dev wlp1s0`: `qdisc noqueue 0: root`. 실험 종료 후 1.1.1.1 Ping 3/3 성공, 평균 2.385 ms, 손실 0%; `https://example.com` HTTP 200, 총 0.312초. Pending Queue 0, timer `disabled/inactive`.

종료 후 `timedatectl`: `System clock synchronized: yes`, NTP active. `chronyc tracking`: `Leap status: Normal`, System time 약 0.000464초 slow. `chronyc sources -v`: `^* ntp-nts-1.ps6.canonical.com` 선택, Reach 377. chrony 설정은 처음부터 끝까지 변경하지 않았다.

### 19.12 Agent 측 관찰 결과

NORMAL 대비 200ms 지연 조건의 Internet RTT는 2.827→203.120 ms, HTTP TTFB는 262.768→844.353 ms로 증가했다. 10% 손실 조건의 관측 Internet Loss 평균은 10.0%, TCP 재전송 비율 평균은 4.292%였으나 LOSS-02는 실제 재전송 0건이었다. MIXED 조건은 Internet RTT 평균 103.736 ms, 손실 평균 8.0%, TTFB 평균 725.824 ms였다. 10회 Ping 표본과 짧은 TCP 캡처의 한계를 고려해 각 건의 0%/20% 손실과 0건 재전송도 보존했다.

Server Rule Engine은 NORMAL 5건을 `normal`, LATENCY 5건을 `warning`, LOSS 4건을 `warning`·1건(LOSS-05)을 `normal`, MIXED 5건을 `warning`으로 반환했다. 모든 건에서 AI Diagnosis `available=true`가 확인된 뒤 다음 측정을 수행했다. Cloudflare DNS는 전 조건에서 timeout/null이므로 이 지표로 조건 간 속도 차이를 판단하지 않는다.

발표 대표 자료 (모두 실측):

| 조건 | 대표 ID | Internet RTT / Loss | HTTP TTFB / Total | TCP 패킷 / 재전송 | Server Rule |
|---|---:|---:|---:|---:|---|
| NORMAL-02 | 22 | 2.682 ms / 0% | 298.385 / 298.537 ms | 27 / 0 | normal |
| LATENCY-01 | 26 | 202.900 ms / 0% | 809.733 / 810.284 ms | 29 / 0 | warning |
| LOSS-01 | 31 | 3.192 ms / 10% | 690.465 / 692.331 ms | 36 / 3 | warning |
| MIXED-01 | 36 | 104.556 ms / 10% | 559.636 / 561.226 ms | 27 / 0 | warning |

PPT 캡처 추천: `timedatectl status`/`chronyc tracking`/선택 소스, `systemctl status netdoctor-agent.timer`, 기본 경로와 `wlp1s0`, 네 조건의 `tc qdisc show dev wlp1s0`, 대표 Server Measurement/Diagnosis ID 22·26·31·36, 위 통계 표, 최종 `qdisc noqueue`와 Ping/HTTP 복구. netem 적용 명령은 `tc qdisc replace dev wlp1s0 root netem delay 200ms`, `... netem loss 10%`, `... netem delay 100ms loss 5%`; reset은 `tc qdisc del dev wlp1s0 root` 및 별도 `fault_test.sh reset`으로 수행했다.

실험용 일회성 실행/조회 코드는 제거했다. Agent 기능·API Schema·Timer 설정은 변경하지 않았고, 재현 가능한 수치 데이터 JSON과 이 보고서만 남겼다. Server GET 재확인에서 해당 Agent의 Measurement 총 31건(기존 11건 + 본 실험 20건)이 조회됐다. 보고서의 20개 행을 결과 JSON과 코드로 대조해 모두 일치함을 확인했다.

## 20. Health Score v1.1 실제 신규 Measurement 검증

### 20.1 실행 환경 및 사전 확인 (2026-10-04 KST)

- 기존 Agent ID와 `wlp1s0` 기본 경로를 확인했다. qdisc는 `noqueue`로 netem 지연/손실 없음. `netdoctor-agent.timer`는 `disabled/inactive`, 서비스도 inactive, pending 0건이다.
- Backend `/health` 및 Dashboard 루트는 HTTP 200. root 전용 환경파일의 URL/키 존재를 값 노출 없이 확인했고 인증된 Measurement 목록 조회는 HTTP 200, 기존 31건(ID 10–40)이었다.
- 시작 시 `System clock synchronized: no`. chrony의 마지막 동기화는 2026-10-01 08:07:15 UTC, 선택 가능한 소스가 없었다. 과거 `Leap status: Normal`만으로 현재 동기화가 정상이라고 판정하지 않았다. 기존 NTS 소스의 재시도(`burst`, `refresh`, `rekey`)와 chrony 서비스 재시작으로 복구되지 않았으며, 재시작 후 `Leap status: Not synchronised`를 확인했다. chrony 설정파일은 변경하지 않았다.
- TCP Collector는 기본 5초 창에서 진단 URL GET 1회만 실행한다. 일회성 20초 캡처와 동일 진단 대상에 제한된 순차 요청을 추가하는 방안을 검토했다. 원본 Agent 코드 및 설정, Health Score 정책은 변경하지 않는다.
- 신규 Measurement는 시간 동기화 조건 충족 후 1회만 실행한다. 기존 ID 21–40 및 원본 실험 JSON은 수정하지 않는다.

### 20.2 시간 동기화 장애 및 실행 보류

- Ubuntu 기본 NTS 소스들의 NTS-KE timeout과 `no selectable sources`를 chrony 로그에서 확인했다. TCP 4460/TLS 연결 및 인증서 검증은 성공했지만 NTS 키 교환 응답은 timeout이었다. Cloudflare와 Netnod NTS도 읽기 전용 점검에서 동기화되지 않았다.
- `chronyd -Q`(시계 보정 비활성화)로 기존 Ubuntu 서버의 일반 NTP 응답은 확인했다. 관측 offset은 약 +0.102초였으나 시계를 변경하지 않았다. 실제 방화벽·중간장비·원격 서버 중 어느 지점에서 NTS 응답이 차단되는지는 확정하지 못했다.
- 인증된 시간 동기화에서 일반 NTP로 전환하는 것은 인증 정책 변경이므로 사용자에게 임시 사용 여부를 질문했다. 답변을 기다리는 동안 일반 NTP fallback이나 수동 시각 변경을 실행하지 않았다.
- 최종 확인 2026-10-04 10:32:59 KST: `NTPSynchronized=no`. 사용자가 지정한 측정 시작 조건에 미달하므로 신규 Measurement를 생성하거나 업로드하지 않았다. 이는 Health Score 구현 실패 판정이 아니라 검증 사전 조건 미충족이다.

### 20.3 TCP 표본 확대 검토

- 기존 `tcp.collect`는 기본 5초(내부 제한 1–30초) 캡처 중 HTTP GET을 1회 발생시킨다. 시간만 늘려도 표본이 100패킷 이상으로 증가한다고 보장할 수 없다.
- 재개 시 후보: 일회성 20초 캡처 동안 기존 `https://example.com`의 동일 IPv4/포트에 추가 GET 4회를 간격을 두고 순차 실행한다. 응답은 `/dev/null`로 보내고 요청마다 시간·크기 제한을 둔다. 표본 수에 맞춰 반복 측정하거나 결과를 보정하지 않는다.
- 이번에는 측정을 보류했으므로 추가 트래픽, 설정 조정, 캡처를 실행하지 않았다. captured_packets, TCP score/sample_size/quality/low_sample은 모두 신규 데이터 미확인이다.
- 기존 Collector의 대상 제한 BPF와 dumpcap→파이프→TShark 필드 추출을 검토했다. Raw packet이나 HTTP 본문을 디스크에 저장하는 기능은 추가하지 않았다.

### 20.4 신규 Measurement 및 Health Score 상태

| 검증 항목 | 이번 결과 |
|---|---|
| 신규 Measurement ID / timestamp | 미생성 |
| Gateway / Internet RTT·Loss, DNS, Traceroute, HTTP | 신규 측정 미실행 |
| TCP packets / retransmissions / Collector Status | 신규 측정 미실행 |
| 신규 Upload HTTP status | 요청 미전송 |
| 신규 Rule / AI available | 미검증 |
| v1 자동 저장 / v1.1 자동 저장 / 두 버전 공존 | 신규 Measurement가 없어 미검증 |
| Overall / Base Status / Final Status / Data Quality | 신규 결과 없음 |
| Local / Internet / DNS / TCP / HTTP score | 신규 결과 없음 |
| Coverage / Deductions / Guard Trigger | 신규 결과 없음 |
| Health Score 중복 row | 신규 데이터 미생성, DB row 중복 여부 직접 확인 불가 |

기존 ID 40의 v1과 v1.1 Health Score 조회는 각각 HTTP 200이었다. 이 사실을 신규 Measurement의 자동 저장 성공 근거로 사용하지 않는다. 수동 Backfill은 실행하지 않았고 점수 정책·API Schema도 수정하지 않았다.

### 20.5 기존 데이터 보존 및 Regression 점검

- 인증된 Measurement 목록과 Agent History API 모두 HTTP 200, 각 31건(ID 10–40). 신규 추가 0건, pending 0건.
- 기존 ID 40 진단 API HTTP 200, Rule 응답 존재, AI `available=true`. 이는 기존 처리 결과의 조회 확인이며 이번에 Ollama를 새로 호출한 것은 아니다.
- Dashboard 루트 HTML 및 참조 JS/CSS 모두 HTTP 200. 브라우저 화면의 실제 렌더링/상호작용은 확인하지 않았다.
- ID 21–40의 API 반환값을 정렬 JSON으로 직렬화한 SHA-256을 사전·사후 비교해 20건 모두 동일함을 확인했다. 원본 실험 JSON, Agent Python 파일, config.yaml 총 20개 파일의 SHA-256도 동일했다.
- 기존 4종 실험 JSON SHA-256: `467764a4dde0e0c55f7213457740fa12ee7edb7e48f234d34c36149a18b65251`.
- 비교 기준: `data/validation/health_score_v11_2026-10-04_baseline.json`; 최종 사전 점검 결과: `data/validation/health_score_v11_2026-10-04_preflight.json`. 인증키는 포함하지 않았다.
- 최종 qdisc `noqueue`, timer `disabled/inactive`. 장애 조건을 적용하지 않았다.

### 20.6 최초 보류 판정 및 재개 조건 (2026-10-04)

**WARNING — 시간 동기화 사전 조건 미충족으로 신규 실측 검증 보류.** 신규 1건의 Upload→Rule→AI→Health Score v1.1 자동 생성 성공/실패는 아직 판정할 수 없다.

NTS 동기화를 복구하거나 사용자가 승인한 임시 일반 NTP로 `System clock synchronized: yes`와 `Leap status: Normal`을 확인한 뒤, 기존 경로로 Measurement를 1회만 생성하고 이 절을 실제 결과로 갱신해야 한다. 기존 실험 데이터와 Health Score 정책은 변경하지 않는다.

### 20.7 실제 검증 재개 및 최종 결과 (2026-10-08 KST)

**신규 ID 41의 Agent 측정→Server 저장→Rule→AI→Health Score v1.1 자동 저장은 PASS. 전체 판정은 WARNING:** 신규 v1 점수는 저장되지 않았고, 검증 종료 후 원래 NTS 설정으로 복구하자 시간 동기화 장애가 다시 남았다. 기존 실험 데이터나 점수 정책은 수정하지 않았다.

#### 20.7.1 실행 환경과 시간 동기화

- 사용자 승인 후 임시 일반 NTP로 재개했다. 실행 전 `wlp1s0` 기본 경로, qdisc `noqueue`, pending 0건, timer `disabled/inactive`, 서비스 inactive, Backend `/health` 및 Dashboard HTTP 200을 확인했다.
- 기존 chrony 소스의 주소/ID와 선택 옵션, 설정파일 SHA-256을 `health_score_v11_2026-10-08_time_snapshot.json`에 보존했다. 기존 NTS 소스 10개에 런타임 `chronyc selectopts <source> +noselect`를 적용하고, 읽기 전용 응답 확인을 마친 `216.239.35.8`(Google NTP)을 `chronyc add server 216.239.35.8 iburst`로 일시 추가했다. `/etc/chrony` 설정파일은 변경하지 않았다.
- `chronyc waitsync 12 0.01 0 5` 이후 `System clock synchronized: yes`, `Leap status: Normal`, 선택 소스 `^* 216.239.35.8`을 확인했다. 신규 측정부터 업로드/검증 완료까지 동기화 상태가 유지됐다.
- root 전용 `/etc/netdoctor-agent.env`를 읽은 뒤 일반 Agent 사용자로 권한을 낮춰 기존 `main.registration`, `main.diagnose`, `main.queue` 경로를 사용했다. 캡처에는 기존 서비스와 동일한 `wireshark` 보조 그룹을 프로세스에만 부여했다. 사용자 그룹 구성이나 dumpcap capability는 변경하지 않았다.

#### 20.7.2 신규 Measurement 실제 값

- Agent ID: `549dc09b-4438-4e02-ad3b-2e70c4110b95`; hostname `IKEAWOLF-SERVER-C`; interface `wlp1s0`.
- Measurement timestamp: `2026-10-08T08:36:13.083736+00:00` = **2026-10-08 17:36:13.083736 KST**.
- Server Measurement ID: **41**, 이번 실행의 신규 데이터는 이 1건뿐이다.

| 항목 | 실측값 |
|---|---|
| Gateway RTT min / avg / max | 1.650 / 2.482 / 3.870 ms |
| Gateway Loss / jitter | 0% / 1.162 ms |
| Internet RTT min / avg / max | 1.830 / 2.832 / 3.710 ms |
| Internet Loss / jitter | 0% / 0.334 ms |
| DNS System / Google / Cloudflare | 66 / 61 / null ms |
| Traceroute | 12개 hop probe, 1개 응답·11개 timeout, latency jump 없음 |
| HTTP DNS / connect / TLS | 65.231 / 125.545 / 67.720 ms |
| HTTP TTFB / total / status | 256.508 / 257.280 ms / 200 |
| TCP captured packets | 136 |
| TCP retransmissions / retransmission percentage | 0건 / 0% |
| TCP duplicate ACK / RST / zero window | 0 / 0 / 0 |

Traceroute의 12는 실제 목적지까지 확인된 경로 길이가 아니라 설정된 최대 hop까지의 탐색 기록이다. 응답하지 않는 router를 곧바로 장애라고 판정하지 않았다.

Collector: interface, gateway_ping, internet_ping, traceroute, http, tshark는 `ok`; dns는 Cloudflare 질의 실패로 `partial`; iperf3는 Host 미설정으로 `skipped`. null을 숫자로 보정하거나 부분 실패 데이터를 제외하지 않았다.

#### 20.7.3 TCP 표본 확대와 개인정보

- Agent 코드나 config.yaml 수정 없이 이번 프로세스의 `tshark_duration_seconds`만 5→20초로 설정했다.
- 기존 dumpcap 프로세스의 BPF를 확인한 뒤 같은 진단 URL `https://example.com`의 동일 IPv4/443에 GET 4회를 순차 추가했다. Collector의 기본 GET을 포함하면 총 5회다. 추가 요청 간 약 1초 간격, 각 요청 connect timeout 2초/max time 3초, 최대 파일 64 KiB, rate 32 KiB/s 제한을 적용했다. 추가 4회 모두 HTTP 200/exit 0이었다.
- BPF는 단일 진단 대상 TCP/443로 제한했다. 응답 본문은 `/dev/null`로 보내고 dumpcap→파이프→TShark 필드 추출만 사용했다. Packet Payload, Cookie, 로그인 정보, HTTP Body, 방문 목록을 저장하거나 전송하지 않았다.
- 실제 수집량 **136 packets**로 목표 100 이상을 달성했다. 재전송은 실제 0건이며 값을 수정하지 않았다. 측정 JSON의 민감 필드 검사 결과 문제 0건.
- 기존 ID 40의 v1.1은 TCP sample_size 39, quality `low_sample`, low_sample=true였고, 신규 ID 41은 sample_size 136, quality `complete`, low_sample=false다. 이번에는 Overall도 `low_confidence`가 아니라 `partial`이며 남은 제한은 DNS 결측이다. 이는 표본 신뢰도 비교이며 서로 다른 실험 조건의 성능 효과를 단정하는 비교는 아니다.

#### 20.7.4 Upload, Rule, AI 및 자동 저장 증거

- 등록 HTTP **200**. Measurement POST는 `2026-10-08T08:36:52.718298+00:00` 시작, `08:37:40.599617+00:00` 종료, HTTP **200**, 소요 약 **47.881초**. timeout/재전송 없이 1회 요청했다.
- **첫 POST 응답 자체에** `measurement_id=41`, `score_version=health-score-v1.1`, `created_at=2026-10-08T08:36:52.803003Z`의 점수가 포함됐다. 별도 Health Score GET 전에 이미 생성됐으므로 수동 Backfill에 의존하지 않는 자동 저장을 확인했다.
- Rule Diagnosis: severity `normal`, findings와 triggered_rules는 빈 배열.
- AI Diagnosis: `available=true`, 모델 `qwen3.5:4b-q4_K_M`. 새 측정은 추가로 실행하지 않았다.
- Measurement, Diagnosis, v1.1 Health Score, History GET 모두 HTTP **200**. 같은 v1.1 점수 재조회에서도 created_at이 동일했다.

| v1.1 확인 항목 | 실제 결과 |
|---|---|
| score_version | health-score-v1.1 |
| Overall Score | 100 |
| Base Status / Final Status | normal / normal |
| Data Quality | partial |
| Overall Coverage / included_weight | 0.95 / 1.0 |
| Guard Trigger / Guard Reason | [] / null |
| Deductions / top_causes | 모든 Category 빈 배열 / 빈 배열 |

| Category | Score | Coverage | Quality | sample_size | low_sample |
|---|---:|---:|---|---:|---|
| Local | 100 | 1.0 | complete | null | false |
| Internet | 100 | 1.0 | complete | null | false |
| DNS | 100 | 0.6667 | partial | null | false |
| TCP | 100 | 1.0 | complete | 136 | false |
| HTTP | 100 | 1.0 | complete | null | false |

Cloudflare DNS 결측은 Coverage와 Data Quality에 반영됐다. 각 Category 점수는 Server 반환값 그대로 기록했다.

#### 20.7.5 v1/v1.1 공존 및 Queue 처리

- 신규 ID 41에 `score_version=health-score-v1`로 GET 요청하면 HTTP **404**, `health score not stored for the requested version`이다. v1 지정 History에서도 ID 41의 health_score는 null이었다. **이번 신규 데이터에는 v1 자동 저장/두 버전 공존이 확인되지 않았다.** 기존 ID 40에는 두 버전이 남아 있다. Server 정책 변경이나 Backfill은 실행하지 않았다.
- 새 Measurement의 Agent ID·timestamp에 일치하는 Server 행은 정확히 1개이며, 전체 목록은 31→32건이다. v1.1 반복 조회 결과도 동일했다. API에서 중복 Measurement는 없었으나 Agent 측 API 조회만 수행했으므로 PostgreSQL 점수 테이블의 중복 row/unique 제약은 직접 검사하지 않았다.
- 첫 로컬/Server 비교는 `metrics.dns.query_success` 차이로 불일치했다. Server OpenAPI의 `DNSMetrics`에는 이 보조 필드가 없으며, Server가 이를 제외하는 기존 계약임을 확인했다. **계약에 있는 모든 metrics, network, target_profile, collector_status, ID/timestamp가 일치**함을 확인한 뒤 성공 Queue item만 제거했다. 보조 필드는 원본 증거 JSON에 보존했다.
- 최종 pending **0건**, 추가 POST **0회**. Agent JSON이나 Server Schema를 변경하지 않았다.

#### 20.7.6 Regression, 복구 및 증거 파일

- 사전/사후 ID 21–40의 API 반환값 SHA-256이 모두 동일했다. 원본 4종 실험 JSON, Agent Python 파일, config.yaml의 해시도 동일했다.
- Agent 업로드와 인증 API, 신규 Rule/AI, History에 ID 41 표시를 확인했다. Dashboard 루트 HTTP 200을 확인했으며 브라우저의 실제 렌더링/상호작용은 이번 환경에서 확인하지 않았다.
- 검증 종료 후 `chronyc delete 216.239.35.8` 및 `systemctl restart chrony`로 임시 일반 NTP와 런타임 noselect 변경을 제거했다. 기존 `/etc/chrony` 설정파일 3개 해시는 사전 값과 동일하다.
- 원래 NTS 환경으로 복구 후 `NTPSynchronized=no`, `Leap status: Not synchronised`다. 측정/업로드 중 동기화 성공과 이후 NTS 장애를 구분한다. **NTS 영구 복구는 남은 운영 문제**다.
- 최종 qdisc는 `noqueue`, timer `disabled/inactive`, 서비스 inactive다. Agent 설정·Health Score 정책·자동 타이머를 변경하지 않았다.
- 증거: `data/validation/health_score_v11_2026-10-08_time_snapshot.json`, `..._baseline.json`, `..._result.json`, `..._queue_reconciliation.json`, `..._final_checks.json`. result JSON에는 실제 Agent 요청, POST 응답, Rule/AI, 두 버전 조회 및 재조회 결과를 보존했다. 최종 점검에서 임시 소스 제거·선택 옵션 복원·설정파일 해시 일치·pending 0·기존 ID 보존을 확인했다. 증거 파일 권한은 600이며, 보고서/증거에 인증키 값이 없는지도 검사했다.

**최종: v1.1 자동 처리 경로 PASS / 전체 WARNING (신규 v1 미저장, 원래 NTS 동기화 장애 및 브라우저 렌더링 직접 확인 미실시).** Health Score 정책 변경이나 기존 실험 수정 없이 신규 정상 실측 1건으로 핵심 목표를 검증했다.
