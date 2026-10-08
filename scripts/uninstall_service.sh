#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
systemctl disable --now netdoctor-agent.timer 2>/dev/null || true
rm -f /etc/systemd/system/netdoctor-agent.service /etc/systemd/system/netdoctor-agent.timer
systemctl daemon-reload
echo "NetDoctor unit files removed; project data retained."
