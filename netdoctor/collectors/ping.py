from netdoctor.parsers.measurements import parse_ping
from netdoctor.utils import run


def collect(target, count=4):
    if not target:
        raise ValueError("ping target unavailable")
    count = min(max(int(count), 1), 30)
    proc = run(["ping", "-n", "-c", str(count), "-W", "2", str(target)], timeout=count * 3 + 3)
    # ping exits nonzero on packet loss, while its summary remains useful.
    return parse_ping(proc.stdout)
