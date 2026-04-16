const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

let map;
let markers = [];

// Apply Telegram Theme colors to body
document.body.style.backgroundColor = tg.backgroundColor;
document.body.style.color = tg.textColor;

async function init() {
    try {
        const initData = tg.initData;
        const response = await fetch(`/api/prices?initData=${encodeURIComponent(initData)}`);
        const data = await response.json();
        
        if (data.error) throw new Error(data.error);

        renderDashboard(data);
    } catch (err) {
        console.error("Dashboard error:", err);
        document.getElementById('loader').innerHTML = `<p style="color:#ff6b6b">Errore carica dati: ${err.message}</p>`;
    }
}

function renderDashboard(data) {
    // 1. Loader removal
    document.body.classList.add('body-loaded');
    
    // 2. Info pills
    document.getElementById('fuel-type').innerText = data.config.carburante;
    document.getElementById('service-type').innerText = data.config.self_service ? 'Self' : 'Servito';
    
    // 3. Map setup
    const userLat = data.config.lat;
    const userLon = data.config.lon;
    
    if (!map) {
        map = L.map('map').setView([userLat, userLon], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap'
        }).addTo(map);
        
        // Dark Mode Map adjustment (Optional: uses CSS filter on tiles)
        const isDark = tg.colorScheme === 'dark';
        if (isDark) {
            document.querySelector('.leaflet-tile-pane').style.filter = 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)';
        }
    }

    // Add User Marker
    L.circleMarker([userLat, userLon], { radius: 8, color: '#2481cc', fillOpacity: 0.8 }).addTo(map)
        .bindPopup("La tua posizione");

    // 4. Stations rendering
    const container = document.getElementById('stations-container');
    container.innerHTML = '';

    data.stations.forEach(st => {
        // Map Marker
        const marker = L.marker([st._lat, st._lon]).addTo(map)
            .bindPopup(`<b>${st.bandiera || 'Stazione'}</b><br>${st.prezzo.toFixed(3)}€/L`);
        markers.push(marker);

        // List Item
        const card = document.createElement('div');
        card.className = 'station-card';
        card.innerHTML = `
            <div class="st-info">
                <span class="st-name">${st.bandiera || 'Stazione'}</span>
                <span class="st-dist">${st.distanza_km.toFixed(1)} km • ${st.nome_impianto || ''}</span>
            </div>
            <div class="st-price-box">
                <span class="st-price">${st.prezzo.toFixed(3)}</span>
                <span class="st-unit">€/L</span>
            </div>
        `;
        
        card.onclick = () => {
            map.flyTo([st._lat, st._lon], 15);
            marker.openPopup();
            // Trigger feedback
            if (tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
        };

        container.appendChild(card);
    });
}

init();
