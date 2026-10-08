#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 {normal|latency|loss|mixed|reset} INTERFACE [--yes]" >&2
  exit 2
}

scenario="${1:-}"
iface="${2:-}"
[[ "$scenario" =~ ^(normal|latency|loss|mixed|reset)$ ]] || usage
[[ "$iface" =~ ^[a-zA-Z0-9_.:-]+$ ]] || usage
[[ -d "/sys/class/net/$iface" && "$iface" != lo ]] || { echo "Invalid interface" >&2; exit 2; }
default_iface="$(ip -j route show default | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r[0].get("dev", "") if r else "")')"
[[ "$iface" == "$default_iface" ]] || { echo "Interface differs from default route: $default_iface" >&2; exit 2; }
echo "Scenario: $scenario; interface: $iface; default route: $default_iface"
echo "Current qdisc: $(tc qdisc show dev "$iface")"
if [[ "${3:-}" != --yes ]]; then
  read -r -p "Type interface name to continue: " reply
  [[ "$reply" == "$iface" ]] || { echo "Cancelled"; exit 2; }
fi
[[ "$EUID" -eq 0 ]] || { echo "Run explicitly with sudo for tc changes" >&2; exit 2; }

qdisc="$(tc qdisc show dev "$iface")"
if [[ "$scenario" == reset ]]; then
  if [[ "$qdisc" == *" netem "* ]]; then
    tc qdisc del dev "$iface" root
    echo "netem removed"
  else
    echo "No netem root qdisc to remove"
  fi
  exit 0
fi
[[ "$qdisc" != *" netem "* ]] || { echo "Existing netem found; run reset first" >&2; exit 2; }
[[ "$qdisc" == *" noqueue "* || "$qdisc" == *" fq_codel "* ]] || {
  echo "Unexpected qdisc; refusing to replace it" >&2; exit 2;
}

cleanup() {
  if [[ "$(tc qdisc show dev "$iface")" == *" netem "* ]]; then
    tc qdisc del dev "$iface" root || true
    echo "netem reset complete"
  fi
}
trap cleanup EXIT INT TERM
case "$scenario" in
  normal) echo "No impairment applied" ;;
  latency) tc qdisc replace dev "$iface" root netem delay 200ms ;;
  loss) tc qdisc replace dev "$iface" root netem loss 10% ;;
  mixed) tc qdisc replace dev "$iface" root netem delay 100ms loss 5% ;;
esac
if [[ -n "${SUDO_USER:-}" ]]; then
  runuser -u "$SUDO_USER" -- python3 -m netdoctor.main diagnose
else
  python3 -m netdoctor.main diagnose
fi
