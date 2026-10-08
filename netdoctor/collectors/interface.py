import platform
import socket
from pathlib import Path

from netdoctor.parsers.network import parse_dns_servers, parse_ip, parse_link_speed, parse_wifi_bitrate
from netdoctor.utils import required_output, run


def collect(_config=None):
    interfaces, network = parse_ip(required_output(["ip", "-j", "address"]),
                                   required_output(["ip", "-j", "route", "show", "default"]))
    resolv = Path("/etc/resolv.conf").read_text()
    resolved = run(["resolvectl", "dns"])
    network["dns_servers"] = parse_dns_servers(resolved.stdout if not resolved.returncode else "", resolv)
    for interface in interfaces:
        ethtool = run(["ethtool", interface["name"]])
        interface["link_speed_mbps"] = parse_link_speed(ethtool.stdout)
        if (Path("/sys/class/net") / interface["name"] / "wireless").exists():
            interface["kind"] = "wifi"
        if interface["kind"] == "wifi" and interface["link_speed_mbps"] is None:
            try:
                wifi = run(["iw", "dev", interface["name"], "link"])
                interface["link_speed_mbps"] = parse_wifi_bitrate(wifi.stdout)
            except FileNotFoundError:
                pass
    os_release = platform.freedesktop_os_release()
    return {"hostname": socket.gethostname(), "os": os_release.get("PRETTY_NAME", platform.platform()),
            "interfaces": interfaces, "network": network}
