/**
 * script.js
 * Handles the Leaflet map interactions, data fetching, and history display
 * for the Coastline Buffer & Boat Map application.
 */

// --- Global Variables ---
let map;
let landLayer = L.layerGroup(); // Layer group for land polygons
let bufferLayer = L.layerGroup(); // Layer group for buffer zones
let boatLayer = L.layerGroup(); // Layer group for boat markers
const boatMarkers = {}; // Store boat markers by ID for easy update: { boatId: marker }

// --- Map Initialization ---
function initMap() {
    console.log("Initializing Leaflet map...");
    map = L.map('map').setView([51.505, -0.09], 5); // Default view (will be updated)

    // Add OpenStreetMap base layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    // Add layer groups to the map
    landLayer.addTo(map);
    bufferLayer.addTo(map);
    boatLayer.addTo(map);

    // Initial history load
    fetchAndDisplayHistory();
    console.log("Map initialized.");
}

// --- DOM Element References ---
const loadingIndicator = document.getElementById('loading');
const errorMessageDiv = document.getElementById('errorMessage');
const historyLogDiv = document.getElementById('historyLog');

// --- Helper Functions ---

function showLoading(message = "Loading...") {
    if (loadingIndicator) {
        loadingIndicator.textContent = message;
        loadingIndicator.style.display = 'flex'; // Show the overlay
    }
}

function hideLoading() {
    if (loadingIndicator) {
        loadingIndicator.style.display = 'none'; // Hide the overlay
    }
}

function displayError(message) {
     console.error("Displaying Error:", message);
    if (errorMessageDiv) {
        errorMessageDiv.textContent = message;
        errorMessageDiv.style.display = 'block'; // Show error area
         // Optionally hide after some time
        // setTimeout(() => {
        //     errorMessageDiv.style.display = 'none';
        //     errorMessageDiv.textContent = '';
        // }, 5000);
    }
}

function clearError() {
     if (errorMessageDiv) {
        errorMessageDiv.style.display = 'none';
        errorMessageDiv.textContent = '';
     }
}

// --- Data Loading ---

async function loadMapData(countryCode) {
    console.log(`Loading map data for: ${countryCode}`);
    showLoading(`Loading ${countryCode.toUpperCase()} data...`);
    clearError(); // Clear previous errors

    try {
        const response = await fetch(`/api/mapdata/${countryCode}`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ description: response.statusText })); // Try to get JSON error, fallback to status text
            throw new Error(`Failed to load map data: ${errorData.description || response.status}`);
        }
        const data = await response.json();
        console.log("Received map data:", data);

        // --- Handle potential backend errors ---
        if (data.errors && data.errors.length > 0) {
            displayError(`Server Errors: ${data.errors.join('; ')}`);
            // Decide if you want to continue rendering partial data or stop
        }

        // --- Clear Existing Layers ---
        landLayer.clearLayers();
        bufferLayer.clearLayers();
        boatLayer.clearLayers();
        Object.keys(boatMarkers).forEach(key => delete boatMarkers[key]); // Clear marker cache


        // --- Add Land Layer ---
        if (data.land) {
            try {
                const landGeoJson = JSON.parse(data.land); // Parse GeoJSON string
                 L.geoJSON(landGeoJson, {
                    style: {
                        color: "#2a4018", // Dark green
                        weight: 1,
                        fillColor: "#88aa77", // Lighter green fill
                        fillOpacity: 0.5
                    }
                }).addTo(landLayer);
                console.log("Land layer added.");
            } catch (e) {
                console.error("Error parsing or adding land GeoJSON:", e);
                displayError("Error displaying land data.");
            }
        } else {
            console.warn("No land data received.");
        }


        // --- Add Buffer Layer ---
        if (data.buffer) {
             try {
                 const bufferGeoJson = JSON.parse(data.buffer); // Parse GeoJSON string
                 L.geoJSON(bufferGeoJson, {
                    style: {
                        color: "#ff0000", // Red outline
                        weight: 2,
                        fillColor: "#ffcccc", // Light red fill
                        fillOpacity: 0.3,
                        dashArray: '5, 5' // Dashed line
                    }
                }).addTo(bufferLayer);
                 console.log("Buffer layer added.");
            } catch (e) {
                 console.error("Error parsing or adding buffer GeoJSON:", e);
                 displayError("Error displaying buffer zone data.");
             }
        } else {
             console.warn("No buffer data received.");
        }


        // --- Add Boat Markers ---
        if (data.boats && data.boats.length > 0) {
            data.boats.forEach(boat => {
                const iconColor = boat.valveOpen ? 'red' : 'blue'; // Red if open, blue if closed
                const marker = L.circleMarker([boat.lat, boat.lng], {
                    radius: 6,
                    fillColor: iconColor,
                    color: "#000",
                    weight: 1,
                    opacity: 1,
                    fillOpacity: 0.8
                }).addTo(boatLayer);

                // Store marker reference
                boatMarkers[boat.id] = marker;

                // Create popup content
                const popupContent = `
                    <b>${boat.name}</b> (ID: ${boat.id})<br>
                    Lat: ${boat.lat}, Lng: ${boat.lng}<br>
                    Valve Status: <span id="valve-status-${boat.id}">${boat.valveOpen ? 'Open' : 'Closed'}</span><br>
                    <button onclick="toggleValve(${boat.id})">
                        ${boat.valveOpen ? 'Close Valve' : 'Open Valve'}
                    </button>
                `;
                marker.bindPopup(popupContent);
            });
            console.log(`Added ${data.boats.length} boat markers.`);
        } else {
            console.log("No boats to display for this country.");
        }


        // --- Update Map View ---
        if (data.center && data.zoom) {
            map.setView(data.center, data.zoom);
            console.log(`Map view set to center: ${data.center}, zoom: ${data.zoom}`);
        }


    } catch (error) {
        console.error("Error fetching or processing map data:", error);
        displayError(`Client Error: ${error.message}`);
    } finally {
        hideLoading();
    }
}


