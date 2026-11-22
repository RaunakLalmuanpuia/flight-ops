import json
import urllib.parse
import urllib.request
from pathlib import Path

from flightops.sources import raw
from flightops.sources.registry import DATA

STATES_DIR = DATA / "opensky_states"
AWC_DIR = DATA / "awc"
# shortcut: ATL only, from OurAirports; phase 6 (second hub) should read the airport table instead
ATL = (33.6367, -84.4281)
BOX = 1.5  # degrees each way: 3 x 3 = 9 sq deg, inside OpenSky's 1-credit tier of 25
STATES_URL = "https://opensky-network.org/api/states/all"
AWC_URL = "https://aviationweather.gov/api/data"
STATE_FIELDS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact", "longitude", "latitude",
    "baro_altitude", "on_ground", "velocity", "true_track", "vertical_rate", "sensors", "geo_altitude",
    "squawk", "spi", "position_source",
]
METAR_FIELDS = ["icaoId", "obsTime", "reportTime", "metarType", "rawOb"]  # rawOb is the delivered observation


def _get(url: str, token: str | None = None) -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return response.read().decode()


def fetch_states(token: str) -> dict:
    lat, lon = ATL
    query = urllib.parse.urlencode({
        "lamin": round(lat - BOX, 4), "lamax": round(lat + BOX, 4),
        "lomin": round(lon - BOX, 4), "lomax": round(lon + BOX, 4),
    })
    return json.loads(_get(f"{STATES_URL}?{query}", token))


def fetch_metar() -> list[dict]:
    return json.loads(_get(f"{AWC_URL}/metar?ids=KATL&format=json&hours=2") or "[]")  # empty body when none


def fetch_taf() -> str:
    return _get(f"{AWC_URL}/taf?ids=KATL&format=raw").strip()


def write_states(payload: dict) -> Path:
    rows = []
    for state in payload["states"] or []:  # null when the box is empty
        if len(state) != len(STATE_FIELDS):
            raise ValueError(f"state vector has {len(state)} fields, expected {len(STATE_FIELDS)}")
        rows.append({"time": payload["time"], **dict(zip(STATE_FIELDS, state))})
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    path = STATES_DIR / f"KATL_states_{payload['time']}.csv"
    raw.write_csv(path, ["time", *STATE_FIELDS], rows)
    return path


def write_metar(rows: list[dict], fetched_at: int) -> Path:
    AWC_DIR.mkdir(parents=True, exist_ok=True)
    path = AWC_DIR / f"KATL_metar_{fetched_at}.csv"
    raw.write_csv(path, METAR_FIELDS, [{k: r.get(k) for k in METAR_FIELDS} for r in rows])
    return path


def write_taf(text: str, fetched_at: int) -> Path:
    AWC_DIR.mkdir(parents=True, exist_ok=True)
    path = AWC_DIR / f"KATL_taf_{fetched_at}.csv"
    raw.write_csv(path, ["fetched_at", "raw_text"], [{"fetched_at": fetched_at, "raw_text": text}] if text else [])
    return path
