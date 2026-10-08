# NetDoctor Agent

NetDoctor Agent measures the local machine's network and sends structured JSON to the NetDoctor server. It does not run an LLM or diagnose faults. Collectors operate independently; a failed tool leaves `null` metrics and a `collector_status` entry. No normal Agent command changes routes, DNS, interfaces, or traffic shaping.

## Architecture

```text
ip / ping / dig / traceroute / curl / tshark / iperf3
            ↓ collect and parse
     Measurement JSON (schema 1.0)
            ↓ save before upload
       data/pending/*.json
            ↓ authenticated HTTP POST
         NetDoctor Server
```

The root structure has separate `collectors/`, `parsers/`, `api/`, `tests/`, `fixtures/`, and `scripts/`. We use the Python standard library for the Agent, so there is no PyPI dependency. The host tested here is Ubuntu 26.04.1; the same Ubuntu package names apply to Ubuntu 24.04 except package versions differ.

## Install and dependencies

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 iproute2 iputils-ping traceroute bind9-dnsutils curl ethtool iw tshark iperf3
python3 -m unittest discover -s tests -v
python3 -m netdoctor.main info
```

`bind9-dnsutils` provides `dig`; `iproute2` provides `ip` and `tc`. To create the optional `netdoctor-agent` console command, run `python3 -m venv .venv && .venv/bin/pip install -e .`, then use `.venv/bin/netdoctor-agent`. Running `python3 -m netdoctor.main` from the project root needs no installation.

## Configuration

Edit flat `config.yaml` for targets, durations, and optional `iperf_host`. Target defaults are 1.1.1.1, example.com, and https://example.com. Set server credentials in the process environment; `.env.example` is a template, and `.env` is ignored by Git. The Agent does not read `.env` automatically.

```bash
export NETDOCTOR_SERVER_URL=http://SERVER_IP:8000
export NETDOCTOR_API_KEY='shared-key'
python3 -m netdoctor.main diagnose
```

The URL must point to the FastAPI server. Authentication uses `X-NetDoctor-Key`. Registration goes to `POST /api/v1/agents/register`; measurements go to `POST /api/v1/measurements`. A stable UUID is stored at `data/agent-id` with mode 600. Set `NETDOCTOR_DATA_DIR` to move queue and ID together. Do not delete the ID if the server already knows this Agent.

## CLI

```bash
python3 -m netdoctor.main info       # interface, IP, gateway and stable ID
python3 -m netdoctor.main diagnose   # register, measure, save, upload
python3 -m netdoctor.main upload     # retry queued JSON files
python3 -m netdoctor.main status     # queue count and server config state
```

`diagnose` saves JSON before attempting upload. Failed uploads remain in `data/pending/`; the next `diagnose` or `upload` retries them. Files are removed only after an HTTP success response. Registration failures do not stop measurement. Each Collector reports `ok`, `partial`, `error`, or `skipped`.

## Collectors and feature definitions

| Collector | Tool | Result |
|---|---|---|
| Interface | `ip -j`, `resolvectl`, `ethtool` | default route, IP, MAC, DNS, link speed, Wi-Fi/Ethernet |
| Gateway / Internet | `ping` | RTT, packet loss, jitter |
| DNS | `dig` | system / Cloudflare / Google query times, success, one resolved A record |
| Traceroute | `traceroute -n` | per-hop IP/RTT/timeout, first RTT jump ≥30 ms |
| HTTP | `curl -w %{json}` | DNS, connect, TLS, TTFB, total, status |
| TCP | `tshark` | packet count, retransmissions, duplicate ACK, RST, zero window |
| Throughput | `iperf3 -J` | TCP/UDP Mbps, UDP jitter and loss (only when host configured) |

Ping jitter is the mean absolute difference between consecutive **received** RTT samples: `mean(abs(rtt[i] - rtt[i-1]))`. With fewer than two replies it is `null`. Packet loss comes from ping's transmitted/received summary. HTTP `connect_ms` and `ttfb_ms` are cumulative from the start; `tls_ms` is `time_appconnect - time_connect`. A traceroute timeout is recorded as a hop with `timeout: true`, not classified as a failure. On Wi-Fi, `link_speed_mbps` is the current TX bitrate from `iw`, which can change between samples; if unavailable it is `null`.

## TShark permissions and privacy

Ubuntu's `wireshark-common` nonroot capture option gives `/usr/bin/dumpcap` `cap_net_admin,cap_net_raw=eip` and restricts its execution to group `wireshark`. Add the Agent user to the group:

```bash
sudo dpkg-reconfigure wireshark-common  # choose Yes for nonroot capture
sudo usermod -aG wireshark "$USER"
# Log out and back in; verify with: id && getcap /usr/bin/dumpcap
```

During a short capture the Agent uses BPF `tcp and host <configured diagnostic IPv4> and port <HTTP port>`, plus display filter `tcp`. `dumpcap` streams capture bytes through a pipe to `tshark`; packet files are not written to disk. It extracts only `tcp.analysis.retransmission`, `tcp.analysis.fast_retransmission`, `tcp.analysis.duplicate_ack`, `tcp.flags.reset`, and `tcp.analysis.zero_window`. It triggers one request to the configured diagnostic URL. No payload, headers, cookies, visited-site history, or raw traffic is sent to the server. The Agent reports only aggregate numbers. A normal login after group membership change is needed; on this machine testing used a nonroot process with primary group `wireshark`.

## iperf3

Leave `iperf_host: null` unless a designated iperf3 server is ready. On the server run `iperf3 -s -p 5201`, permit TCP/UDP port 5201, and set `iperf_host` (and optional `iperf_port`) in `config.yaml`. The Agent runs a 3-second TCP test and a 3-second UDP test at 10 Mbit/s. A localhost loopback test validates the parser and execution, but its TCP throughput is not a physical link speed.

## systemd

The one-shot service performs a diagnosis. The optional timer invokes it every 15 minutes; there is no continuously running TShark or iperf3 process. Install unit files and configure credentials before enabling the timer:

```bash
sudo bash scripts/install_service.sh
sudoedit /etc/netdoctor-agent.env
# Add NETDOCTOR_SERVER_URL and NETDOCTOR_API_KEY, then:
sudo chmod 600 /etc/netdoctor-agent.env
sudo systemctl enable --now netdoctor-agent.timer
systemctl status netdoctor-agent.timer
journalctl -u netdoctor-agent.service -n 50
```

To run once: `sudo systemctl start netdoctor-agent.service`. To remove units: `sudo bash scripts/uninstall_service.sh`. The uninstall script retains the project and measurement data. The service runs as the installing user and includes the `wireshark` supplementary group.

## Fault simulation and reset

These commands are separate from the Agent. They require an explicit interface name and confirmation; `--yes` is for controlled automation. The script verifies the interface is the current default route and refuses to replace an unfamiliar qdisc. It runs one diagnosis, then its exit trap removes the netem qdisc. Each invocation briefly affects live traffic on that interface.

```bash
sudo bash scripts/fault_test.sh normal wlp1s0
sudo bash scripts/fault_test.sh latency wlp1s0   # 200 ms
sudo bash scripts/fault_test.sh loss wlp1s0      # 10% loss
sudo bash scripts/fault_test.sh mixed wlp1s0     # 100 ms + 5% loss
sudo bash scripts/fault_test.sh reset wlp1s0     # manual recovery if interrupted
tc qdisc show dev wlp1s0                         # verify baseline qdisc
```

## Testing and troubleshooting

`python3 -m unittest discover -s tests -v` runs fixture parser tests and a local HTTP mock for registration and offline queue replay. Tests do not need external network commands. `python3 -m compileall -q netdoctor` checks syntax.

- `tshark` permission error: check `getcap /usr/bin/dumpcap`, `getent group wireshark`, and log in again after group assignment.
- `link_speed_mbps: null`: Wi-Fi drivers may not expose `ethtool` speed or `iw` current TX bitrate; this is expected.
- DNS resolver `partial`: one upstream DNS may time out while others succeed; see `metrics.dns.query_success`.
- Traceroute `*`: intermediate routers often ignore probes; do not infer an outage solely from a timeout hop.
- Upload pending: verify the server URL, API key, FastAPI availability, and `python3 -m netdoctor.main upload`.
- `iperf3` skipped: configure a reachable `iperf_host` only when intentional.

For full removal, first uninstall the service, then remove the project directory and its local data only after backing up any queued measurements you need. System packages and the `wireshark` group membership are managed separately by the administrator.
