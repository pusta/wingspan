// WingSpan frontend — vanilla JS, no build step.
const API = "/api";

let flightsData = [];
let map, flightsLayer;

document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initMap();
  initForm();
  initAutocomplete({
    searchId: "origin-search",
    suggestionsId: "origin-suggestions",
    searchUrl: `${API}/airports/search`,
    hiddenFields: { "origin-iata": "iata" },
    renderItem: (a) => `
      <div class="suggestion" data-values='${JSON.stringify({iata: a.iata}).replace(/'/g, "&#39;")}'
           data-label="${a.iata} — ${escapeHtml(a.city)}, ${escapeHtml(a.country)}">
        <div><span class="code">${a.iata}</span><span class="name">${escapeHtml(a.name)}</span></div>
        <div class="loc">${escapeHtml(a.city)}, ${escapeHtml(a.country)}</div>
      </div>`,
  });
  initAutocomplete({
    searchId: "dest-search",
    suggestionsId: "dest-suggestions",
    searchUrl: `${API}/airports/search`,
    hiddenFields: { "dest-iata": "iata" },
    renderItem: (a) => `
      <div class="suggestion" data-values='${JSON.stringify({iata: a.iata}).replace(/'/g, "&#39;")}'
           data-label="${a.iata} — ${escapeHtml(a.city)}, ${escapeHtml(a.country)}">
        <div><span class="code">${a.iata}</span><span class="name">${escapeHtml(a.name)}</span></div>
        <div class="loc">${escapeHtml(a.city)}, ${escapeHtml(a.country)}</div>
      </div>`,
  });
  initAutocomplete({
    searchId: "airline-search",
    suggestionsId: "airline-suggestions",
    searchUrl: `${API}/airlines/search`,
    hiddenFields: { "airline-iata": "iata", "airline-name": "name" },
    allowFreeText: true,           // let the user type a carrier we haven't seeded
    freeTextHiddenField: "airline-name",
    renderItem: (a) => `
      <div class="suggestion"
           data-values='${JSON.stringify({iata: a.iata, name: a.name}).replace(/'/g, "&#39;")}'
           data-label="${a.iata} — ${escapeHtml(a.name)}">
        <div><span class="code">${a.iata}</span><span class="name">${escapeHtml(a.name)}</span></div>
        ${a.country ? `<div class="loc">${escapeHtml(a.country)}</div>` : ""}
      </div>`,
  });
  loadFlights();
});

/* ---------- View switching ---------- */
function initNav() {
  document.querySelectorAll("nav button").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
}

function switchView(name) {
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name)
  );
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === `view-${name}`)
  );
  if (name === "map" && map) setTimeout(() => map.invalidateSize(), 50);
  if (name === "stats") loadStats();
}

/* ---------- Map ---------- */
function initMap() {
  map = L.map("map", { worldCopyJump: true, zoomControl: true }).setView([20, 0], 2);
  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
      attribution: '© OpenStreetMap contributors © CARTO',
      subdomains: "abcd",
      maxZoom: 10,
    }
  ).addTo(map);
  flightsLayer = L.layerGroup().addTo(map);
}

function drawFlights() {
  if (!flightsLayer) return;
  flightsLayer.clearLayers();

  const airports = new Map(); // iata -> { lat, lon, label, count }
  flightsData.forEach((f) => {
    for (const side of ["origin", "dest"]) {
      const iata = f[`${side}_iata`];
      const entry = airports.get(iata) || {
        lat: f[`${side}_lat`],
        lon: f[`${side}_lon`],
        label: `${iata} — ${f[`${side}_city`]}`,
        count: 0,
      };
      entry.count += 1;
      airports.set(iata, entry);
    }

    L.geodesic(
      [[[f.origin_lat, f.origin_lon], [f.dest_lat, f.dest_lon]]],
      { color: "#3b82f6", weight: 1.6, opacity: 0.75 }
    ).addTo(flightsLayer);
  });

  airports.forEach(({ lat, lon, label, count }) => {
    const radius = Math.min(3 + count * 0.6, 8);
    L.circleMarker([lat, lon], {
      radius,
      color: "#60a5fa",
      fillColor: "#3b82f6",
      fillOpacity: 0.85,
      weight: 1.5,
    })
      .bindTooltip(`${label} (${count} flight${count !== 1 ? "s" : ""})`)
      .addTo(flightsLayer);
  });
}

/* ---------- Flights data ---------- */
async function loadFlights() {
  const res = await fetch(`${API}/flights`);
  flightsData = await res.json();
  renderFlights();
  drawFlights();
  updateYearFilter();
}

