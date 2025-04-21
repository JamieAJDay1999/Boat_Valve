/**
 * script.js – Leaflet map, data fetching, valve toggling, history log
 */

/* ------------------------------------------------------------------ */
/*  GLOBALS                                                           */
/* ------------------------------------------------------------------ */
let map;
let landLayer   = L.layerGroup();
let bufferLayer = L.layerGroup();
let boatLayer   = L.layerGroup();
const boatMarkers = {};            // { boatId: marker }
let currentCountryCode = null;     // which dataset is shown

/* ------------------------------------------------------------------ */
/*  DOM references                                                    */
/* ------------------------------------------------------------------ */
const loadingEl  = document.getElementById('loading');
const errorEl    = document.getElementById('errorMessage');
const historyEl  = document.getElementById('historyLog');

/* ------------------------------------------------------------------ */
/*  UI helpers                                                        */
/* ------------------------------------------------------------------ */
function showLoading(msg = "Loading…") {
    loadingEl.textContent = msg;
    loadingEl.style.display = 'flex';
}
function hideLoading()  { loadingEl.style.display = 'none'; }
function displayError(msg) {
    errorEl.textContent = msg;
    errorEl.style.display = 'block';
}
function clearError()   {
    errorEl.style.display = 'none';
    errorEl.textContent  = '';
}

/* ------------------------------------------------------------------ */
/*  MAP init                                                          */
/* ------------------------------------------------------------------ */
function initMap() {
    map = L.map('map').setView([51.5, -0.09], 5);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    landLayer.addTo(map);
    bufferLayer.addTo(map);
    boatLayer.addTo(map);

    fetchAndDisplayHistory();
}

/* ------------------------------------------------------------------ */
/*  DATA fetch – map, boats                                           */
/* ------------------------------------------------------------------ */
async function loadMapData(code) {
    currentCountryCode = code;
    showLoading(`Loading ${code.toUpperCase()} data…`);
    clearError();

    try {
        const res = await fetch(`/api/mapdata/${code}`);
        if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            throw new Error(j.description || res.statusText);
        }
        const data = await res.json();

        if (data.errors) displayError(data.errors.join(' ; '));

        /* ---- clear layers & caches ---- */
        landLayer.clearLayers();
        bufferLayer.clearLayers();
        boatLayer.clearLayers();
        for (const k in boatMarkers) delete boatMarkers[k];

        /* ---- land ---- */
        if (data.land) {
            L.geoJSON(JSON.parse(data.land), {
                style: { color:'#2a4018', weight:1,
                         fillColor:'#88aa77', fillOpacity:0.5 }
            }).addTo(landLayer);
        }

        /* ---- buffer ---- */
        if (data.buffer) {
            L.geoJSON(JSON.parse(data.buffer), {
                style: { color:'#ff0000', weight:2,
                         fillColor:'#ffcccc', fillOpacity:0.3,
                         dashArray:'5,5' }
            }).addTo(bufferLayer);
        }

        /* ---- boats ---- */
        if (data.boats?.length) {
            data.boats.forEach(b => {
                const colour = b.valveOpen ? 'red' : 'blue';
                const m = L.circleMarker([b.lat, b.lng], {
                    radius:6, fillColor: colour, color:'#000',
                    weight:1, opacity:1, fillOpacity:0.8
                }).addTo(boatLayer);

                boatMarkers[b.id] = m;
                m.bindPopup(`
                    <b>${b.name}</b> (ID: ${b.id})<br>
                    Lat: ${b.lat}, Lng: ${b.lng}<br>
                    Valve: <span id="valve-status-${b.id}">
                        ${b.valveOpen ? 'Open' : 'Closed'}</span><br>
                    <button onclick="toggleValve(${b.id})">
                        ${b.valveOpen ? 'Close Valve' : 'Open Valve'}
                    </button>
                `);
            });
        }

        /* ---- view ---- */
        if (data.center && data.zoom) map.setView(data.center, data.zoom);

    } catch (e) {
        console.error(e);
        displayError(e.message);
    } finally {
        hideLoading();
    }
}

/* ------------------------------------------------------------------ */
/*  RANDOMISE boats                                                   */
/* ------------------------------------------------------------------ */
async function randomiseBoats() {
    if (!currentCountryCode) {
        displayError("Select a country first.");
        return;
    }
    showLoading("Randomising boat locations…");
    clearError();

    try {
        const res = await fetch(`/api/boats/randomise/${currentCountryCode}`, {
            method: 'POST'
        });
        if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            throw new Error(j.message || res.statusText);
        }
        await res.json();                // ignore payload – just refresh map
        await loadMapData(currentCountryCode);
    } catch (e) {
        console.error(e);
        displayError(e.message);
    } finally {
        hideLoading();
    }
}

/* ------------------------------------------------------------------ */
/*  Toggle valve                                                      */
/* ------------------------------------------------------------------ */
async function toggleValve(id) {
    const marker = boatMarkers[id];
    if (!marker) return;

    showLoading("Updating valve…");
    clearError();

    try {
        const res = await fetch(`/api/valve/toggle/${id}`, {method:'POST'});
        if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            throw new Error(j.message || res.statusText);
        }
        const r = await res.json();

        const open = r.valveOpen;
        marker.setStyle({ fillColor: open ? 'red' : 'blue' });

        /* update popup content */
        const pop = marker.getPopup();
        const div = document.createElement('div');
        div.innerHTML = pop.getContent();
        div.querySelector(`#valve-status-${id}`).textContent =
            open ? 'Open' : 'Closed';
        div.querySelector('button').textContent =
            open ? 'Close Valve' : 'Open Valve';
        pop.setContent(div.innerHTML);

        if (open) fetchAndDisplayHistory();

    } catch (e) {
        console.error(e);
        displayError(e.message);
    } finally {
        hideLoading();
    }
}

/* ------------------------------------------------------------------ */
/*  History log                                                       */
/* ------------------------------------------------------------------ */
async function fetchAndDisplayHistory() {
    if (!historyEl) return;
    historyEl.innerHTML = '<p>Loading history…</p>';

    try {
        const res = await fetch('/api/history');
        if (!res.ok) throw new Error(res.statusText);
        const hist = await res.json();

        if (!hist.length) {
            historyEl.innerHTML = '<p>No valve openings yet.</p>';
            return;
        }
        let html = '<ul>';
        hist.forEach(h => {
            const t = new Date(h.timestamp).toLocaleString();
            html += `
              <li class="${h.inZone ? 'illegal' : 'legal'}">
                <strong>${h.boatName}</strong> (ID: ${h.boatId})
                – ${h.country.toUpperCase()}<br>
                Status: <strong>${h.status}</strong><br>
                Time: ${t}<br>
                Location: ${h.lat.toFixed(4)}, ${h.lng.toFixed(4)}
                ${h.inZone ? '<br><span style="color:red;font-weight:bold;">ALERT: IN BUFFER</span>' : ''}
              </li>`;
        });
        html += '</ul>';
        historyEl.innerHTML = html;

    } catch (e) {
        console.error(e);
        historyEl.innerHTML = `<p style="color:red;">${e.message}</p>`;
    }
}

/* ------------------------------------------------------------------ */
/*  Start                                                             */
/* ------------------------------------------------------------------ */
document.addEventListener('DOMContentLoaded', initMap);
