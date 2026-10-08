#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
service_user="${SUDO_USER:-}"
[[ -n "$service_user" && "$service_user" != root ]] || { echo "Invoke via sudo from target user" >&2; exit 1; }
[[ "$project_dir" != *"@"* && "$service_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 1
sed -e "s|@PROJECT_DIR@|$project_dir|g" -e "s|@USER@|$service_user|g" \
  "$project_dir/systemd/netdoctor-agent.service" > /etc/systemd/system/netdoctor-agent.service
install -m 644 "$project_dir/systemd/netdoctor-agent.timer" /etc/systemd/system/netdoctor-agent.timer
systemctl daemon-reload
echo "Installed unit files. Configure /etc/netdoctor-agent.env, then enable timer if desired."
