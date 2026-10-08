from netdoctor.parsers.measurements import parse_dig
from netdoctor.utils import run


SERVERS = {"system": None, "cloudflare": "1.1.1.1", "google": "8.8.8.8"}


def collect(domain):
    result = {"system_ms": None, "cloudflare_ms": None, "google_ms": None,
              "resolved_ip": None, "query_success": {}}
    for name, server in SERVERS.items():
        args = ["dig", "+tries=1", "+time=2", "+noall", "+answer", "+stats", domain, "A"]
        if server:
            args.append("@" + server)
        try:
            proc = run(args, timeout=5)
            parsed = parse_dig(proc.stdout)
            result[name + "_ms"] = parsed["ms"] if parsed["success"] else None
            result["query_success"][name] = parsed["success"]
            if not result["resolved_ip"] and parsed["resolved_ip"]:
                result["resolved_ip"] = parsed["resolved_ip"]
        except (OSError, ValueError) as exc:
            result["query_success"][name] = False
            result.setdefault("errors", {})[name] = str(exc)
    if not any(result["query_success"].values()):
        raise RuntimeError("all DNS queries failed: " + str(result.get("errors", {})))
    return result
