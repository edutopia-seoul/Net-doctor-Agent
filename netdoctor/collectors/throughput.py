from netdoctor.parsers.measurements import parse_iperf3_tcp, parse_iperf3_udp
from netdoctor.utils import run


EMPTY = {"tcp_mbps": None, "udp_mbps": None, "udp_jitter_ms": None, "udp_loss_pct": None}


def collect(host, port=5201):
    if not host:
        return EMPTY.copy()
    base = ["iperf3", "-c", str(host), "-p", str(port), "-t", "3", "-J"]
    tcp = run(base, timeout=12)
    if tcp.returncode:
        raise RuntimeError(tcp.stderr.strip() or "iperf3 TCP failed")
    udp = run(base + ["-u", "-b", "10M"], timeout=12)
    if udp.returncode:
        raise RuntimeError(udp.stderr.strip() or "iperf3 UDP failed")
    return {"tcp_mbps": parse_iperf3_tcp(tcp.stdout), **parse_iperf3_udp(udp.stdout)}
