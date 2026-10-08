import unittest
from pathlib import Path

from netdoctor.parsers.network import parse_ip, parse_dns_servers, parse_link_speed, parse_wifi_bitrate
from netdoctor.parsers.measurements import (parse_ping, parse_dig, parse_traceroute,
                                            parse_curl, parse_tshark, parse_iperf3_tcp,
                                            parse_iperf3_udp)
from netdoctor.main import empty_metrics

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text()


class ParserTests(unittest.TestCase):
    def test_ip(self):
        interfaces, network = parse_ip(fixture("ip_address.json"), fixture("ip_route.json"))
        self.assertEqual(interfaces[0]["ipv4"], ["192.0.2.20"])
        self.assertEqual(network["gateway"], "192.0.2.1")
        self.assertEqual(network["default_interface"], "enp3s0")

    def test_dns_servers(self):
        self.assertEqual(parse_dns_servers("Link 2 (eth0): 1.1.1.1 8.8.8.8", "nameserver 127.0.0.53"),
                         ["1.1.1.1", "8.8.8.8"])

    def test_link_speed_unavailable(self):
        self.assertIsNone(parse_link_speed("Speed: Unknown!"))

    def test_wifi_bitrate(self):
        self.assertEqual(parse_wifi_bitrate("tx bitrate: 526.6 MBit/s VHT-MCS 6"), 526.6)

    def test_ping(self):
        result = parse_ping(fixture("ping.txt"))
        self.assertEqual(result["packet_loss_pct"], 25)
        self.assertAlmostEqual(result["avg_rtt_ms"], 2.667)
        self.assertEqual(result["jitter_ms"], 1.5)

    def test_ping_all_lost(self):
        result = parse_ping("4 packets transmitted, 0 received, 100% packet loss")
        self.assertIsNone(result["avg_rtt_ms"])
        self.assertIsNone(result["jitter_ms"])

    def test_dig(self):
        self.assertEqual(parse_dig(fixture("dig.txt"))["ms"], 25)
        self.assertTrue(parse_dig(fixture("dig.txt"))["success"])

    def test_traceroute(self):
        result = parse_traceroute(fixture("traceroute.txt"))
        self.assertEqual(result["hop_count"], 3)
        self.assertTrue(result["hops"][1]["timeout"])
        self.assertEqual(result["latency_jump_hop"], 3)

    def test_curl(self):
        result = parse_curl(fixture("curl.json"))
        self.assertEqual(result["tls_ms"], 25)
        self.assertEqual(result["status_code"], 200)

    def test_tshark(self):
        result = parse_tshark(fixture("tshark.tsv"))
        self.assertEqual(result["captured_packets"], 5)
        self.assertEqual(result["retransmissions"], 1)
        self.assertEqual(result["rst"], 1)
        self.assertEqual(result["retransmission_pct"], 20)

    def test_iperf3(self):
        self.assertAlmostEqual(parse_iperf3_tcp(fixture("iperf_tcp.json")), 98.765)
        self.assertEqual(parse_iperf3_udp(fixture("iperf_udp.json"))["udp_loss_pct"], 0.5)

    def test_empty_schema(self):
        self.assertIsNone(empty_metrics()["throughput"]["tcp_mbps"])


if __name__ == "__main__":
    unittest.main()
