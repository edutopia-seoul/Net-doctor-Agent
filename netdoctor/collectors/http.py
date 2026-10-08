from netdoctor.parsers.measurements import parse_curl
from netdoctor.utils import run


def collect(url, timeout=15):
    proc = run(["curl", "-sS", "-L", "--noproxy", "*", "-o", "/dev/null", "-w", "%{json}",
                "--max-time", str(timeout), str(url)], timeout=timeout + 2)
    if not proc.stdout:
        raise RuntimeError(proc.stderr.strip() or "curl failed")
    result = parse_curl(proc.stdout)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"curl exit {proc.returncode}")
    return result