function renderFlights() {
  const container = document.getElementById("flights-list");
  const yearFilter = document.getElementById("year-filter").value;
  const filtered = yearFilter
    ? flightsData.filter((f) => f.date.startsWith(yearFilter))
    : flightsData;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty">No flights yet. Click <strong>+ Add Flight</strong> to log your first one.</div>`;
    return;
  }

  container.innerHTML = filtered
    .map((f) => {
      const miles = Math.round(f.distance_nm * 1.15078).toLocaleString();
      const parts = [
        f.airline && `${f.airline}${f.flight_number ? " " + f.flight_number : ""}`,
        `${miles} mi`,
        formatDuration(f.duration_minutes),
        f.aircraft,
        f.travel_class,
      ].filter(Boolean);
      const cityLine = `${escapeHtml(f.origin_city)} → ${escapeHtml(f.dest_city)}`;
      const logo = airlineLogo(f.airline_iata, f.airline);
      return `
        <div class="flight-card">
          <div class="flight-date">${f.date}</div>
          <div class="flight-main">
            ${logo}
            <div class="flight-detail">
              <div class="flight-route">
                ${f.origin_iata}<span class="arrow">→</span>${f.dest_iata}
                <span class="flight-cities">${cityLine}</span>
              </div>
              <div class="flight-info">${parts.join(" · ")}</div>
            </div>
          </div>
          <div class="flight-actions">
            <button class="flight-edit" data-id="${f.id}" title="Edit flight">✎</button>
            <button class="flight-delete" data-id="${f.id}" title="Delete flight">✕</button>
          </div>
        </div>`;
    })
    .join("");

  container.querySelectorAll(".flight-delete").forEach((btn) => {
    btn.addEventListener("click", () => deleteFlight(Number(btn.dataset.id)));
  });
  container.querySelectorAll(".flight-edit").forEach((btn) => {
    btn.addEventListener("click", () => startEdit(Number(btn.dataset.id)));
  });
}

function formatDuration(min) {
  if (!min) return "";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Build the airline-logo slot for a flight card.
 * Uses the pics.avs.io CDN (free, no auth). If the image fails to load
 * (airline not in their catalog, offline, etc.) we fall back to a colored
 * initial badge — `onerror` swaps the img for the sibling fallback.
 */
function airlineLogo(iata, airlineName) {
  const initials = initialsFor(airlineName || iata || "?");
  const bg = colorFor(iata || airlineName || "?");
  const fallback = `
    <div class="logo-fallback" style="background: ${bg}"
         aria-label="${escapeHtml(airlineName || iata || "Unknown")}">${escapeHtml(initials)}</div>`;
  if (!iata) {
    return `<div class="logo-slot">${fallback}</div>`;
  }
  return `
    <div class="logo-slot">
      <img class="logo-img"
           src="https://pics.avs.io/100/30/${encodeURIComponent(iata)}@2x.png"
           alt="${escapeHtml(airlineName || iata)}"
           loading="lazy"
           onerror="this.remove()" />
      ${fallback}
    </div>`;
}

function initialsFor(name) {
  // Take up to two word-initials, or the first two chars if single word
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function colorFor(key) {
  // Deterministic pastel-ish color from a string — stable per airline/IATA
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  const hue = Math.abs(h) % 360;
  return `hsl(${hue}, 55%, 35%)`;
}

function updateYearFilter() {
  const years = [...new Set(flightsData.map((f) => f.date.slice(0, 4)))]
    .sort()
    .reverse();
  const sel = document.getElementById("year-filter");
  const current = sel.value;
  sel.innerHTML =
    '<option value="">All years</option>' +
    years.map((y) => `<option value="${y}">${y}</option>`).join("");
  sel.value = current;
  sel.onchange = renderFlights;
}

async function deleteFlight(id) {
  if (!confirm("Delete this flight?")) return;
  const res = await fetch(`${API}/flights/${id}`, { method: "DELETE" });
  if (res.ok) {
    await loadFlights();
  } else {
    alert("Failed to delete flight.");
  }
}

/* ---------- Add / edit flight form ---------- */
function initForm() {
  const form = document.getElementById("add-flight-form");
  const cancelBtn = document.getElementById("cancel-edit");

  // Default date to today
  form.querySelector('input[name="date"]').value = new Date()
    .toISOString()
    .slice(0, 10);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    if (!data.origin_iata || !data.dest_iata) {
      alert("Please pick both airports from the suggestion list.");
      return;
    }
    // Strip empty strings; coerce duration to int or drop it
    const editingId = data.id;
    delete data.id;
    for (const k of Object.keys(data)) {
      if (data[k] === "") delete data[k];
    }
    if (data.duration_minutes) {
      data.duration_minutes = parseInt(data.duration_minutes, 10);
    }

    const url = editingId ? `${API}/flights/${editingId}` : `${API}/flights`;
    const method = editingId ? "PUT" : "POST";
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (res.ok) {
      resetForm();
      await loadFlights();
      switchView("flights");
    } else {
      const err = await res.json().catch(() => ({}));
      alert("Error: " + (err.detail || "Could not save flight"));
    }
  });

  cancelBtn.addEventListener("click", () => {
    resetForm();
    switchView("flights");
  });
}

