import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "internet_host": "1.1.1.1", "dns_domain": "example.com",
    "http_url": "https://example.com", "iperf_host": None,
    "iperf_port": 5201, "ping_count": 10, "traceroute_max_hops": 12,
    "tshark_duration_seconds": 5, "timeout_seconds": 15,
}


def load(path=None):
    """Read the intentionally flat YAML subset used by config.yaml."""
    result = DEFAULTS.copy()
    file = Path(path) if path else ROOT / "config.yaml"
    if file.exists():
        for raw in file.read_text().splitlines():
            line = raw.split(" #", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(f"Invalid config line: {raw}")
            key, value = (part.strip() for part in line.split(":", 1))
            if key not in DEFAULTS:
                raise ValueError(f"Unknown config key: {key}")
            if value.lower() in ("null", "none", ""):
                result[key] = None
            elif isinstance(DEFAULTS[key], int):
                result[key] = int(value)
            else:
                result[key] = value.strip("\"'")
    result["server_url"] = os.environ.get("NETDOCTOR_SERVER_URL", "").rstrip("/")
    result["api_key"] = os.environ.get("NETDOCTOR_API_KEY", "")
    result["data_dir"] = Path(os.environ.get("NETDOCTOR_DATA_DIR", ROOT / "data"))
    return result
