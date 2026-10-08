import subprocess
import socket
from urllib.parse import urlparse

from netdoctor.parsers.measurements import parse_tshark
from netdoctor.utils import executable, run


FIELDS = ["tcp.analysis.retransmission", "tcp.analysis.fast_retransmission",
          "tcp.analysis.duplicate_ack", "tcp.flags.reset", "tcp.analysis.zero_window"]


def collect(interface, url, duration=5):
    binary = executable("tshark")
    if not binary:
        raise FileNotFoundError("tshark is not installed")
    dumpcap = executable("dumpcap")
    if not dumpcap:
        raise FileNotFoundError("dumpcap is not installed")
    if not interface:
        raise ValueError("capture interface unavailable")
    parsed = urlparse(url or "")
    if not parsed.hostname or parsed.scheme not in ("http", "https"):
        raise ValueError("configured HTTP URL required for focused TCP capture")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(parsed.hostname, port, socket.AF_INET, socket.SOCK_STREAM)
    if not addresses:
        raise RuntimeError("diagnostic host has no IPv4 address")
    address = addresses[0][4][0]
    duration = min(max(int(duration), 1), 30)
    capture_cmd = [dumpcap, "-i", interface, "-a", f"duration:{duration}",
                   "-f", f"tcp and host {address} and port {port}", "-w", "-"]
    parse_cmd = [binary, "-n", "-r", "-", "-Y", "tcp", "-T", "fields", "-E", "separator=\t"]
    for field in FIELDS:
        parse_cmd.extend(["-e", field])
    capture = parser = None
    try:
        capture = subprocess.Popen(capture_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        parser = subprocess.Popen(parse_cmd, stdin=capture.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        capture.stdout.close()
        try:
            # Generates traffic only toward the configured diagnostic URL.
            run(["curl", "-sS", "--noproxy", "*", "-o", "/dev/null", "--resolve",
                 f"{parsed.hostname}:{port}:{address}", "--max-time", str(duration), url],
                timeout=duration + 2)
            stdout, parse_error = parser.communicate(timeout=duration + 5)
            _, capture_error = capture.communicate(timeout=2)
        except BaseException:
            if parser and parser.poll() is None:
                parser.kill()
                parser.communicate()
            if capture and capture.poll() is None:
                capture.kill()
                capture.communicate()
            raise
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc
    if capture.returncode or parser.returncode:
        raise RuntimeError((capture_error.decode(errors="replace") if capture.returncode else parse_error).strip()
                           or "TCP capture failed")
    return parse_tshark(stdout)
