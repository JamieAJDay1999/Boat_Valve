document.addEventListener('DOMContentLoaded', () => {
    // --- Configuration ---
    const mapCenter = [43.51, 16.44]; // Split, Croatia
    const initialZoom = 11;
    const backendBaseUrl = 'http://127.0.0.1:5000';

    // --- DOM Elements ---
    const mapElement = document.getElementById('map');
    const historyLogElement = document.getElementById('historyLog');
    const searchInput = document.getElementById('searchInput');
    const searchButton = document.getElementById('searchButton');
    const searchResultSpan = document.getElementById('searchResult');
    const refreshHistoryButton = document.getElementById('refreshHistoryButton');

    // --- Map Initialization ---
    const map = L.map(mapElement).setView(mapCenter, initialZoom);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    // --- Global variables ---
    let markers = {};
    let allBoatsData = [];
    let zoneLayerGroup = L.layerGroup().addTo(map); // Layer group for the zone

    // --- Helper Functions ---
    function displayError(element, message) {
        console.error(message);
        if (element) {
            element.innerHTML = `<p style="color: red; padding: 10px;">Error: ${message}</p>`;
        }
    }

    function formatTimestamp(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' });
        } catch (e) { return isoString; }
    }

    // --- Zone Drawing (Handles GeoJSON) ---
    function drawZone(zoneDefinition) {
        zoneLayerGroup.clearLayers(); // Clear previous zone layers

        // Define the style for the GeoJSON polygon layer
        const zoneStyle = {
            className: 'exclusion-zone', // Use CSS class if defined
            fillColor: '#808080',        // Explicit grey fill
            fillOpacity: 0.35,           // Opacity for the fill
            stroke: true,                // Draw border
            color: '#505050',            // Border color
            weight: 1,                   // Border thickness
            interactive: false           // Make zone non-interactive
        };

        if (zoneDefinition.type === 'geojson' && zoneDefinition.data) {
            try {
                // The backend sends the GeoJSON as a string, parse it
                const geojsonData = JSON.parse(zoneDefinition.data);

                // Add the GeoJSON layer to the map
                L.geoJSON(geojsonData, { style: zoneStyle }).addTo(zoneLayerGroup);
                console.log("Drew GeoJSON buffer zone.");

            } catch (e) {
                console.error("Error parsing or drawing GeoJSON zone:", e);
                displayError(mapElement, "Failed to parse or draw the zone definition.");
            }
        } else if (zoneDefinition.type === 'error') {
             console.error("Error fetching zone definition from backend:", zoneDefinition.message);
             displayError(mapElement, `Could not load zone: ${zoneDefinition.message}`);
        }
         else {
            // Fallback or handle other types if needed (e.g., the old circles)
            console.warn("Received unexpected or empty zone definition type:", zoneDefinition.type);
             // Optionally draw nothing or show a message
        }
    }

    // --- History Display (Unchanged) ---
    function displayHistory(historyData) {
        if (!historyData || historyData.length === 0) {
            historyLogElement.innerHTML = '<p>No valve opening history recorded yet.</p>';
            return;
        }
        let tableHTML = `<table><thead><tr><th>Timestamp</th><th>Boat ID</th><th>Lat</th><th>Lng</th><th>Location</th></tr></thead><tbody>`;
        historyData.forEach(log => {
            const locationClass = log.inZone ? 'in-zone-true' : 'in-zone-false';
            const locationText = log.inZone ? 'Inside Zone (3NM)' : 'Outside Zone';
            tableHTML += `<tr class="${locationClass}"><td>${formatTimestamp(log.timestamp)}</td><td>${log.boatId}</td><td>${log.lat.toFixed(4)}</td><td>${log.lng.toFixed(4)}</td><td>${locationText}</td></tr>`;
        });
        tableHTML += '</tbody></table>';
        historyLogElement.innerHTML = tableHTML;
    }

    // --- Fetch and Display History (Unchanged) ---
    async function fetchAndDisplayHistory() {
        try {
            const response = await fetch(`${backendBaseUrl}/api/history`);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const historyData = await response.json();
            displayHistory(historyData);
        } catch (error) {
            displayError(historyLogElement, `Could not load history. ${error.message}`);
        }
    }

     // --- Marker and Popup Creation / Update (Unchanged) ---
     function createMarker(boat) {
        const valveStatus = boat.valveOpen ? 'Open' : 'Closed';
        const lightColorClass = boat.valveOpen ? 'red-light' : 'green-light';
        const customIcon = L.divIcon({ className: `marker-icon ${lightColorClass}`, iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -12] });
        const marker = L.marker([boat.lat, boat.lng], { icon: customIcon, boatId: boat.id }).addTo(map);
        markers[boat.id] = marker;
        updatePopupContent(boat);
    }
     function updatePopupContent(boat) {
        const marker = markers[boat.id]; if (!marker) return;
        const valveStatus = boat.valveOpen ? 'Open' : 'Closed';
        const lightColorClass = boat.valveOpen ? 'red-light' : 'green-light';
        const iconElement = marker.getElement(); if (iconElement) { const divIcon = iconElement.querySelector('.marker-icon'); if (divIcon) divIcon.className = `marker-icon ${lightColorClass}`; }
        const popupContent = `<b>ID:</b> ${boat.id}<br><b>Name:</b> ${boat.name}<br><b>Lat:</b> ${boat.lat.toFixed(4)}<br><b>Lng:</b> ${boat.lng.toFixed(4)}<br><b>Valve:</b> <span class="${lightColorClass}" style="padding: 0 5px; border-radius: 3px; color: white;">${valveStatus}</span><div class="popup-actions"><button onclick="handleOpenValve(${boat.id})" ${boat.valveOpen ? 'disabled' : ''}>Open Valve</button><button onclick="handleCloseValve(${boat.id})" ${!boat.valveOpen ? 'disabled' : ''}>Close Valve</button></div>`;
        if (marker.getPopup()) marker.setPopupContent(popupContent); else marker.bindPopup(popupContent);
    }

    // --- Fetch Initial Data (Unchanged logic, calls modified drawZone) ---
    async function fetchInitialData() {
        try {
            console.log("Fetching zone definition...");
            const zoneResponse = await fetch(`${backendBaseUrl}/api/zone-definition`);
            // Check if response is ok *before* parsing json
            if (!zoneResponse.ok && zoneResponse.status !== 500) { // Allow 500 for backend error message
                 throw new Error(`Zone fetch HTTP error! status: ${zoneResponse.status}`);
            }
            const zoneData = await zoneResponse.json();
             // Draw zone handles both success (geojson) and backend error (type: error)
            drawZone(zoneData);

            console.log("Fetching boat data...");
            const boatsResponse = await fetch(`${backendBaseUrl}/api/boats`);
            if (!boatsResponse.ok) throw new Error(`Boats fetch error! status: ${boatsResponse.status}`);
            const boats = await boatsResponse.json(); allBoatsData = boats;
            console.log(`Received ${allBoatsData.length} boats.`);
            Object.values(markers).forEach(m => map.removeLayer(m)); markers = {};
            allBoatsData.forEach(boat => createMarker(boat));
            console.log("Finished creating boat markers.");
        } catch (error) {
            displayError(mapElement, `Could not load initial map data. Is the backend running? ${error.message}`);
            searchButton.disabled = true; searchInput.disabled = true;
        }
    }

    // --- Valve Control Handlers (Unchanged) ---
    window.handleOpenValve = async function(boatId) {
        const boat = allBoatsData.find(b => b.id === boatId); if (!boat) return;
        const marker = markers[boatId]; if(marker && marker.getPopup()) marker.getPopup().disableClickPropagation();
        try {
            const response = await fetch(`${backendBaseUrl}/api/valve/open`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boatId: boat.id, lat: boat.lat, lng: boat.lng }) });
            if (!response.ok) { const errorData = await response.json(); throw new Error(`Failed: ${errorData.error || response.statusText}`); }
            const result = await response.json(); console.log("Valve open successful:", result);
            boat.valveOpen = true; updatePopupContent(boat); fetchAndDisplayHistory();
        } catch (error) { console.error("Error opening valve:", error); alert(`Error: ${error.message}`); }
        finally { if(marker && marker.getPopup()) marker.getPopup().enableClickPropagation(); }
    };
    window.handleCloseValve = function(boatId) { const boat = allBoatsData.find(b => b.id === boatId); if (boat) { boat.valveOpen = false; updatePopupContent(boat); } };

    // --- Search Functionality (Unchanged) ---
    function performSearch() {
        const searchTerm = searchInput.value.trim().toLowerCase(); searchResultSpan.textContent = ''; let found = false;
        if (!searchTerm) { searchResultSpan.textContent = 'Please enter an ID or Name.'; return; }
        if (allBoatsData.length === 0 && !searchButton.disabled) { searchResultSpan.textContent = 'Boat data not loaded yet.'; return; }
        map.closePopup();
        for (const boat of allBoatsData) { if (String(boat.id) === searchTerm || boat.name.toLowerCase().includes(searchTerm)) { const marker = markers[boat.id]; if (marker) { map.setView(marker.getLatLng(), 13); marker.openPopup(); searchResultSpan.textContent = `Found: ${boat.name} (ID: ${boat.id})`; found = true; break; } } }
        if (!found) searchResultSpan.textContent = 'Boat not found.';
    }

    // --- Event Listeners (Unchanged) ---
    searchButton.addEventListener('click', performSearch);
    searchInput.addEventListener('keypress', (event) => { if (event.key === 'Enter') performSearch(); });
    refreshHistoryButton.addEventListener('click', () => { historyLogElement.innerHTML = '<p>Refreshing history...</p>'; fetchAndDisplayHistory(); });

    // --- Initial Load ---
    fetchInitialData();
    fetchAndDisplayHistory();
});