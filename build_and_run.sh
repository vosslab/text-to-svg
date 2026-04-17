#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT_DIR"

set +u
source source_me.sh
set -u

rm -rf .pytest_cache
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
rm -f web/app.js web/app.js.map

cd web
npm install
npm run build

cd "$ROOT_DIR"
LOG_FILE="$(mktemp)"
trap 'rm -f "$LOG_FILE"' EXIT

python3.12 -u -m backend.server --port 0 >"$LOG_FILE" 2>&1 &
SERVER_PID=$!

SERVER_URL=""
for _ in $(seq 1 100); do
	if grep -q "Serving on http://127.0.0.1:" "$LOG_FILE"; then
		SERVER_URL="$(sed -n 's/^Serving on \(http:\/\/127\.0\.0\.1:[0-9][0-9]*\)$/\1/p' "$LOG_FILE" | tail -n 1)"
		break
	fi
	sleep 0.1
done

if [ -z "$SERVER_URL" ]; then
	cat "$LOG_FILE"
	kill "$SERVER_PID" || true
	wait "$SERVER_PID" || true
	exit 1
fi

echo "$SERVER_URL"

if [[ "$(uname)" == "Darwin" ]]; then
	open "$SERVER_URL" >/dev/null 2>&1 || true
fi

wait "$SERVER_PID"
