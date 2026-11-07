#!/usr/bin/env bash
# Pull-based deploy for the Hukum gateway. Runs every minute from a systemd timer (or by hand).
# New commit on origin/main -> run the tests -> back up the live code -> copy code over -> restart -> health check
# -> roll back automatically if unhealthy. Never touches .env, placement.db, sessions or venv.
# Nothing here runs code from pull requests or forks: it only ever follows the owner's main branch.
set -uo pipefail
REPO="${HUKUM_REPO:-$HOME/hukum-repo}"
DIR="${HUKUM_DIR:?HUKUM_DIR not set}"
BRANCH="${BRANCH:-main}"
PORT="${PORT:-8765}"
LOG="$DIR/deploy.log"; BAD="$DIR/.bad_commit"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
cd "$REPO" || exit 1
git fetch -q origin "$BRANCH" 2>>"$LOG" || { log "fetch failed"; exit 0; }
NEW="$(git rev-parse "origin/$BRANCH")"; CUR="$(git rev-parse HEAD)"
[ "$NEW" = "$CUR" ] && [ -f "$DIR/.deployed_commit" ] && [ "$(cat "$DIR/.deployed_commit")" = "$CUR" ] && exit 0
[ "$NEW" = "$(cat "$BAD" 2>/dev/null)" ] && exit 0            # this commit already failed; wait for a new one
git merge -q --ff-only "origin/$BRANCH" 2>>"$LOG" || { git reset -q --hard "origin/$BRANCH"; }
log "deploying ${NEW:0:8}: $(git log -1 --pretty=%s)"
SRC="$REPO/placement-agents"
# 1. tests (against a throwaway db; they never touch the live one)
if ! (cd "$SRC" && "$PY" -m unittest tests.test_pc >>"$LOG" 2>&1); then
  log "TESTS FAILED, not deploying ${NEW:0:8}"; echo "$NEW" > "$BAD"; exit 1
fi
# 2. backup + copy code only
mkdir -p "$DIR/backups"; BK="$DIR/backups/code-$(date +%Y%m%d-%H%M%S).tgz"
(cd "$DIR" && tar -czf "$BK" --exclude=venv --exclude=backups --exclude='*.db' --exclude='*.session' --exclude=.env --exclude=__pycache__ .)
ls -1t "$DIR"/backups/code-*.tgz | tail -n +6 | xargs -r rm -f
(cd "$SRC" && tar -cf - --exclude=tests --exclude=__pycache__ --exclude='*.db' --exclude='*.session' --exclude=.env \
   --exclude='*.zip' --exclude='*.apk' *.py *.txt agents web deploy 2>/dev/null) | (cd "$DIR" && tar -xf -)
if ! cmp -s "$SRC/requirements-gateway.txt" "$DIR/.req_installed" 2>/dev/null; then
  "$PY" -m pip install -q -r "$SRC/requirements-gateway.txt" >>"$LOG" 2>&1 && cp "$SRC/requirements-gateway.txt" "$DIR/.req_installed"
fi
# 3. restart + health
restart() { systemctl --user restart hukum 2>>"$LOG"; }
healthy() { for _ in 1 2 3 4 5 6 7 8 9 10; do curl -fsS "http://127.0.0.1:$PORT/api/ping" >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
restart
if healthy; then echo "$NEW" > "$DIR/.deployed_commit"; rm -f "$BAD"; log "deployed OK ${NEW:0:8}"; exit 0; fi
log "UNHEALTHY after deploy, rolling back to $BK"; journalctl --user -u hukum -n 15 --no-pager 2>&1 | tee -a "$LOG" >/dev/null
(cd "$DIR" && tar -xzf "$BK"); restart; echo "$NEW" > "$BAD"
healthy && log "rolled back, previous version running" || log "ROLLBACK ALSO UNHEALTHY: check journalctl --user -u hukum"
exit 1
