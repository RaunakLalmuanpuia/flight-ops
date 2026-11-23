#!/usr/bin/env bash
# Portfolio screenshots of the running app into docs/screenshots/.
# Usage: scripts/screenshots.sh [base-url]   (default http://127.0.0.1:8000)
set -euo pipefail
BASE=${1:-http://127.0.0.1:8000}
OUT="$(cd "$(dirname "$0")/../.." && pwd)/docs/screenshots"
# shortcut: macOS Chrome path; on Linux pass CHROME=chromium
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
mkdir -p "$OUT"

shot() {
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size="$3" \
        --virtual-time-budget=10000 --screenshot="$OUT/$1.png" "$BASE$2" 2>/dev/null
    echo "$OUT/$1.png"
}

shot hub-2024-07-19 /day/2024-07-19 1440,1300
shot hub-2024-07-10 /day/2024-07-10 1440,1300
shot tail-N102DN-2024-07-19 /tail/N102DN/2024-07-19 1440,1100
shot tail-N181PQ-2024-07-19 /tail/N181PQ/2024-07-19 1440,1100
# shortcut: N102DN's DEN->ATL by flight_id, which held across July rebuilds so far; look it up if a rebuild renumbers flights
shot flight-N102DN-2024-07-19 /flights/371994 1440,900
# live data changes every minute: run `python -m flightops live` first, or this captures the stale banner
shot live /live 1440,1300
shot decisions /decisions 1440,700
# shortcut: the walkthrough's what-if decision by id; look it up by author 'walkthrough' if the log is recreated
shot decision-N102DN-what-if /decisions/50 1440,1000