function resetForm() {
  const form = document.getElementById("add-flight-form");
  form.reset();
  document.getElementById("flight-id").value = "";
  document.getElementById("origin-search").value = "";
  document.getElementById("dest-search").value = "";
  document.getElementById("origin-iata").value = "";
  document.getElementById("dest-iata").value = "";
  document.getElementById("airline-search").value = "";
  document.getElementById("airline-name").value = "";
  document.getElementById("airline-iata").value = "";
  form.querySelector('input[name="date"]').value = new Date()
    .toISOString()
    .slice(0, 10);
  document.getElementById("add-form-title").textContent = "Add Flight";
  document.getElementById("form-submit").textContent = "Save Flight";
  document.getElementById("cancel-edit").hidden = true;
}

function startEdit(id) {
  const f = flightsData.find((x) => x.id === id);
  if (!f) return;
  const form = document.getElementById("add-flight-form");

  document.getElementById("flight-id").value = f.id;
  form.elements.date.value = f.date;
  form.elements.flight_number.value = f.flight_number || "";
  form.elements.aircraft.value = f.aircraft || "";
  form.elements.seat.value = f.seat || "";
  form.elements.travel_class.value = f.travel_class || "";
  form.elements.duration_minutes.value = f.duration_minutes || "";
  form.elements.notes.value = f.notes || "";

  // Airline autocomplete — prefill visible + both hidden inputs
  const airlineLabel = f.airline_iata
    ? `${f.airline_iata} — ${f.airline || ""}`
    : (f.airline || "");
  document.getElementById("airline-search").value = airlineLabel;
  document.getElementById("airline-name").value = f.airline || "";
  document.getElementById("airline-iata").value = f.airline_iata || "";

  document.getElementById("origin-search").value =
    `${f.origin_iata} — ${f.origin_city}, ${f.origin_country}`;
  document.getElementById("origin-iata").value = f.origin_iata;
  document.getElementById("dest-search").value =
    `${f.dest_iata} — ${f.dest_city}, ${f.dest_country}`;
  document.getElementById("dest-iata").value = f.dest_iata;

  document.getElementById("add-form-title").textContent = `Edit Flight ${f.origin_iata} → ${f.dest_iata}`;
  document.getElementById("form-submit").textContent = "Update Flight";
  document.getElementById("cancel-edit").hidden = false;
  switchView("add");
}

/* ---------- Generic autocomplete ---------- */
// Used for both airport pickers and the airline picker. Options:
//   searchId         - id of the visible <input type="text">
//   suggestionsId    - id of the .suggestions div
//   searchUrl        - API endpoint returning a JSON array of items
//   hiddenFields     - map of { hiddenInputId: keyInApiResponse }
//                      (on pick, each hidden input is set from that key)
//   renderItem       - (item) => HTML string for one suggestion; each
//                      suggestion element MUST have data-label (text shown
//                      in the input after pick) and data-values (JSON map
//                      with keys matching hiddenFields values)
//   allowFreeText    - if true, the user is allowed to type free text that
//                      doesn't match any suggestion; the value is written
//                      into `freeTextHiddenField` as-is, with the code
//                      hidden field left blank
//   freeTextHiddenField - id of the hidden input to fill when allowFreeText
function initAutocomplete({
  searchId, suggestionsId, searchUrl, hiddenFields,
  renderItem, allowFreeText = false, freeTextHiddenField = null,
}) {
  const input = document.getElementById(searchId);
  const sugBox = document.getElementById(suggestionsId);
  const hiddenIds = Object.keys(hiddenFields);
  let debounce;

  function clearHidden() {
    hiddenIds.forEach((id) => { document.getElementById(id).value = ""; });
  }

  input.addEventListener("input", () => {
    clearHidden();
    if (allowFreeText && freeTextHiddenField) {
      // carry the user's free-text forward in case they don't pick a suggestion
      document.getElementById(freeTextHiddenField).value = input.value;
    }
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) {
      sugBox.classList.remove("open");
      sugBox.innerHTML = "";
      return;
    }
    debounce = setTimeout(async () => {
      const res = await fetch(`${searchUrl}?q=${encodeURIComponent(q)}`);
      const items = await res.json();
      if (!Array.isArray(items) || items.length === 0) {
        sugBox.classList.remove("open");
        return;
      }
      sugBox.innerHTML = items.map(renderItem).join("");
      sugBox.classList.add("open");
      sugBox.querySelectorAll(".suggestion").forEach((el) => {
        el.addEventListener("click", () => {
          input.value = el.dataset.label;
          const values = JSON.parse(el.dataset.values);
          for (const [hiddenId, key] of Object.entries(hiddenFields)) {
            document.getElementById(hiddenId).value = values[key] ?? "";
          }
          sugBox.classList.remove("open");
        });
      });
    }, 200);
  });

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !sugBox.contains(e.target)) {
      sugBox.classList.remove("open");
    }
  });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- Stats ---------- */
