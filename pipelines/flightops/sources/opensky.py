import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightops.sources import raw
from flightops.sources.registry import DATA

DIR = DATA / "opensky"
AIRPORT = "KATL"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
API_URL = "https://opensky-network.org/api/flights"
COLUMNS = [
    "icao24", "firstSeen", "estDepartureAirport", "lastSeen", "estArrivalAirport", "callsign",
    "estDepartureAirportHorizDistance", "estDepartureAirportVertDistance",
    "estArrivalAirportHorizDistance", "estArrivalAirportVertDistance",
    "departureAirportCandidatesCount", "arrivalAirportCandidatesCount",
]


def settled_days(today: date) -> tuple[date, date]:
    # the API updates in batches, and a saved day is never fetched again, so skip days that may be partial
    return today - timedelta(days=8), today - timedelta(days=2)


def _token() -> str:
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["OPENSKY_CLIENT_ID"],
        "client_secret": os.environ["OPENSKY_CLIENT_SECRET"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as response:
        return json.load(response)["access_token"]


def _fetch(kind: str, day: date, token: str) -> list[dict] | None:
    begin = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    url = f"{API_URL}/{kind}?airport={AIRPORT}&begin={begin}&end={begin + 86399}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # not ready yet, so the next run retries it
            return None
        raise


def collect(first: date, last: date) -> list[Path]:
    DIR.mkdir(parents=True, exist_ok=True)
    token = None
    written = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        for kind in ("arrival", "departure"):
            path = DIR / f"{AIRPORT}_{kind}_{day.isoformat()}.csv"
            if path.exists():
                continue
            token = token or _token()
            rows = _fetch(kind, day, token)
            if rows is None:
                print(f"not ready: {path.name}")
                continue
            raw.write_csv(path, COLUMNS, rows)
            written.append(path)
    return written


def load_all(conn) -> list[raw.LoadResult]:
    return [raw.load_file(conn, "opensky", "opensky_flight", p) for p in sorted(DIR.glob(f"{AIRPORT}_*.csv"))]
