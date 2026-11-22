import time
import urllib.error

from flightops.sources import live, opensky, raw
from flightops.transform.live import build_live

WEATHER_EVERY = 5  # ticks: METARs come about hourly, so every 5 minutes is plenty


def tick(conn, n: int, state: dict) -> int:
    """One poll. Source errors are printed and skipped; database errors propagate and stop the loop."""
    files, wait = [], 0
    try:
        state["token"] = state.get("token") or opensky._token()
        files.append(("opensky", "opensky_state", live.write_states(live.fetch_states(state["token"]))))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            state["token"] = None  # tokens last 30 minutes; the next tick gets a new one
        wait = int(e.headers.get("X-Rate-Limit-Retry-After-Seconds") or 0)
        print(f"states: HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"states: {e}")
    if n % WEATHER_EVERY == 0:
        fetched_at = int(time.time())
        try:
            files.append(("awc", "awc_metar", live.write_metar(live.fetch_metar(), fetched_at)))
            files.append(("awc", "awc_taf", live.write_taf(live.fetch_taf(), fetched_at)))
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"weather: {e}")
    for source, table, path in files:
        raw.load_file(conn, source, table, path)
    positions, tails, operators = build_live(conn)
    print(f"tick {n}: {positions} aircraft, {tails} with a tail, {operators} with an operator")
    return wait


def run(conn, every: int = 60, ticks: int | None = None, sleep=time.sleep) -> None:
    n = 0
    state: dict = {}
    while ticks is None or n < ticks:
        wait = tick(conn, n, state)
        n += 1
        sleep(max(every, wait))
