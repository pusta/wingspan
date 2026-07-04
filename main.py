"""WingSpan — flight tracker API."""
import csv
import io
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database as db
from .geo import haversine_km, km_to_nm


class FlightIn(BaseModel):
    date: str = Field(..., description="ISO date, e.g. 2026-04-15")
    airline: Optional[str] = None
    airline_iata: Optional[str] = None
    flight_number: Optional[str] = None
    origin_iata: str
    dest_iata: str
    duration_minutes: Optional[int] = None
    aircraft: Optional[str] = None
    seat: Optional[str] = None
    travel_class: Optional[str] = None
    notes: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="WingSpan", lifespan=lifespan)


@app.post("/api/flights")
def add_flight(flight: FlightIn):
    origin_code = flight.origin_iata.upper().strip()
    dest_code = flight.dest_iata.upper().strip()
    conn = db.get_db()
    try:
        origin = conn.execute(
            "SELECT lat, lon FROM airports WHERE iata = ?", (origin_code,)
        ).fetchone()
        dest = conn.execute(
            "SELECT lat, lon FROM airports WHERE iata = ?", (dest_code,)
        ).fetchone()
        if not origin or not dest:
            raise HTTPException(400, f"Unknown airport code: {origin_code if not origin else dest_code}")

        dist_km = haversine_km(origin["lat"], origin["lon"], dest["lat"], dest["lon"])
        dist_nm = km_to_nm(dist_km)

        # Rough duration estimate if the user didn't supply one:
        # 30 min for taxi/climb/descent + cruise at ~800 km/h.
        duration = flight.duration_minutes
        if duration is None:
            duration = int(30 + (dist_km / 800.0) * 60)

        cur = conn.execute(
            """
            INSERT INTO flights
              (date, airline, airline_iata, flight_number, origin_iata, dest_iata,
               distance_nm, duration_minutes, aircraft, seat, travel_class, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                flight.date,
                flight.airline,
                (flight.airline_iata or "").upper().strip() or None,
                flight.flight_number,
                origin_code,
                dest_code,
                dist_nm,
                duration,
                flight.aircraft,
                flight.seat,
                flight.travel_class,
                flight.notes,
            ),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.get("/api/flights")
def list_flights(year: Optional[int] = None):
    conn = db.get_db()
    try:
        query = """
            SELECT
              f.id, f.date, f.airline, f.airline_iata, f.flight_number,
              f.origin_iata, f.dest_iata,
              f.distance_nm, f.duration_minutes,
              f.aircraft, f.seat, f.travel_class, f.notes,
              o.name AS origin_name, o.city AS origin_city,
              o.country AS origin_country,
              o.lat  AS origin_lat,  o.lon  AS origin_lon,
              d.name AS dest_name,   d.city AS dest_city,
              d.country AS dest_country,
              d.lat  AS dest_lat,    d.lon  AS dest_lon
            FROM flights f
            JOIN airports o ON f.origin_iata = o.iata
            JOIN airports d ON f.dest_iata   = d.iata
        """
        params: list = []
        if year:
            query += " WHERE strftime('%Y', f.date) = ?"
            params.append(str(year))
        query += " ORDER BY f.date DESC, f.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.put("/api/flights/{flight_id}")
def update_flight(flight_id: int, flight: FlightIn):
    origin_code = flight.origin_iata.upper().strip()
    dest_code = flight.dest_iata.upper().strip()
    conn = db.get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM flights WHERE id = ?", (flight_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Flight not found")

        origin = conn.execute(
            "SELECT lat, lon FROM airports WHERE iata = ?", (origin_code,)
        ).fetchone()
        dest = conn.execute(
            "SELECT lat, lon FROM airports WHERE iata = ?", (dest_code,)
        ).fetchone()
        if not origin or not dest:
            raise HTTPException(400, f"Unknown airport code: {origin_code if not origin else dest_code}")

        dist_km = haversine_km(origin["lat"], origin["lon"], dest["lat"], dest["lon"])
        dist_nm = km_to_nm(dist_km)
        duration = flight.duration_minutes
        if duration is None:
            duration = int(30 + (dist_km / 800.0) * 60)

        conn.execute(
            """
            UPDATE flights SET
              date=?, airline=?, airline_iata=?, flight_number=?,
              origin_iata=?, dest_iata=?,
              distance_nm=?, duration_minutes=?, aircraft=?, seat=?,
              travel_class=?, notes=?
            WHERE id=?
            """,
            (flight.date, flight.airline,
             (flight.airline_iata or "").upper().strip() or None,
             flight.flight_number,
             origin_code, dest_code, dist_nm, duration,
             flight.aircraft, flight.seat, flight.travel_class, flight.notes,
             flight_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/flights/{flight_id}")
def delete_flight(flight_id: int):
    conn = db.get_db()
    try:
        cur = conn.execute("DELETE FROM flights WHERE id = ?", (flight_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Flight not found")
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/airports/search")
def search_airports(q: str, limit: int = 10):
    q = q.strip()
    if not q:
        return []
    conn = db.get_db()
    try:
        pattern = f"%{q}%"
        rows = conn.execute(
            """
            SELECT iata, icao, name, city, country, lat, lon
            FROM airports
            WHERE iata LIKE ? OR name LIKE ? OR city LIKE ?
            ORDER BY
              CASE
                WHEN iata = ?            THEN 0
                WHEN iata LIKE ?         THEN 1
                WHEN city LIKE ?         THEN 2
                ELSE                          3
              END,
              name
            LIMIT ?
            """,
            (pattern, pattern, pattern,
             q.upper(), f"{q.upper()}%", f"{q}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/airlines/search")
def search_airlines(q: str, limit: int = 10):
    q = q.strip()
    if not q:
        return []
    conn = db.get_db()
    try:
        pattern = f"%{q}%"
        rows = conn.execute(
            """
            SELECT iata, icao, name, country, active
            FROM airlines
            WHERE (iata LIKE ? OR name LIKE ?)
            ORDER BY
              active DESC,
              CASE
                WHEN iata = ?    THEN 0
                WHEN iata LIKE ? THEN 1
                WHEN name LIKE ? THEN 2
                ELSE                  3
              END,
              name
            LIMIT ?
            """,
            (pattern, pattern,
             q.upper(), f"{q.upper()}%", f"{q}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/stats")
def get_stats(year: Optional[int] = None):
    conn = db.get_db()
    try:
        where = ""
        params: list = []
        if year:
            where = " WHERE strftime('%Y', f.date) = ?"
            params.append(str(year))

        totals = conn.execute(
            f"""
            SELECT
              COUNT(*)                              AS count,
              COALESCE(SUM(f.distance_nm), 0)       AS total_nm,
              COALESCE(SUM(f.duration_minutes), 0)  AS total_minutes
            FROM flights f
            {where}
            """,
            params,
        ).fetchone()

        # Distinct airports visited (origin OR destination)
        airports_sql = """
            SELECT COUNT(DISTINCT iata) AS n FROM (
              SELECT origin_iata AS iata FROM flights f {w}
              UNION
              SELECT dest_iata   AS iata FROM flights f {w}
            )
        """.format(w=where)
        airports_count = conn.execute(
            airports_sql, params + params
        ).fetchone()["n"]

        top_airlines = conn.execute(
            f"""
            SELECT f.airline, COUNT(*) AS count
            FROM flights f
            WHERE f.airline IS NOT NULL AND f.airline != ''
            {(' AND ' + where.replace('WHERE ', '')) if where else ''}
            GROUP BY f.airline
            ORDER BY count DESC
            LIMIT 5
            """,
            params,
        ).fetchall()

        # Longest flight
        longest = conn.execute(
            f"""
            SELECT f.id, f.date, f.origin_iata, f.dest_iata, f.distance_nm,
                   o.city AS origin_city, d.city AS dest_city
            FROM flights f
            JOIN airports o ON f.origin_iata = o.iata
            JOIN airports d ON f.dest_iata   = d.iata
            {where}
            ORDER BY f.distance_nm DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

        # Most-flown route (unordered pair — A→B and B→A count together)
        top_route = conn.execute(
            f"""
            SELECT
              MIN(f.origin_iata, f.dest_iata) AS a,
              MAX(f.origin_iata, f.dest_iata) AS b,
              COUNT(*) AS count
            FROM flights f
            {where}
            GROUP BY a, b
            ORDER BY count DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

        # Most-visited airport
        top_airport = conn.execute(
            f"""
            SELECT iata, COUNT(*) AS count, MAX(city) AS city FROM (
              SELECT f.origin_iata AS iata, o.city AS city
                FROM flights f JOIN airports o ON f.origin_iata = o.iata {where}
              UNION ALL
              SELECT f.dest_iata AS iata, d.city AS city
                FROM flights f JOIN airports d ON f.dest_iata = d.iata {where}
            )
            GROUP BY iata
            ORDER BY count DESC
            LIMIT 1
            """,
            params + params,
        ).fetchone()

        # Year-by-year breakdown (only when no year filter)
        by_year = []
        if not year:
            by_year = [
                dict(r) for r in conn.execute(
                    """
                    SELECT strftime('%Y', date) AS year,
                           COUNT(*) AS flights,
                           ROUND(SUM(distance_nm) * 1.15078) AS miles,
                           ROUND(SUM(duration_minutes) / 60.0, 1) AS hours
                    FROM flights
                    GROUP BY year
                    ORDER BY year DESC
                    """
                ).fetchall()
            ]

        nm = totals["total_nm"] or 0
        minutes = totals["total_minutes"] or 0
        return {
            "flight_count": totals["count"],
            "total_nautical_miles": round(nm, 1),
            "total_miles": round(nm * 1.15078, 1),
            "total_kilometers": round(nm * 1.852, 1),
            "total_hours": round(minutes / 60, 1),
            "airports_visited": airports_count,
            "top_airlines": [dict(r) for r in top_airlines],
            "longest_flight": dict(longest) if longest else None,
            "top_route": dict(top_route) if top_route and top_route["count"] > 1 else None,
            "top_airport": dict(top_airport) if top_airport else None,
            "by_year": by_year,
        }
    finally:
        conn.close()


@app.get("/api/export.csv")
def export_csv():
    """Export all flights as CSV for backup / spreadsheet use."""
    conn = db.get_db()
    try:
        rows = conn.execute(
            """
            SELECT date, airline, airline_iata, flight_number,
                   origin_iata, dest_iata,
                   ROUND(distance_nm * 1.15078, 1) AS miles,
                   duration_minutes, aircraft, seat, travel_class, notes
            FROM flights
            ORDER BY date ASC, id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "date", "airline", "airline_iata", "flight_number",
        "origin", "destination",
        "miles", "duration_minutes", "aircraft", "seat", "class", "notes",
    ])
    for r in rows:
        writer.writerow([r[k] if r[k] is not None else "" for k in r.keys()])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="wingspan-flights.csv"'},
    )


# Frontend (static files) — mounted last so /api/* takes precedence.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