// --- Valve Toggling ---

async function toggleValve(boatId) {
     console.log(`Toggling valve for boat ID: ${boatId}`);
     const marker = boatMarkers[boatId];
     if (!marker) {
        console.error(`Marker not found for boat ID ${boatId}`);
        return;
     }

     showLoading(`Updating valve for boat ${boatId}...`);
     clearError();

    try {
        const response = await fetch(`/api/valve/toggle/${boatId}`, {
            method: 'POST',
             headers: {
                 'Content-Type': 'application/json'
                 // Add any other required headers like CSRF tokens if needed later
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: response.statusText }));
            throw new Error(`Failed to toggle valve: ${errorData.message || response.status}`);
        }

        const result = await response.json();
        console.log("Valve toggle result:", result);

        // --- Update Marker Appearance and Popup ---
        const newStatus = result.valveOpen;
        const newColor = newStatus ? 'red' : 'blue';
        marker.setStyle({ fillColor: newColor });

        // Update popup content dynamically (more robust than replacing entire HTML string)
        const popup = marker.getPopup();
        if (popup) {
             // Find the elements within the popup's content node
             const tempDiv = document.createElement('div');
             tempDiv.innerHTML = popup.getContent(); // Parse existing content

             const statusSpan = tempDiv.querySelector(`#valve-status-${boatId}`);
             const toggleButton = tempDiv.querySelector('button');

             if (statusSpan) {
                 statusSpan.textContent = newStatus ? 'Open' : 'Closed';
             }
             if (toggleButton) {
                 toggleButton.textContent = newStatus ? 'Close Valve' : 'Open Valve';
                 // Re-attach event listener if needed, though onclick attribute should still work
             }
             popup.setContent(tempDiv.innerHTML); // Set updated HTML
             // Alternatively, regenerate the whole popup string if simpler:
             // const newPopupContent = `...regenerated content based on result...`;
             // popup.setContent(newPopupContent);
        }


        // --- Refresh History Log ---
         // Refreshing the history log if a valve was opened might be desired
         if (newStatus) { // If valve is now open, refresh history
             console.log("Valve opened, refreshing history...");
             fetchAndDisplayHistory();
         }


    } catch (error) {
        console.error("Error toggling valve:", error);
        displayError(`Valve Toggle Error: ${error.message}`);
    } finally {
         hideLoading();
    }
}


// --- History Log ---

async function fetchAndDisplayHistory() {
    console.log("Fetching valve opening history...");
    if (!historyLogDiv) {
        console.error("History log element not found.");
        return;
    }
    historyLogDiv.innerHTML = '<p>Loading history...</p>'; // Show loading state

    try {
        const response = await fetch('/api/history');
        if (!response.ok) {
            throw new Error(`Failed to fetch history: ${response.statusText}`);
        }
        const history = await response.json();
        console.log("Received history:", history);

        if (history.length === 0) {
            historyLogDiv.innerHTML = '<p>No valve opening events recorded yet.</p>';
            return;
        }

        // --- Format and Display History ---
        let historyHtml = '<ul>';
         history.forEach(entry => {
             // Format timestamp for readability
             const timestamp = new Date(entry.timestamp).toLocaleString(); // Use local time format
             const statusClass = entry.inZone ? 'illegal' : 'legal'; // CSS class for styling
             historyHtml += `
                <li class="${statusClass}">
                     <strong>${entry.boatName}</strong> (ID: ${entry.boatId}) - ${entry.country.toUpperCase()}
                    <br>
                     Status: <strong>${entry.status}</strong>
                     <br>
                     Time: ${timestamp}
                     <br>
                     Location: ${entry.lat.toFixed(4)}, ${entry.lng.toFixed(4)}
                     ${entry.inZone ? '<br><span style="color: red; font-weight: bold;">ALERT: DISPOSAL IN BUFFER ZONE</span>' : ''}
                </li>
             `;
        });
        historyHtml += '</ul>';

        historyLogDiv.innerHTML = historyHtml;

    } catch (error) {
        console.error("Error fetching or displaying history:", error);
        historyLogDiv.innerHTML = `<p style="color: red;">Error loading history: ${error.message}</p>`;
    }
}


// --- Initial Setup ---
// Wait for the DOM to be fully loaded before initializing the map
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    // Optionally load default country data on page load
    // loadMapData('uk'); // Example: Load UK data by default
});