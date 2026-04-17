let tg = window.Telegram.WebApp;
let map, userMarker;
let markers = [];

// Settings local state
let userSettings = {
    carburante: localStorage.getItem('fuel') || 'Benzina',
    raggio_km: localStorage.getItem('range') || '10'
};

// Configurazione Dinamica Backend
// 1. Cerca il parametro 'api' nell'URL (es. ?api=https://mio-server.com)
// 2. Se non c'è, e siamo su GitHub, usa un placeholder (va sostituito!)
// 3. Se siamo in locale, usa lo stesso server
const urlParams = new URLSearchParams(window.location.search);
const apiParam = urlParams.get('api');

const BACKEND_URL = apiParam 
    ? apiParam 
    : (window.location.origin.includes('github.io') ? 'https://bot-telegram-fuel-tracker-production.up.railway.app' : '');

tg.expand();
tg.ready();

// Inizializzazione UI
document.addEventListener('DOMContentLoaded', () => {
    updateUIDisplay();
    setupEventListeners();
    initApp();
});

function updateUIDisplay() {
    const display = document.getElementById('fuel-type-display');
    if(display) display.innerText = `${userSettings.carburante} • ${userSettings.raggio_km}km`;
    
    document.getElementById('fuel-select').value = userSettings.carburante;
    document.getElementById('range-slider').value = userSettings.raggio_km;
    document.getElementById('range-val').innerText = `${userSettings.raggio_km}km`;
}

function setupEventListeners() {
    const panel = document.getElementById('settings-panel');
    const openBtn = document.getElementById('open-settings');
    const closeBtn = document.getElementById('close-settings');
    const saveBtn = document.getElementById('save-settings');
    const slider = document.getElementById('range-slider');

    openBtn.onclick = () => panel.classList.remove('hidden');
    closeBtn.onclick = () => panel.classList.add('hidden');
    slider.oninput = (e) => document.getElementById('range-val').innerText = `${e.target.value}km`;

    saveBtn.onclick = () => {
        userSettings.carburante = document.getElementById('fuel-select').value;
        userSettings.raggio_km = document.getElementById('range-slider').value;

        localStorage.setItem('fuel', userSettings.carburante);
        localStorage.setItem('range', userSettings.raggio_km);

        panel.classList.add('hidden');
        updateUIDisplay();
        location.reload(); 
    };
}

async function initApp() {
    if (!navigator.geolocation) {
        showStatus("GPS non supportato");
        return;
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            initMap(lat, lon);
            fetchData(lat, lon);
        },
        (err) => {
            console.error(err);
            showStatus("Attiva il GPS per vedere i prezzi");
        },
        { enableHighAccuracy: true }
    );
}

function initMap(lat, lon) {
    if (map) return;
    map = L.map('map', {
        zoomControl: false,
        attributionControl: false
    }).setView([lat, lon], 14);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);

    userMarker = L.circleMarker([lat, lon], {
        radius: 7,
        fillColor: "#38bdf8",
        color: "#fff",
        weight: 2,
        fillOpacity: 1
    }).addTo(map);
}

async function fetchData(lat, lon) {
    const loader = document.getElementById('loader');
    const initData = tg.initData;

    try {
        if (!initData) {
            alert("⚠️ Per favore, apri questa Dashboard direttamente dal tasto nel Bot di Telegram!");
            return;
        }

        const query = new URLSearchParams({
            lat: lat,
            lon: lon,
            carburante: userSettings.carburante,
            raggio_km: userSettings.raggio_km
        });

        console.log("Fetching from:", `${BACKEND_URL}/api/prices`);
        const response = await fetch(`${BACKEND_URL}/api/prices?${query}`, {
            method: 'GET',
            headers: {
                'Authorization': initData,
                'ngrok-skip-browser-warning': 'true',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        const data = await response.json();

        if (data.error) throw new Error(data.error);

        loader.classList.add('hidden');
        renderDashboard(data.stations);
    } catch (err) {
        showStatus(`Errore: ${err.message}`);
    }
}

function renderDashboard(stations) {
    const listContainer = document.getElementById('ranking-list');
    listContainer.innerHTML = '';
    
    markers.forEach(m => map.removeLayer(m));
    markers = [];

    if (stations.length === 0) {
        listContainer.innerHTML = '<p class="empty-msg">Nessun distributore trovato.</p>';
        return;
    }

    // Identifica il prezzo minimo per evidenziarlo
    const minPrice = Math.min(...stations.map(s => s.prezzo));

    stations.forEach((st, index) => {
        const isCheapest = st.prezzo === minPrice;
        const markerColor = isCheapest ? "#22c55e" : "#38bdf8";

        // 1. Marker a forma di "Price Tag"
        const marker = L.marker([st._lat, st._lon], {
            icon: L.divIcon({
                className: 'price-tag-icon',
                html: `<div class="marker-pin ${isCheapest ? 'cheapest' : ''}">${st.prezzo.toFixed(2)}</div>`,
                iconSize: [40, 30],
                iconAnchor: [20, 30]
            })
        }).addTo(map);
        
        marker.bindPopup(`<b>${st.nome_impianto}</b><br>${st.prezzo.toFixed(3)} €/L`);
        markers.push(marker);

        // 2. Card
        const card = document.createElement('div');
        card.className = `station-card ${isCheapest ? 'border-glow' : ''}`;
        card.innerHTML = `
            <div class="card-info">
                <div class="card-price">
                    <span class="price-val ${isCheapest ? 'text-green' : ''}">${st.prezzo.toFixed(3)}</span>
                    <span class="unit">€/L</span>
                </div>
                <div class="card-meta">${st.bandiera.toUpperCase()}</div>
                <div class="card-subtext">${st.nome_impianto}</div>
            </div>
            <div class="card-actions">
                <span class="dist-badge">📍 ${st.distanza_km.toFixed(1)} km</span>
                <button class="nav-round-btn" onclick="openNav(${st._lat}, ${st._lon}, event)">↗️</button>
            </div>
        `;
        
        card.onclick = () => {
            map.flyTo([st._lat, st._lon], 16, { duration: 1.5 });
            marker.openPopup();
        };

        listContainer.appendChild(card);
    });

    if (markers.length > 0) {
        const group = new L.featureGroup([...markers, userMarker]);
        map.fitBounds(group.getBounds().pad(0.2));
    }
}

// Funzione globale per aprire la navigazione
window.openNav = function(lat, lon, event) {
    if(event) event.stopPropagation();
    // Usa il formato 'dir' per avviare direttamente la navigazione verso le coordinate esatte
    const url = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
    if (tg.openLink) {
        tg.openLink(url);
    } else {
        window.open(url, '_blank');
    }
};

function showStatus(msg) {
    const loader = document.getElementById('loader');
    loader.innerHTML = `<p style="padding:20px; text-align:center;">${msg}</p>`;
}
