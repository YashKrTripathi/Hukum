#!/usr/bin/env bash
# One-time setup on the CRM: moves the Hukum gateway under systemd and turns on auto-deploy from GitHub.
#   git clone https://github.com/YashKrTripathi/Hukum.git ~/hukum-repo && bash ~/hukum-repo/deploy/setup-hukum-crm.sh
# Finds the folder of the running gateway itself (override: HUKUM_DIR=/path). Safe to re-run.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user, not root."; exit 1; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
LINGER="$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo no)"
[ "$LINGER" = "yes" ] || { echo "linger is off: run  sudo loginctl enable-linger $USER  first (services would stop at logout)."; exit 1; }

say "1/4 find the running gateway"
DIR="${HUKUM_DIR:-}"
if [ -z "$DIR" ]; then
  for pid in $(pgrep -u "$USER" -f "run_gateway.py" || true); do
    c="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"; [ -f "$c/run_gateway.py" ] && { DIR="$c"; break; }
  done
fi
[ -n "$DIR" ] && [ -f "$DIR/run_gateway.py" ] || { echo "Could not find the gateway folder. Re-run with HUKUM_DIR=/path/to/it (the folder with run_gateway.py and .env)."; exit 1; }
[ -f "$DIR/.env" ] || { echo "$DIR/.env missing: not the live gateway folder?"; exit 1; }
echo "gateway folder: $DIR"
PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$DIR/logs"

say "2/4 install the systemd units"
mkdir -p "$HOME/.config/systemd/user"
sed "s#@HUKUM_DIR@#$DIR#; s#@PY@#$PY#" "$REPO/deploy/hukum.service" > "$HOME/.config/systemd/user/hukum.service"
sed "s#@REPO@#$REPO#" "$REPO/deploy/hukum-sync.service" > "$HOME/.config/systemd/user/hukum-sync.service"
# the sync service needs to know where the live folder is
sed -i "/^ExecStart=/i Environment=HUKUM_DIR=$DIR\nEnvironment=HUKUM_REPO=$REPO" "$HOME/.config/systemd/user/hukum-sync.service"
cp "$REPO/deploy/hukum-sync.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload

say "3/4 switch the gateway to systemd (brief restart)"
for pid in $(pgrep -u "$USER" -f "run_gateway.py" || true); do
  [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$DIR" ] && kill "$pid" && echo "stopped hand-started gateway pid $pid"
done
sleep 2
systemctl --user enable --now hukum
for i in 1 2 3 4 5 6 7 8; do curl -fsS http://127.0.0.1:8765/api/ping >/dev/null 2>&1 && { echo "gateway healthy"; break; }; sleep 2; [ "$i" = 8 ] && { echo "gateway not answering: journalctl --user -u hukum -n 30"; exit 1; }; done

say "4/4 auto-deploy from GitHub every minute"
rm -f "$DIR/.deployed_commit" "$DIR/.bad_commit"
HUKUM_DIR="$DIR" HUKUM_REPO="$REPO" bash "$REPO/deploy/hukum-sync.sh" || true
systemctl --user enable --now hukum-sync.timer
echo
echo "Done. Push to main on GitHub -> live within ~1-2 minutes (tests run first, rollback if unhealthy)."
echo "Log: tail -f $DIR/deploy.log      Status: systemctl --user status hukum hukum-sync.timer"
