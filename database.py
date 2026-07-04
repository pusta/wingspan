"""SQLite database setup and airport-data seeding."""
import csv
import logging
import os
import sqlite3
import urllib.request
from pathlib import Path

log = logging.getLogger("wingspan.db")

DB_PATH = Path(os.environ.get("DB_PATH", "/data/wingspan.db"))

AIRPORTS_URL = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)

AIRLINES_URL = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS airports (
    iata    TEXT PRIMARY KEY,
    icao    TEXT,
    name    TEXT,
    city    TEXT,
    country TEXT,
    lat     REAL,
    lon     REAL
);

CREATE TABLE IF NOT EXISTS airlines (
    iata    TEXT PRIMARY KEY,
    icao    TEXT,
    name    TEXT,
    country TEXT,
    active  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS flights (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    date             TEXT NOT NULL,
    airline          TEXT,
    airline_iata     TEXT,
    flight_number    TEXT,
    origin_iata      TEXT NOT NULL,
    dest_iata        TEXT NOT NULL,
    distance_nm      REAL,
    duration_minutes INTEGER,
    aircraft         TEXT,
    seat             TEXT,
    travel_class     TEXT,
    notes            TEXT,
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (origin_iata) REFERENCES airports(iata),
    FOREIGN KEY (dest_iata)   REFERENCES airports(iata)
);

CREATE INDEX IF NOT EXISTS idx_flights_date ON flights(date);
CREATE INDEX IF NOT EXISTS idx_airports_city ON airports(city);
CREATE INDEX IF NOT EXISTS idx_airlines_name ON airlines(name);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --- Schema migrations -----------------------------------------------------
# Column additions for existing DBs. Each entry: (table, column, type).
# The migrate() step is idempotent — already-present columns are skipped.
NEW_COLUMNS = [
    ("flights", "aircraft",     "TEXT"),
    ("flights", "seat",         "TEXT"),
    ("flights", "travel_class", "TEXT"),
    ("flights", "airline_iata", "TEXT"),
]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply additive column migrations to keep older DBs up to date."""
    for table, col, coltype in NEW_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if col not in existing:
            log.info("Migrating: ALTER TABLE %s ADD COLUMN %s %s", table, col, coltype)
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)

        airport_count = conn.execute("SELECT COUNT(*) FROM airports").fetchone()[0]
        if airport_count == 0:
            log.info("No airports in DB — seeding from OpenFlights...")
            try:
                seeded = seed_airports(conn)
                log.info("Seeded %d airports.", seeded)
            except Exception as exc:
                log.warning("Airport seed failed: %s. App will run but search will be empty.", exc)

        airline_count = conn.execute("SELECT COUNT(*) FROM airlines").fetchone()[0]
        if airline_count == 0:
            log.info("No airlines in DB — seeding from OpenFlights...")
            try:
                seeded = seed_airlines(conn)
                log.info("Seeded %d airlines.", seeded)
            except Exception as exc:
                log.warning("Airline seed failed: %s. App will run but airline search will be empty.", exc)

        # One-time backfill: try to resolve existing free-text airline names to IATA codes.
        # Safe, idempotent — only fills airline_iata where it's currently NULL and an
        # exact (case-insensitive) name match exists.
        try:
            backfill = conn.execute(
                """
                UPDATE flights
                SET airline_iata = (
                    SELECT a.iata FROM airlines a
                    WHERE a.active = 1
                      AND LOWER(a.name) = LOWER(flights.airline)
                    LIMIT 1
                )
                WHERE airline_iata IS NULL
                  AND airline IS NOT NULL
                  AND airline != ''
                """
            )
            if backfill.rowcount:
                log.info("Backfilled airline_iata on %d existing flights.", backfill.rowcount)
        except Exception as exc:
            log.warning("Airline backfill skipped: %s", exc)

        conn.commit()
    finally:
        conn.close()


def seed_airports(conn: sqlite3.Connection) -> int:
    """Download the OpenFlights airports.dat file and insert into SQLite.

    The CSV has 14 columns; we only keep airports with a valid 3-letter IATA
    code and numeric coordinates.
    Columns: airport_id, name, city, country, iata, icao, lat, lon, altitude, ...
    """
    req = urllib.request.Request(AIRPORTS_URL, headers={"User-Agent": "wingspan"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")

    reader = csv.reader(data.splitlines())
    rows = []
    for r in reader:
        if len(r) < 8:
            continue
        iata = r[4].strip().strip('"')
        if not iata or iata == r"\N" or len(iata) != 3 or not iata.isalpha():
            continue
        try:
            lat = float(r[6])
            lon = float(r[7])
        except (ValueError, IndexError):
            continue
        rows.append((
            iata.upper(),
            r[5].strip().strip('"') or None,   # ICAO
            r[1].strip().strip('"'),            # name
            r[2].strip().strip('"'),            # city
            r[3].strip().strip('"'),            # country
            lat, lon,
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO airports "
        "(iata, icao, name, city, country, lat, lon) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def seed_airlines(conn: sqlite3.Connection) -> int:
    """Download the OpenFlights airlines.dat file and insert into SQLite.

    Columns: airline_id, name, alias, iata, icao, callsign, country, active
    We only keep airlines with a valid 2-character IATA code.
    Active flag ('Y'/'N') is stored as integer for filtering.
    """
    req = urllib.request.Request(AIRLINES_URL, headers={"User-Agent": "wingspan"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")

    reader = csv.reader(data.splitlines())
    rows = []
    seen = set()
    for r in reader:
        if len(r) < 8:
            continue
        iata = r[3].strip().strip('"').upper()
        if not iata or iata == r"\N" or len(iata) != 2:
            continue
        name = r[1].strip().strip('"')
        if not name or name == r"\N":
            continue
        # If multiple entries share an IATA code (common — historical carriers),
        # prefer the active one. We defer by checking 'seen' set.
        active = 1 if r[7].strip().strip('"').upper() == "Y" else 0
        key = (iata, active)
        if iata in seen and active == 0:
            continue
        if active == 1:
            seen.add(iata)
        icao = r[4].strip().strip('"')
        if icao == r"\N":
            icao = None
        country = r[6].strip().strip('"')
        if country == r"\N":
            country = None
        rows.append((iata, icao, name, country, active))

    # Sort so active airlines go first and get precedence via INSERT OR REPLACE semantics.
    rows.sort(key=lambda r: -r[4])  # active desc
    conn.executemany(
        "INSERT OR REPLACE INTO airlines (iata, icao, name, country, active) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)
