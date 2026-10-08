import json
import re


def parse_ip(address_json, route_json):
    addresses = json.loads(address_json)
    routes = json.loads(route_json)
    route = next((r for r in routes if r.get("dst") == "default"), {})
    interfaces = []
    for item in addresses:
        if item.get("ifname") == "lo":
            continue
        interfaces.append({
            "name": item.get("ifname"), "mac": item.get("address"),
            "ipv4": [a["local"] for a in item.get("addr_info", [])
                     if a.get("family") == "inet" and "local" in a],
            "state": item.get("operstate", "UNKNOWN"), "link_speed_mbps": None,
            "kind": "wifi" if item.get("ifname", "").startswith(("wl", "wlan"))
                    else "ethernet" if item.get("link_type") == "ether" else "unknown",
        })
    primary = next((i for i in interfaces if i["name"] == route.get("dev")), None)
    return interfaces, {
        "default_interface": route.get("dev"),
        "local_ip": primary["ipv4"][0] if primary and primary["ipv4"] else None,
        "gateway": route.get("gateway"), "dns_servers": [],
    }


def parse_dns_servers(resolvectl_text, resolv_conf_text):
    servers = []
    for line in resolvectl_text.splitlines():
        if line.startswith(("Global:", "Link ")):
            section = line.split(":", 1)[1]
            servers.extend(section.split())
    if not servers:
        servers = re.findall(r"^nameserver\s+(\S+)", resolv_conf_text, re.M)
    return list(dict.fromkeys(s for s in servers if s not in ("127.0.0.53", "::1")))


def parse_link_speed(text):
    match = re.search(r"Speed:\s*(\d+)Mb/s", text)
    return int(match.group(1)) if match else None


def parse_wifi_bitrate(text):
    match = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", text)
    return float(match.group(1)) if match else None
