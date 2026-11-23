#!/usr/bin/env bash
# Start flight-ops locally: migrations, live pipeline poller, Laravel server and Vite.
# Usage: ./start.sh [--build] [port]
#   --build  first fetch, load and build the ontology from data/raw (slow; needed on a fresh database)
#   port     web port, default 8000
set -euo pipefail
cd "$(dirname "$0")"
BUILD=0; [ "${1:-}" = "--build" ] && { BUILD=1; shift; }
PORT=${1:-8000}

for tool in pg_isready uv php composer npm; do
    command -v "$tool" >/dev/null || { echo "Missing $tool. Install it first." >&2; exit 1; }
done
pg_isready -h localhost -q || { echo "Postgres is not accepting connections. Start Postgres.app." >&2; exit 1; }
[ -f .env ] || { echo "Missing .env. Copy .env.example and fill it in." >&2; exit 1; }
[ -f web/.env ] || { echo "Missing web/.env. Run: cp web/.env.example web/.env && (cd web && php artisan key:generate)" >&2; exit 1; }
[ -d web/vendor ] || (cd web && composer install)
[ -d web/node_modules ] || (cd web && npm install)

flightops() { (cd pipelines && uv run --env-file ../.env python -m flightops "$@"); }
flightops migrate
if [ "$BUILD" = 1 ]; then flightops fetch; flightops load; flightops build; fi

trap 'kill 0' EXIT INT TERM
flightops live &                                   # polls OpenSky + aviationweather every 60 s
(cd web && npm run dev) &
(cd web && php artisan serve --port="$PORT") &
echo "App: http://127.0.0.1:$PORT"
wait
