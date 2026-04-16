let tg = window.Telegram.WebApp;
let map, userMarker;
let markers = [];

// Carica impostazioni salvate o usa default
let userSettings = {
    carburante: localStorage.getItem('fuel') || 'Benzina',
    self_service: localStorage.getItem('self') || 'true',
    raggio_km: localStorage.getItem('range') || '10'
};

tg.expand();
tg.ready();

// Inizializza UI
document.addEventListener('DOMContentLoaded', () => {
    updateUIDisplay();
    initSettingsPanel();
    startApp();
});

function updateUIDisplay() {
    document.getElementById('fuel-type-display').innerText = `Carburante: ${userSettings.carburante}`;
    document.getElementById('fuel-select').value = userSettings.carburante;
    document.getElementById('service-select').value = userSettings.self_service;
    document.getElementById('range-slider').value = userSettings.raggio_km;
    document.getElementById('range-val').innerText = `${userSettings.raggio_km}km`;
}

function initSettingsPanel() {
    const panel = document.getElementById('settings-panel');
    const openBtn = document.getElementById('open-settings');
    const saveBtn = document.getElementById('save-settings');
    const slider = document.getElementById('range-slider');

    openBtn.onclick = () => panel.classList.toggle('hidden');
    slider.oninput = (e) => document.getElementById('range-val').innerText = `${e.target.value}km`;

    saveBtn.onclick = () => {
        userSettings.carburante = document.getElementById('fuel-select').value;
        userSettings.self_service = document.getElementById('service-select').value;
        userSettings.raggio_km = document.getElementById('range-slider').value;

        localStorage.setItem('fuel', userSettings.carburante);
        localStorage.setItem('self', userSettings.self_service);
        localStorage.setItem('range', userSettings.raggio_km);

        panel.classList.add('hidden');
        updateUIDisplay();
        location.reload(); // Rinfresca tutto con i nuovi dati
    };
}

async function startApp() {
    if (!navigator.geolocation) {
        showError("Geolocalizzazione non supportata");
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
            showError("Attiva il GPS per usare la mappa");
        },
        { enableHighAccuracy: true }
    );
}

function initMap(lat, lon) {
    if (map) return;
    map = L.map('map', {
        zoomControl: false,
        attributionControl: false
    }).setView([lat, lon], 13);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);

    userMarker = L.circleMarker([lat, lon], {
        radius: 8,
        fillColor: "#0088cc",
        color: "#fff",
        weight: 2,
        fillOpacity: 0.8
    }).addTo(map).bindPopup("Tu sei qui");
}

async function fetchData(lat, lon) {
    const loader = document.getElementById('loader');
    const initData = tg.initData;

    try {
        const query = new URLSearchParams({
            initData: initData,
            lat: lat,
            lon: lon,
            carburante: userSettings.carburante,
            self_service: userSettings.self_service,
            raggio_km: userSettings.raggio_km
        });

        const response = await fetch(`/api/prices?${query}`);
        const data = await response.json();

        if (data.error) throw new Error(data.error);

        loader.classList.add('hidden');
        renderStations(data.stations);
    } catch (err) {
        loader.innerHTML = `<p style="color:#ff6b6b">Errore: ${err.message}</p>`;
    }
}

function renderStations(stations) {
    markers.forEach(m => map.removeLayer(m));
    markers = [];

    stations.forEach((st, index) => {
        const marker = L.marker([st._lat, st._lon]).addTo(map);
        marker.bindPopup(`
            <div class="popup-content">
                <strong>${st.nome_impianto}</strong><br>
                <span class="price">${st.prezzo.toFixed(3)} €/L</span><br>
                <small>${st.bandiera} • ${st.distanza_km.toFixed(1)} km</small><br>
                <a href="https://www.google.com/maps/search/?api=1&query=${st._lat},${st._lon}" target="_blank" class="nav-link">Naviga</a>
            </div>
        `);
        markers.push(marker);
    });

    if (stations.length > 0) {
        const group = new L.featureGroup([...markers, userMarker]);
        map.fitBounds(group.getBounds().pad(0.1));
    }
}

function showError(msg) {
    document.getElementById('loader').innerHTML = `<p style="color:#ff6b6b">${msg}</p>`;
}
