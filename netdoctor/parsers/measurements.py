import json
import re
import statistics


def parse_ping(text):
    rtts = [float(x) for x in re.findall(r"time[=<]([\d.]+)\s*ms", text)]
    loss = re.search(r"([\d.]+)%\s*packet loss", text)
    if not loss:
        raise ValueError("ping summary missing")
    return {
        "min_rtt_ms": min(rtts) if rtts else None,
        "avg_rtt_ms": round(statistics.mean(rtts), 3) if rtts else None,
        "max_rtt_ms": max(rtts) if rtts else None,
        "packet_loss_pct": float(loss.group(1)),
        "jitter_ms": round(statistics.mean(abs(b-a) for a, b in zip(rtts, rtts[1:])), 3)
        if len(rtts) >= 2 else None,
    }


def parse_dig(text):
    time = re.search(r"Query time:\s*(\d+)\s*msec", text)
    ips = re.findall(r"^\S+\s+\d+\s+IN\s+A\s+(\d+\.\d+\.\d+\.\d+)\s*$", text, re.M)
    return {"ms": int(time.group(1)) if time else None, "resolved_ip": ips[0] if ips else None,
            "success": bool(ips)}


def parse_traceroute(text, jump_threshold_ms=30):
    hops = []
    previous = None
    jump_hop = jump_ms = None
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.*)$", line)
        if not match:
            continue
        number, rest = int(match.group(1)), match.group(2)
        address = re.search(r"(?:\d{1,3}\.){3}\d{1,3}", rest)
        times = [float(v) for v in re.findall(r"([\d.]+)\s*ms", rest)]
        avg = round(statistics.mean(times), 3) if times else None
        hops.append({"hop": number, "address": address.group(0) if address else None,
                     "avg_rtt_ms": avg, "timeout": not bool(times)})
        if avg is not None:
            if previous is not None and jump_hop is None and avg - previous >= jump_threshold_ms:
                jump_hop, jump_ms = number, round(avg - previous, 3)
            previous = avg
    if not hops:
        raise ValueError("traceroute hops missing")
    return {"hop_count": len(hops), "latency_jump_hop": jump_hop,
            "latency_jump_ms": jump_ms, "hops": hops}


def parse_curl(text):
    data = json.loads(text)
    def milliseconds(key):
        value = data.get(key)
        return round(float(value) * 1000, 3) if value is not None else None
    connect, appconnect, pretransfer = (milliseconds(k) for k in
        ("time_connect", "time_appconnect", "time_pretransfer"))
    return {"dns_ms": milliseconds("time_namelookup"), "connect_ms": connect,
            "tls_ms": round(appconnect - connect, 3) if appconnect and connect is not None else None,
            "ttfb_ms": milliseconds("time_starttransfer"), "total_ms": milliseconds("time_total"),
            "status_code": int(data.get("response_code") or 0) or None}


def parse_tshark(text):
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    total = len(rows)
    def count(index):
        return sum(len(row) > index and row[index].strip() not in ("", "0", "False") for row in rows)
    retrans = sum(any(len(row) > i and row[i].strip() for i in (0, 1)) for row in rows)
    return {"captured_packets": total, "retransmissions": retrans,
            "retransmission_pct": round(100 * retrans / total, 3) if total else None,
            "duplicate_ack": count(2), "rst": count(3), "zero_window": count(4)}


def parse_iperf3_tcp(text):
    data = json.loads(text)
    if data.get("error"):
        raise ValueError(data["error"])
    bits = data.get("end", {}).get("sum_received", {}).get("bits_per_second")
    return round(bits / 1_000_000, 3) if bits is not None else None


def parse_iperf3_udp(text):
    data = json.loads(text)
    if data.get("error"):
        raise ValueError(data["error"])
    summary = data.get("end", {}).get("sum", {})
    bits = summary.get("bits_per_second")
    return {"udp_mbps": round(bits / 1_000_000, 3) if bits is not None else None,
            "udp_jitter_ms": summary.get("jitter_ms"), "udp_loss_pct": summary.get("lost_percent")}
