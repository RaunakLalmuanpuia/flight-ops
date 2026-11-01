import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from flightops import db


@pytest.fixture
def conn():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS flightops_test WITH (FORCE)")
        admin.execute("CREATE DATABASE flightops_test")
    with db.connect(make_conninfo(url, dbname="flightops_test")) as c:
        db.migrate(c)
        yield c
