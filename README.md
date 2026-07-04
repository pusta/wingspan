# WingSpan ✈️

A self-hosted flight tracker. Log every flight you take, see your routes drawn as great-circles on a world map, and watch your lifetime stats climb.

## Features

- Log flights: airline, flight number, date, origin, destination, aircraft, seat, class, notes
- **Airline autocomplete + logos** — pick from a seeded carrier database; logos render on every flight card via the `pics.avs.io` CDN, with a colored initial-badge fallback when a carrier isn't in the catalog
- **Edit flights** after logging — useful for fixing typos or adding details later
- **Auto-calculated distance** using haversine (great-circle)
- **Auto-estimated duration** with optional manual override per flight
- **Interactive world map** with route overlays (Leaflet + geodesic curves, dark CARTO tiles)
- **Rich stats dashboard**: total miles, hours, airports visited, longest flight, most-flown route, most-visited airport, top airlines, year-by-year breakdown
- **Year filter** for flights list and stats
- **CSV export** for backup or spreadsheet analysis
- **Airport + airline autocomplete** (~7,000 airports, ~6,000 airlines from OpenFlights)
- **Responsive UI** — single layout reflows from desktop to mobile
- **Single-container** deploy with Docker / Podman
- **Additive schema migrations** — existing databases upgrade in-place on startup, with automatic backfill of `airline_iata` where the free-text airline name matches a seeded carrier

## Quick start

```bash
git clone <your-repo> wingspan
cd wingspan
docker compose up --build -d
```

Open http://localhost:8000

On first boot, the app downloads the OpenFlights airport database (~1 MB, 7,000+ airports) into SQLite. This takes a few seconds. Subsequent boots are instant.

## Data persistence

All your data lives in `./data/wingspan.db`. Back up that single file and you've backed up everything. Perfect fit for your existing Proxmox backup workflow.

## Architecture

```
┌────────────────────────────────────────┐
│ Browser (desktop or mobile)            │
│   • Leaflet map + leaflet.geodesic     │
│   • Vanilla JS, no build step          │
└────────────┬───────────────────────────┘
             │ HTTP
             ▼
┌────────────────────────────────────────┐
│ FastAPI container (uvicorn, port 8000) │
│   ├─ /api/flights       (CRUD)         │
│   ├─ /api/airports/search (autocompl.) │
│   ├─ /api/stats         (aggregates)   │
│   └─ /                  (static UI)    │
└────────────┬───────────────────────────┘
             │
             ▼
┌────────────────────────────────────────┐
│ SQLite  →  /data/wingspan.db           │
│   • airports (seeded from OpenFlights) │
│   • flights  (your log)                │
└────────────────────────────────────────┘
```

## Project layout

```
wingspan/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── main.py        # FastAPI app + routes
│   ├── database.py    # SQLite schema + airport seeding
│   └── geo.py         # haversine
└── static/
    ├── index.html
    ├── style.css
    └── app.js
```

## API reference

| Method   | Path                          | Purpose                               |
|----------|-------------------------------|---------------------------------------|
| `POST`   | `/api/flights`                | Add a flight                          |
| `GET`    | `/api/flights?year=2026`      | List flights (optional year)          |
| `PUT`    | `/api/flights/{id}`           | Edit a flight                         |
| `DELETE` | `/api/flights/{id}`           | Remove a flight                       |
| `GET`    | `/api/airports/search?q=jfk`  | Airport autocomplete                  |
| `GET`    | `/api/airlines/search?q=delta`| Airline autocomplete                  |
| `GET`    | `/api/stats?year=2026`        | Aggregate stats (optional year)       |
| `GET`    | `/api/export.csv`             | Download all flights as CSV           |

Interactive docs: http://localhost:8000/docs

## Deploying to your home lab

Behind a reverse proxy (Caddy / Traefik / nginx), just forward to port 8000. The app has no auth built in — put it behind your Authelia / Authentik / VPN / Tailscale setup.

Example Caddy block:
```
wingspan.home.lan {
    reverse_proxy wingspan-host:8000
}
```

## Roadmap ideas

Things to consider adding next:
- **CSV import** to bulk-load historical flights from spreadsheets or exports
- **Import from TripIt / email confirmations** (parse .ics calendar invites)
- **Photo attachments** per flight
- **Airline logos** on the flight list
- **Authentication** (single-user password, or OIDC via your Authentik)
- **Live flight lookup** via FlightAware / AviationStack API to auto-fill duration and aircraft
- **Heatmap layer** for most-flown routes
- **Map per-year filter** synced with the flights list filter

## Credits

- Airport data: [OpenFlights](https://openflights.org/data.html) (Open Database License)
- Map tiles: OpenStreetMap contributors, rendered by CARTO
- Map library: [Leaflet](https://leafletjs.com/) + [leaflet.geodesic](https://github.com/henrythasler/Leaflet.Geodesic)