async function loadStats() {
  const res = await fetch(`${API}/stats`);
  const s = await res.json();
  const grid = document.getElementById("stats-grid");

  const cards = [
    `<div class="stat-card">
      <div class="stat-label">Total Flights</div>
      <div class="stat-value">${s.flight_count}</div>
    </div>`,
    `<div class="stat-card">
      <div class="stat-label">Miles Flown</div>
      <div class="stat-value">${Math.round(s.total_miles).toLocaleString()}</div>
      <div class="stat-sub">${Math.round(s.total_kilometers).toLocaleString()} km · ${Math.round(s.total_nautical_miles).toLocaleString()} nm</div>
    </div>`,
    `<div class="stat-card">
      <div class="stat-label">Time in Air</div>
      <div class="stat-value">${s.total_hours.toFixed(1)}</div>
      <div class="stat-sub">hours</div>
    </div>`,
    `<div class="stat-card">
      <div class="stat-label">Airports Visited</div>
      <div class="stat-value">${s.airports_visited}</div>
    </div>`,
  ];

  if (s.longest_flight) {
    const lf = s.longest_flight;
    const miles = Math.round(lf.distance_nm * 1.15078).toLocaleString();
    cards.push(`<div class="stat-card">
      <div class="stat-label">Longest Flight</div>
      <div class="stat-value" style="font-size: 1.4rem; font-family: ui-monospace, monospace;">${lf.origin_iata} → ${lf.dest_iata}</div>
      <div class="stat-sub">${miles} mi · ${escapeHtml(lf.origin_city)} to ${escapeHtml(lf.dest_city)}</div>
    </div>`);
  }

  if (s.top_route) {
    cards.push(`<div class="stat-card">
      <div class="stat-label">Most-Flown Route</div>
      <div class="stat-value" style="font-size: 1.4rem; font-family: ui-monospace, monospace;">${s.top_route.a} ↔ ${s.top_route.b}</div>
      <div class="stat-sub">${s.top_route.count} flights (both directions)</div>
    </div>`);
  }

  if (s.top_airport) {
    cards.push(`<div class="stat-card">
      <div class="stat-label">Most-Visited Airport</div>
      <div class="stat-value" style="font-size: 1.6rem; font-family: ui-monospace, monospace;">${s.top_airport.iata}</div>
      <div class="stat-sub">${escapeHtml(s.top_airport.city)} · ${s.top_airport.count} visits</div>
    </div>`);
  }

  if (s.top_airlines && s.top_airlines.length > 0) {
    cards.push(`<div class="stat-card" style="grid-column: span 2;">
      <div class="stat-label">Top Airlines</div>
      ${s.top_airlines.map((a) =>
        `<div class="airline-row"><span>${escapeHtml(a.airline)}</span><span style="color: var(--muted)">${a.count} flight${a.count !== 1 ? "s" : ""}</span></div>`
      ).join("")}
    </div>`);
  }

  if (s.by_year && s.by_year.length > 1) {
    cards.push(`<div class="stat-card" style="grid-column: span 2;">
      <div class="stat-label">By Year</div>
      ${s.by_year.map((y) =>
        `<div class="airline-row"><span>${y.year}</span><span style="color: var(--muted)">${y.flights} flights · ${Math.round(y.miles).toLocaleString()} mi · ${y.hours}h</span></div>`
      ).join("")}
    </div>`);
  }

  grid.innerHTML = cards.join("");
}
