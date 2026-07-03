let tg = null;
try {
    tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
} catch (e) {
    console.error('Telegram WebApp init error:', e);
}

let map, userMarker;
let markers = [];

let userSettings = {
    carburante: localStorage.getItem('fuel') || 'Benzina',
    raggio_km: localStorage.getItem('range') || '10'
};

const urlParams = new URLSearchParams(window.location.search);
const apiParam = urlParams.get('api');
const BACKEND_URL = apiParam || '';

if (tg) {
    try { tg.expand(); tg.ready(); } catch (e) { console.error('TG expand/ready error:', e); }
}

document.addEventListener('DOMContentLoaded', () => {
    updateUIDisplay();
    setupEventListeners();
    initApp();
});

function updateUIDisplay() {
    const display = document.getElementById('fuel-type-display');
    if (display) display.innerText = `${userSettings.carburante} \u2022 ${userSettings.raggio_km}km`;
    document.getElementById('fuel-select').value = userSettings.carburante;
    document.getElementById('range-slider').value = userSettings.raggio_km;
    document.getElementById('range-val').innerText = `${userSettings.raggio_km}km`;
}

function setupEventListeners() {
    const panel = document.getElementById('settings-panel');
    document.getElementById('open-settings').onclick = () => panel.classList.remove('hidden');
    document.getElementById('close-settings').onclick = () => panel.classList.add('hidden');
    document.getElementById('range-slider').oninput = (e) =>
        document.getElementById('range-val').innerText = `${e.target.value}km`;

    document.getElementById('save-settings').onclick = () => {
        userSettings.carburante = document.getElementById('fuel-select').value;
        userSettings.raggio_km = document.getElementById('range-slider').value;
        localStorage.setItem('fuel', userSettings.carburante);
        localStorage.setItem('range', userSettings.raggio_km);
        panel.classList.add('hidden');
        updateUIDisplay();
        location.reload();
    };
}

function initApp() {
    if (!tg) {
        showStatus('Apri questa app da Telegram');
        return;
    }
    if (!navigator.geolocation) {
        showStatus('GPS non supportato');
        return;
    }
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            initMap(pos.coords.latitude, pos.coords.longitude);
            fetchData(pos.coords.latitude, pos.coords.longitude);
        },
        () => {
            const lat = 45.4642, lon = 9.1900;
            initMap(lat, lon);
            fetchData(lat, lon);
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
}

function initMap(lat, lon) {
    if (map) return;
    try {
        map = L.map('map', { zoomControl: false, attributionControl: false }).setView([lat, lon], 14);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
            maxZoom: 19
        }).addTo(map);
        userMarker = L.circleMarker([lat, lon], {
            radius: 7, fillColor: '#38bdf8', color: '#fff', weight: 2, fillOpacity: 1
        }).addTo(map);
    } catch (e) {
        showStatus('Errore mappa: ' + e.message);
    }
}

async function fetchData(lat, lon) {
    const loader = document.getElementById('loader');
    if (!tg) { showStatus('Apri questa Dashboard dal bot Telegram'); return; }

    const initData = tg.initData;
    if (!initData) { showStatus('Apri questa Dashboard dal bot Telegram'); return; }

    try {
        const query = new URLSearchParams({
            lat, lon,
            carburante: userSettings.carburante,
            raggio_km: userSettings.raggio_km
        });
        const resp = await fetch(`${BACKEND_URL}/api/prices?${query}`, {
            headers: {
                'Authorization': initData,
                'ngrok-skip-browser-warning': 'true',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        loader.classList.add('hidden');
        renderDashboard(data.stations);
    } catch (err) {
        console.error('Fetch error:', err);
        loader.classList.add('hidden');
        showStatus(`Errore: ${err.message}`);
    }
}

function renderDashboard(stations) {
    const list = document.getElementById('ranking-list');
    list.innerHTML = '';
    markers.forEach(m => map.removeLayer(m));
    markers = [];

    if (!stations.length) {
        list.innerHTML = '<p class="empty-msg">Nessun distributore trovato.</p>';
        return;
    }

    const minPrice = Math.min(...stations.map(s => s.prezzo));

    stations.forEach((st, i) => {
        const cheap = st.prezzo === minPrice;
        const marker = L.marker([st._lat, st._lon], {
            icon: L.divIcon({
                className: 'price-tag-icon',
                html: `<div class="marker-pin ${cheap ? 'cheapest' : ''}">${st.prezzo.toFixed(2)}</div>`,
                iconSize: [40, 30], iconAnchor: [20, 30]
            })
        }).addTo(map);
        marker.bindPopup(`<b>${st.nome_impianto}</b><br>${st.prezzo.toFixed(3)} \u20ac/L`);
        markers.push(marker);

        const card = document.createElement('div');
        card.className = `station-card ${cheap ? 'border-glow' : ''}`;
        card.innerHTML = `
            <div class="card-info">
                <div class="card-price">
                    <span class="price-val ${cheap ? 'text-green' : ''}">${st.prezzo.toFixed(3)}</span>
                    <span class="unit">\u20ac/L</span>
                </div>
                <div class="card-meta">${st.bandiera.toUpperCase()}</div>
                <div class="card-subtext">${st.nome_impianto}</div>
            </div>
            <div class="card-actions">
                <span class="dist-badge">\ud83d\udccd ${st.distanza_km.toFixed(1)} km</span>
                <button class="nav-round-btn" onclick="openNav(${st._lat}, ${st._lon}, event)">\u2197\ufe0f</button>
            </div>`;
        card.onclick = () => { map.flyTo([st._lat, st._lon], 16, { duration: 1.5 }); marker.openPopup(); };
        list.appendChild(card);
    });

    if (markers.length > 0) {
        const group = new L.featureGroup([...markers, userMarker]);
        map.fitBounds(group.getBounds().pad(0.2));
    }
}

window.openNav = function (lat, lon, event) {
    if (event) event.stopPropagation();
    const url = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
    if (tg && tg.openLink) tg.openLink(url);
    else window.open(url, '_blank');
};

function showStatus(msg) {
    document.getElementById('loader').innerHTML =
        `<div style="padding:20px;text-align:center;color:#ef4444">
            <p style="font-size:1.1rem;margin-bottom:8px">${msg}</p>
            <p style="font-size:0.8rem;opacity:0.6">Riprova pi\u00f9 tardi</p>
        </div>`;
}
