from dataclasses import dataclass
from pathlib import Path

from flightops.db import REPO

DATA = REPO / "data" / "raw"


@dataclass(frozen=True)
class RawFile:
    source: str
    table: str
    pattern: str  # glob, because the BTS zip names its CSV for us

    def path(self) -> Path:
        matches = list((DATA / self.source).glob(self.pattern))
        if len(matches) != 1:
            raise FileNotFoundError(
                f"expected one file for {DATA / self.source / self.pattern}, found {len(matches)}"
            )
        return matches[0]


@dataclass(frozen=True)
class Download:
    url: str
    dest: Path
    unzip: bool = False


RAW_FILES = [
    RawFile("bts", "bts_ontime", "*2024_7.csv"),
    RawFile("faa", "faa_master", "MASTER.txt"),
    RawFile("faa", "faa_acftref", "ACFTREF.txt"),
    RawFile("faa", "faa_dereg", "DEREG.txt"),
    RawFile("ourairports", "ourairports_airports", "airports.csv"),
    RawFile("iem", "iem_metar", "metar_katl_2024_07.csv"),
    RawFile("iem", "iem_taf", "taf_katl_2024_07.csv"),
]

# FAA is absent on purpose: it answers scripted requests with 403, so it is a hand download.
# Weather spans June 30 to August 2 UTC so joins at both ends of July have data.
_IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request"
DOWNLOADS = [
    Download(
        "https://transtats.bts.gov/PREZIP/"
        "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_7.zip",
        DATA / "bts" / "ontime_2024_7.zip",
        unzip=True,
    ),
    Download(
        "https://davidmegginson.github.io/ourairports-data/airports.csv",
        DATA / "ourairports" / "airports.csv",
    ),
    Download(
        f"{_IEM}/asos.py?station=ATL&data=metar&year1=2024&month1=6&day1=30"
        "&year2=2024&month2=8&day2=2&tz=Etc/UTC&format=onlycomma&latlon=no"
        "&missing=empty&trace=empty&report_type=1&report_type=3&report_type=4",
        DATA / "iem" / "metar_katl_2024_07.csv",
    ),
    Download(
        f"{_IEM}/taf.py?station=KATL&sts=2024-06-30T00:00Z&ets=2024-08-02T00:00Z&fmt=csv",
        DATA / "iem" / "taf_katl_2024_07.csv",
    ),
]
