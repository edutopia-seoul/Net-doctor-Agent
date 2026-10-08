import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from netdoctor import __version__
from netdoctor.api import client
from netdoctor.collectors import dns, http, interface, ping, tcp, throughput, traceroute
from netdoctor.config import load
from netdoctor.utils import executable


def agent_id(config):
    path = config["data_dir"] / "agent-id"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text().strip()
    value = str(uuid.uuid4())
    try:
        with path.open("x") as file:
            file.write(value + "\n")
        path.chmod(0o600)
        return value
    except FileExistsError:
        return path.read_text().strip()


def registration(config, identity, info):
    return {"agent_id": identity, "hostname": info["hostname"], "os": info["os"],
            "agent_version": __version__,
            "interfaces": [{**{key: item.get(key) for key in ("name", "mac", "ipv4")},
                            "link_speed_mbps": round(item["link_speed_mbps"])
                            if item.get("link_speed_mbps") is not None else None}
                           for item in info["interfaces"]],
            "capabilities": [name for name in
                             ("ping", "traceroute", "dns", "http", "tshark", "iperf3", "ethtool")
                             if executable({"dns": "dig", "http": "curl"}.get(name, name))]}


def empty_metrics():
    ping_fields = dict.fromkeys(("min_rtt_ms", "avg_rtt_ms", "max_rtt_ms", "packet_loss_pct", "jitter_ms"))
    return {"gateway_ping": ping_fields.copy(), "internet_ping": ping_fields.copy(),
            "dns": {"system_ms": None, "cloudflare_ms": None, "google_ms": None,
                    "resolved_ip": None, "query_success": {}},
            "traceroute": {"hop_count": None, "latency_jump_hop": None,
                           "latency_jump_ms": None, "hops": []},
            "http": dict.fromkeys(("dns_ms", "connect_ms", "tls_ms", "ttfb_ms", "total_ms", "status_code")),
            "tcp": dict.fromkeys(("captured_packets", "retransmissions", "retransmission_pct",
                                  "duplicate_ack", "rst", "zero_window")),
            "throughput": throughput.EMPTY.copy()}


def diagnose(config, identity, info=None, output=True):
    measurement = {
        "schema_version": "1.0", "agent_id": identity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_profile": {key: config[key] for key in
                           ("internet_host", "dns_domain", "http_url", "iperf_host")},
        "network": {"default_interface": None, "local_ip": None, "gateway": None, "dns_servers": []},
        "metrics": empty_metrics(), "collector_status": []}

    def attempt(name, callback, field=None, skipped=False):
        try:
            if skipped:
                measurement["collector_status"].append({"name": name, "status": "skipped", "message": "not configured"})
                return
            value = callback()
            if field:
                measurement["metrics"][field] = value
            partial = name == "dns" and not all(value.get("query_success", {}).values())
            measurement["collector_status"].append({"name": name, "status": "partial" if partial else "ok",
                                                    "message": "some resolver queries failed" if partial else ""})
            if output:
                print(f"{name}: OK", flush=True)
            return value
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            message = str(exc)[:240]
            measurement["collector_status"].append({"name": name, "status": "error", "message": message})
            if output:
                print(f"{name}: ERROR ({message})", flush=True)
            return None

    info = info or attempt("interface", lambda: interface.collect(config))
    if info:
        measurement["network"] = info["network"]
        if not any(s["name"] == "interface" for s in measurement["collector_status"]):
            measurement["collector_status"].append({"name": "interface", "status": "ok", "message": ""})
    gateway = measurement["network"]["gateway"]
    attempt("gateway_ping", lambda: ping.collect(gateway, config["ping_count"]), "gateway_ping",
            skipped=not bool(gateway))
    attempt("internet_ping", lambda: ping.collect(config["internet_host"], config["ping_count"]), "internet_ping")
    attempt("dns", lambda: dns.collect(config["dns_domain"]), "dns")
    attempt("traceroute", lambda: traceroute.collect(config["internet_host"], config["traceroute_max_hops"]), "traceroute")
    attempt("http", lambda: http.collect(config["http_url"], config["timeout_seconds"]), "http")
    attempt("tshark", lambda: tcp.collect(measurement["network"]["default_interface"],
                                          config["http_url"], config["tshark_duration_seconds"]), "tcp")
    attempt("iperf3", lambda: throughput.collect(config["iperf_host"], config["iperf_port"]),
            "throughput", skipped=not bool(config["iperf_host"]))
    return measurement


def queue(config, measurement):
    directory = config["data_dir"] / "pending"
    directory.mkdir(parents=True, exist_ok=True)
    name = f'{measurement["timestamp"].replace(":", "-")}-{uuid.uuid4().hex}.json'
    path = directory / name
    with path.open("x") as file:
        json.dump(measurement, file, ensure_ascii=False, indent=2)
        file.write("\n")
    path.chmod(0o600)
    return path


def upload_pending(config):
    directory = config["data_dir"] / "pending"
    if not config["server_url"] or not config["api_key"]:
        return 0, ["NETDOCTOR_SERVER_URL and NETDOCTOR_API_KEY are required"]
    sent = 0
    errors = []
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        try:
            client.upload(config, json.loads(path.read_text()))
            path.unlink()
            sent += 1
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {str(exc)[:180]}")
    return sent, errors


def main(argv=None):
    parser = argparse.ArgumentParser(prog="netdoctor-agent")
    parser.add_argument("command", choices=("info", "diagnose", "upload", "status"))
    parser.add_argument("--config", help="flat YAML config path")
    args = parser.parse_args(argv)
    config = load(args.config)
    identity = agent_id(config)
    if args.command == "status":
        pending = len(list((config["data_dir"] / "pending").glob("*.json")))
        print(json.dumps({"agent_id": identity, "pending": pending,
                          "server_configured": bool(config["server_url"] and config["api_key"])}, indent=2))
        return 0
    if args.command == "upload":
        sent, errors = upload_pending(config)
        print(f"Uploaded: {sent}; pending errors: {len(errors)}")
        for error in errors:
            print(error, file=sys.stderr)
        return 1 if errors else 0
    try:
        info = interface.collect(config)
    except (OSError, ValueError, RuntimeError) as exc:
        info = None
        print(f"Interface discovery failed: {exc}", file=sys.stderr)
    if args.command == "info":
        print(json.dumps({"agent_id": identity, "info": info}, indent=2, ensure_ascii=False))
        return 0 if info else 1
    if info:
        try:
            print(f"Registration HTTP {client.register(config, registration(config, identity, info))}")
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Registration deferred: {exc}")
    measurement = diagnose(config, identity, info)
    path = queue(config, measurement)
    print(f"Measurement saved: {path}")
    sent, errors = upload_pending(config)
    print(f"Upload: {sent} sent, {len(errors)} pending")
    for error in errors:
        print(error, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
