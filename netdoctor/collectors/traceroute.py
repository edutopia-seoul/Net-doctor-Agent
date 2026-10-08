from netdoctor.parsers.measurements import parse_traceroute
from netdoctor.utils import run


def collect(target, max_hops=12):
    hops = min(max(int(max_hops), 1), 30)
    proc = run(["traceroute", "-n", "-w", "1", "-q", "1", "-m", str(hops), str(target)],
               timeout=hops * 2 + 5)
    if proc.returncode and not proc.stdout:
        raise RuntimeError(proc.stderr.strip() or "traceroute failed")
    return parse_traceroute(proc.stdout)
