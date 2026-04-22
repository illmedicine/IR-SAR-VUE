/* app.js — main rendering / propagation loop for the NIS SAR Viewer.
 *
 * Uses Three.js for the globe + satellite point cloud, and satellite.js for SGP4
 * propagation of each catalog entry. All coordinates are converted from TEME (satellite.js
 * output) to ECI-equivalent scene units where 1 scene unit = 1 Earth radius.
 *
 * Satellites are rendered in a single THREE.Points buffer for performance (tens of
 * thousands of points at once). Picking is done in screen space (nearest-neighbor to the
 * click position) rather than via raycasting, since points have no true geometry.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

(function () {
    'use strict';

    // Earth radius in km; scene scale is 1 unit = 1 Earth radius so the globe mesh is a unit sphere.
    const R_EARTH_KM = 6371.0;

    // ---------- THREE.js scene setup ----------
    const canvas   = document.getElementById('scene');
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    renderer.setSize(window.innerWidth, window.innerHeight, false);
    renderer.setClearColor(0x05070d, 1);

    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.01, 1000);
    camera.position.set(0, 0.6, 3.6);

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 1.08;
    controls.maxDistance = 20;

    // Lighting: weak ambient + directional "sun" to give the globe some shading.
    scene.add(new THREE.AmbientLight(0x334466, 0.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.0);
    sun.position.set(5, 3, 5);
    scene.add(sun);

    // Starfield background — random points on a large sphere.
    (function addStars() {
        const N = 3500;
        const geo = new THREE.BufferGeometry();
        const pos = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) {
            const u = Math.random(), v = Math.random();
            const th = 2 * Math.PI * u, ph = Math.acos(2 * v - 1);
            const r = 120;
            pos[i * 3]     = r * Math.sin(ph) * Math.cos(th);
            pos[i * 3 + 1] = r * Math.cos(ph);
            pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
        }
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const mat = new THREE.PointsMaterial({ size: 0.18, color: 0xffffff, sizeAttenuation: true, transparent: true, opacity: 0.7 });
        scene.add(new THREE.Points(geo, mat));
    })();

    // Earth: textured sphere. Uses a free BlueMarble-style texture hosted on a public CDN.
    // On texture-load failure we fall back to a shaded blue sphere so the app still works offline.
    const earthGroup = new THREE.Group();
    scene.add(earthGroup);
    {
        const geo = new THREE.SphereGeometry(1, 96, 64);
        const mat = new THREE.MeshPhongMaterial({ color: 0x1b3a6b, specular: 0x223344, shininess: 18, emissive: 0x050a14 });
        const earthMesh = new THREE.Mesh(geo, mat);
        earthGroup.add(earthMesh);

        const loader = new THREE.TextureLoader();
        loader.setCrossOrigin('anonymous');
        // Public-domain NASA Blue Marble mirror on jsdelivr (via turban/webgl-earth textures repo).
        // If this 404s or is blocked, we keep the plain blue sphere.
        loader.load(
            'https://cdn.jsdelivr.net/gh/turban/webgl-earth@master/images/2_no_clouds_4k.jpg',
            (tex) => {
                tex.colorSpace = THREE.SRGBColorSpace;
                mat.map = tex;
                mat.color.setHex(0xffffff);
                mat.needsUpdate = true;
            },
            undefined,
            () => { /* silent fallback — plain blue sphere */ }
        );
        // Optional specular map (oceans shinier than land).
        loader.load(
            'https://cdn.jsdelivr.net/gh/turban/webgl-earth@master/images/water_4k.png',
            (tex) => { mat.specularMap = tex; mat.specular = new THREE.Color(0x2233aa); mat.needsUpdate = true; },
            undefined, () => {}
        );

        // Equator + prime-meridian rings for orientation.
        const ringMat = new THREE.LineBasicMaterial({ color: 0x4477bb, transparent: true, opacity: 0.25 });
        const eqPts = []; for (let i = 0; i <= 128; i++) { const a = (i / 128) * Math.PI * 2; eqPts.push(new THREE.Vector3(Math.cos(a), 0, Math.sin(a)).multiplyScalar(1.003)); }
        earthGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(eqPts), ringMat));
        const pmPts = []; for (let i = 0; i <= 128; i++) { const a = (i / 128) * Math.PI * 2; pmPts.push(new THREE.Vector3(Math.cos(a), Math.sin(a), 0).multiplyScalar(1.003)); }
        earthGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pmPts), ringMat));
    }

    // ---------- App state ----------
    const state = {
        sats: [],               // parsed TLE records { name, noradId, satrec, color, catalogId }
        points: null,           // THREE.Points object
        positions: null,        // Float32Array of XYZ
        colors: null,           // Float32Array of RGB
        pointSize: 3,
        showOrbits: false,
        showLabels: false,
        showFootprints: false,
        enabledCatalogs: new Set(SatCatalog.CATALOGS.filter(c => c.on).map(c => c.id)),
        selected: null,         // index of selected sat
        selectedOrbitLine: null,
        selectedFootprint: null,
        selectedMarker: null,
        live: true,
        timeRate: 1,
        simTimeMs: Date.now()
    };

    // ---------- UI wiring ----------
    const $ = (id) => document.getElementById(id);
    const elStatus = $('status');
    const elUtc    = $('utc');
    const elInfo   = $('info');

    function setStatus(msg) { elStatus.textContent = msg; }

    // Build catalog checklist.
    (function buildCatalogUI() {
        const host = $('catalogs');
        SatCatalog.CATALOGS.forEach(cat => {
            const id = 'cat-' + cat.id;
            const row = document.createElement('label');
            row.className = 'cat';
            row.innerHTML =
                '<input type="checkbox" id="' + id + '"' + (state.enabledCatalogs.has(cat.id) ? ' checked' : '') + '>' +
                '<span class="sw" style="background:#' + cat.color.toString(16).padStart(6, '0') + '"></span>' +
                '<span>' + cat.name + '</span>' +
                '<span class="ct" id="ct-' + cat.id + '"></span>';
            host.appendChild(row);
            row.querySelector('input').addEventListener('change', (ev) => {
                if (ev.target.checked) state.enabledCatalogs.add(cat.id);
                else state.enabledCatalogs.delete(cat.id);
                reloadSatellites();
            });
        });
    })();

    $('show-orbits').addEventListener('change', (e) => { state.showOrbits = e.target.checked; refreshSelectedVisuals(); });
    $('show-labels').addEventListener('change', (e) => { state.showLabels = e.target.checked; /* labels TBD */ });
    $('show-footprints').addEventListener('change', (e) => { state.showFootprints = e.target.checked; refreshSelectedVisuals(); });
    $('point-size').addEventListener('input', (e) => {
        state.pointSize = parseFloat(e.target.value);
        if (state.points) state.points.material.size = state.pointSize * 0.004;
    });
    $('live').addEventListener('change', (e) => { state.live = e.target.checked; });
    $('timerate').addEventListener('change', (e) => { state.timeRate = parseFloat(e.target.value); });
    $('info-close').addEventListener('click', () => { clearSelection(); });

    // Quick Track buttons: select by NORAD ID (or load that satellite on-demand if missing).
    document.querySelectorAll('#quick-track button').forEach(btn => {
        btn.addEventListener('click', async () => {
            const norad = btn.getAttribute('data-norad');
            let idx = state.sats.findIndex(s => s.noradId === norad);
            if (idx < 0) {
                setStatus('Fetching TLE for NORAD ' + norad + '…');
                const added = await SatCatalog.fetchByNoradId(norad);
                if (added) {
                    state.sats.push(added);
                    buildPointCloud();
                    idx = state.sats.length - 1;
                    setStatus('Tracking ' + state.sats.length + ' satellites.');
                } else {
                    setStatus('Could not fetch TLE for NORAD ' + norad + '.');
                    return;
                }
            }
            // Propagate once so the new sat has a position before selection visuals compute.
            propagateAll(currentDate());
            selectSatellite(idx);
            // Ease the camera toward the satellite.
            const p = state.positions;
            const target = new THREE.Vector3(p[idx * 3], p[idx * 3 + 1], p[idx * 3 + 2]);
            controls.target.copy(target.clone().normalize().multiplyScalar(0));
            const camDist = Math.max(1.8, target.length() * 1.6);
            camera.position.copy(target.clone().normalize().multiplyScalar(camDist));
        });
    });

    // Debounced search.
    let searchTimer = null;
    $('search').addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        const q = e.target.value.trim().toLowerCase();
        searchTimer = setTimeout(() => runSearch(q), 150);
    });

    function runSearch(q) {
        const host = $('search-results');
        host.innerHTML = '';
        if (!q || state.sats.length === 0) return;
        const hits = [];
        for (let i = 0; i < state.sats.length && hits.length < 30; i++) {
            const s = state.sats[i];
            if (s.name.toLowerCase().includes(q) || s.noradId.includes(q)) hits.push({ i, s });
        }
        hits.forEach(({ i, s }) => {
            const row = document.createElement('div');
            row.className = 'sr-item';
            row.innerHTML = '<span>' + s.name + '</span><span class="nid">' + s.noradId + '</span>';
            row.addEventListener('click', () => selectSatellite(i));
            host.appendChild(row);
        });
    }

    // ---------- Satellite loading ----------
    // Debounced + cancellable: rapid checkbox toggling collapses into a single reload.
    let reloadTimer = null;
    let reloadAbort = null;
    let reloadInFlight = false;
    function reloadSatellites() {
        clearTimeout(reloadTimer);
        // Cancel any in-flight reload so its late results don't overwrite newer state.
        if (reloadAbort) { try { reloadAbort.abort(); } catch (e) {} }
        reloadAbort = new AbortController();
        const signal = reloadAbort.signal;
        return new Promise((resolve) => {
            reloadTimer = setTimeout(async () => {
                if (reloadInFlight) { resolve(); return; }
                reloadInFlight = true;
                setStatus('Loading TLE catalogs…');
                clearSelection();
                try {
                    const { sats, errors } = await SatCatalog.fetchEnabled(
                        state.enabledCatalogs,
                        (name, count) => {
                            if (signal.aborted) return;
                            if (count === null)     setStatus('Fetching ' + name + '…');
                            else if (count === -1)  setStatus(name + ' unavailable');
                        },
                        signal
                    );
                    if (signal.aborted) return;
                    state.sats = sats;
                    const counts = {};
                    sats.forEach(s => { counts[s.catalogId] = (counts[s.catalogId] || 0) + 1; });
                    SatCatalog.CATALOGS.forEach(c => {
                        const el = document.getElementById('ct-' + c.id);
                        if (el) el.textContent = counts[c.id] ? counts[c.id] : '';
                    });
                    buildPointCloud();
                    const errMsg = errors.length ? ('  (offline: ' + errors.length + ')') : '';
                    setStatus('Tracking ' + sats.length + ' satellites across ' + state.enabledCatalogs.size + ' catalogs.' + errMsg);
                } finally {
                    reloadInFlight = false;
                    resolve();
                }
            }, 350);
        });
    }

    function buildPointCloud() {
        if (state.points) {
            scene.remove(state.points);
            state.points.geometry.dispose();
            state.points.material.dispose();
            state.points = null;
        }
        const N = state.sats.length;
        if (N === 0) return;
        const positions = new Float32Array(N * 3);
        const colors    = new Float32Array(N * 3);
        const col = new THREE.Color();
        for (let i = 0; i < N; i++) {
            col.setHex(state.sats[i].color);
            colors[i * 3]     = col.r;
            colors[i * 3 + 1] = col.g;
            colors[i * 3 + 2] = col.b;
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geo.setAttribute('color',    new THREE.BufferAttribute(colors, 3));
        const mat = new THREE.PointsMaterial({
            size: state.pointSize * 0.004,
            vertexColors: true,
            sizeAttenuation: true,
            transparent: true,
            opacity: 0.95,
            depthWrite: false
        });
        state.points = new THREE.Points(geo, mat);
        scene.add(state.points);
        state.positions = positions;
        state.colors    = colors;
    }

    // ---------- Propagation ----------
    // GMST rotation: satellite.js outputs TEME; rotating by -GMST gives ECEF. For a fixed
    // Earth mesh (no rotation applied), we can just plot TEME directly — stars don't
    // matter here. We instead rotate the Earth mesh by +GMST so continents (when textured)
    // align with satellite ground tracks.
    function propagateAll(date) {
        if (!state.positions) return;
        const gmst = satellite.gstime(date);
        // Rotate Earth so that ECEF = rotateZ(-gmst) * TEME; we apply +gmst to the mesh.
        earthGroup.rotation.y = gmst;

        const pos = state.positions;
        const R = R_EARTH_KM;
        for (let i = 0; i < state.sats.length; i++) {
            const pv = satellite.propagate(state.sats[i].satrec, date);
            if (!pv || !pv.position) {
                // Failed propagation — park at origin (effectively hidden inside Earth).
                pos[i * 3] = 0; pos[i * 3 + 1] = 0; pos[i * 3 + 2] = 0;
                continue;
            }
            // TEME km → scene units. Three.js uses Y-up; map (x,y,z)_TEME → (x, z, -y) for
            // a conventional view where the equator is in the XZ-plane.
            const x =  pv.position.x / R;
            const y =  pv.position.z / R;
            const z = -pv.position.y / R;
            pos[i * 3]     = x;
            pos[i * 3 + 1] = y;
            pos[i * 3 + 2] = z;
        }
        state.points.geometry.attributes.position.needsUpdate = true;
    }

    // ---------- Selection / info panel ----------
    function selectSatellite(index) {
        if (index < 0 || index >= state.sats.length) return;
        state.selected = index;
        const s = state.sats[index];
        renderInfoPanel(s);
        refreshSelectedVisuals();
    }

    function clearSelection() {
        state.selected = null;
        elInfo.classList.add('hidden');
        removeSelectedVisuals();
    }

    function removeSelectedVisuals() {
        [state.selectedOrbitLine, state.selectedFootprint, state.selectedMarker].forEach(obj => {
            if (obj) { scene.remove(obj); if (obj.geometry) obj.geometry.dispose(); if (obj.material) obj.material.dispose(); }
        });
        state.selectedOrbitLine = state.selectedFootprint = state.selectedMarker = null;
    }

    function refreshSelectedVisuals() {
        removeSelectedVisuals();
        if (state.selected == null) return;
        const s = state.sats[state.selected];

        // Highlight marker: a small ring at the satellite position (updated each frame).
        const ringGeo = new THREE.RingGeometry(0.015, 0.022, 24);
        const ringMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0.85, depthTest: false });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.renderOrder = 10;
        scene.add(ring);
        state.selectedMarker = ring;

        if (state.showOrbits) state.selectedOrbitLine = buildOrbitLine(s);
        if (state.showFootprints) state.selectedFootprint = buildFootprint(s);
    }

    // Propagate one full orbital period to draw a ribbon. Samples: 180 points.
    function buildOrbitLine(sat) {
        const period = (2 * Math.PI) / sat.satrec.no; // minutes per revolution
        const N = 180;
        const pts = [];
        const R = R_EARTH_KM;
        const now = currentDate();
        for (let i = 0; i <= N; i++) {
            const t = new Date(now.getTime() + (i / N) * period * 60000);
            const pv = satellite.propagate(sat.satrec, t);
            if (!pv || !pv.position) continue;
            pts.push(new THREE.Vector3(pv.position.x / R, pv.position.z / R, -pv.position.y / R));
        }
        const geo = new THREE.BufferGeometry().setFromPoints(pts);
        const mat = new THREE.LineBasicMaterial({ color: 0x44ffaa, transparent: true, opacity: 0.85 });
        const line = new THREE.Line(geo, mat);
        scene.add(line);
        return line;
    }

    // Visibility cone footprint — a small circle drawn on Earth below the sat's sub-point.
    function buildFootprint(sat) {
        const now = currentDate();
        const pv = satellite.propagate(sat.satrec, now);
        if (!pv || !pv.position) return null;
        const gmst = satellite.gstime(now);
        const geo = satellite.eciToGeodetic(pv.position, gmst);
        const altKm = geo.height;
        const RkM = R_EARTH_KM;
        // Horizon half-angle (radians) as seen from sat: cos(theta) = R/(R+h).
        const theta = Math.acos(RkM / (RkM + altKm));
        // Circle center = sub-satellite point on unit sphere (ECEF).
        const lat = geo.latitude, lon = geo.longitude;
        const cx = Math.cos(lat) * Math.cos(lon);
        const cy = Math.cos(lat) * Math.sin(lon);
        const cz = Math.sin(lat);
        // Build a ring of points around the sub-point at angular radius theta on the sphere.
        const axis = new THREE.Vector3(cx, cy, cz).normalize();
        const up   = Math.abs(axis.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
        const t1 = new THREE.Vector3().crossVectors(axis, up).normalize();
        const t2 = new THREE.Vector3().crossVectors(axis, t1).normalize();
        const pts = [];
        const r = Math.sin(theta), d = Math.cos(theta);
        for (let i = 0; i <= 96; i++) {
            const a = (i / 96) * Math.PI * 2;
            const p = new THREE.Vector3()
                .addScaledVector(axis, d)
                .addScaledVector(t1, r * Math.cos(a))
                .addScaledVector(t2, r * Math.sin(a))
                .multiplyScalar(1.005);
            pts.push(p);
        }
        // Apply same mapping (ECEF x,y,z → scene x, z, -y), then un-rotate by GMST since
        // earthGroup already rotates. Easier: parent the line to earthGroup directly.
        const sceneP = pts.map(p => new THREE.Vector3(p.x, p.z, -p.y));
        const g = new THREE.BufferGeometry().setFromPoints(sceneP);
        const m = new THREE.LineBasicMaterial({ color: 0x44ffaa, transparent: true, opacity: 0.6 });
        const line = new THREE.Line(g, m);
        earthGroup.add(line);
        // We added to earthGroup so cleanup must also remove from earthGroup.
        line.userData._onEarth = true;
        return line;
    }

    function renderInfoPanel(sat) {
        const meta = SatCatalog.metaFor(sat) || {};
        const cat = SatCatalog.CATALOGS.find(c => c.id === sat.catalogId);
        const purpose = meta.purpose || (cat && cat.purpose) || 'No purpose metadata available.';
        const kind = meta.kind || (cat && cat.kind) || 'other';
        const now = currentDate();
        const pv = satellite.propagate(sat.satrec, now);
        let altKm = '—', lat = '—', lon = '—', speed = '—';
        if (pv && pv.position) {
            const gmst = satellite.gstime(now);
            const g = satellite.eciToGeodetic(pv.position, gmst);
            altKm = g.height.toFixed(1) + ' km';
            lat   = satellite.degreesLat(g.latitude).toFixed(3) + '°';
            lon   = satellite.degreesLong(g.longitude).toFixed(3) + '°';
            if (pv.velocity) {
                const v = pv.velocity;
                speed = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z).toFixed(3) + ' km/s';
            }
        }
        const period = ((2 * Math.PI) / sat.satrec.no).toFixed(1) + ' min';
        const inc    = (sat.satrec.inclo * 180 / Math.PI).toFixed(2) + '°';
        const ecc    = sat.satrec.ecco.toFixed(5);

        const links = SatCatalog.externalLinks(sat).map(l =>
            '<a href="' + l.href + '" target="_blank" rel="noopener">' + l.label + '</a>'
        ).join('');

        // "Live Imagery" CTA for Landsat 8 / 9 — opens the USGS EarthNow viewer panel.
        // NORAD 39084 = Landsat 8, 49260 = Landsat 9. Name-match as a fallback.
        const nmU = (sat.name || '').toUpperCase();
        const isLandsat = sat.noradId === '49260' || sat.noradId === '39084' || nmU.includes('LANDSAT');
        const imageryBtn = isLandsat
            ? '<button class="imagery-cta" id="open-imagery" data-norad="' + sat.noradId + '">Live Imagery Feed</button>'
            : '';

        $('info-name').textContent = sat.name;
        $('info-body').innerHTML =
            '<div class="badges">' +
                '<span class="badge ' + kind + '">' + (cat ? cat.name : 'Catalog') + '</span>' +
                (meta.country ? '<span class="badge">' + meta.country + '</span>' : '') +
            '</div>' +
            '<dl class="kv">' +
                '<dt>NORAD ID</dt><dd>' + sat.noradId + '</dd>' +
                '<dt>Altitude</dt><dd>' + altKm + '</dd>' +
                '<dt>Lat / Lon</dt><dd>' + lat + ' / ' + lon + '</dd>' +
                '<dt>Speed</dt><dd>' + speed + '</dd>' +
                '<dt>Period</dt><dd>' + period + '</dd>' +
                '<dt>Inclination</dt><dd>' + inc + '</dd>' +
                '<dt>Eccentricity</dt><dd>' + ecc + '</dd>' +
                (meta.operator ? '<dt>Operator</dt><dd>' + meta.operator + '</dd>' : '') +
                (meta.launched ? '<dt>Launched</dt><dd>' + meta.launched + '</dd>' : '') +
                (meta.orbit    ? '<dt>Orbit</dt><dd>' + meta.orbit + '</dd>'       : '') +
                (meta.mass     ? '<dt>Mass</dt><dd>' + meta.mass + '</dd>'         : '') +
                (meta.power    ? '<dt>Power</dt><dd>' + meta.power + '</dd>'       : '') +
            '</dl>' +
            '<div class="info-section"><h4>Purpose</h4><p>' + purpose + '</p></div>' +
            imageryBtn +
            '<div class="info-section"><h4>TLE</h4>' +
                '<p style="font-family:Consolas,monospace;font-size:10px;color:#9bf">' + sat.tle1 + '<br>' + sat.tle2 + '</p>' +
            '</div>' +
            '<div class="info-section"><h4>External References</h4>' +
                '<div class="external">' + links + '</div>' +
            '</div>';
        elInfo.classList.remove('hidden');

        // Wire up the imagery button after (re)render.
        const btn = document.getElementById('open-imagery');
        if (btn) btn.addEventListener('click', () => openImageryPanel(sat));
    }

    // ---------- Landsat imagery side panel ----------
    // Sources:
    //   • EarthNow        — https://earthnow.usgs.gov/observer/  (near-real-time Landsat
    //                       8/9 downlink as data arrives at EROS, auto-advancing tiles).
    //   • LandsatLook     — https://landsatlook.usgs.gov/        (interactive 24h / archive
    //                       viewer with full scene search and replay).
    //   • NASA Worldview  — https://worldview.earthdata.nasa.gov/?l=Landsat_WELD_CONUS_... 
    //                       (daily Landsat imagery over GIBS tiles, date-scrubbable).
    // Note: some of these providers set X-Frame-Options: SAMEORIGIN and cannot be iframed.
    // We detect that and show a "Open in new tab" fallback so the UX never breaks.
    const IMAGERY_SOURCES = {
        live:      { label: 'Live Downlink', url: 'https://earthnow.usgs.gov/observer/',
                     caption: 'EarthNow — Landsat 8/9 downlink as acquisitions arrive at USGS EROS (near real-time).' },
        look:      { label: '24h Replay',    url: 'https://landsatlook.usgs.gov/',
                     caption: 'LandsatLook — scrubbable full-resolution archive; set the date slider to the last 24 hours for replay.' },
        worldview: { label: 'Worldview',     url: 'https://worldview.earthdata.nasa.gov/?v=-180,-90,180,90&l=Reference_Labels_15m,Reference_Features_15m,Coastlines_15m,Landsat_WELD_CorrectedReflectance_Bands743_Global_Monthly(hidden),MODIS_Terra_CorrectedReflectance_TrueColor&lg=true',
                     caption: 'NASA Worldview — Landsat and MODIS imagery with a 24-hour timeline at the bottom for replay.' }
    };

    const elImagery      = $('imagery');
    const elImageryFrame = $('imagery-frame');
    const elImageryCap   = $('imagery-caption');
    const elImageryTitle = $('imagery-title');
    const elImageryFallback = $('imagery-fallback');
    const elImageryFallbackLink = $('imagery-fallback-link');
    let   imageryLoadTimer = null;

    function openImageryPanel(sat) {
        elImageryTitle.textContent = (sat && sat.name ? sat.name : 'Landsat') + ' — Imagery';
        elImagery.classList.remove('hidden');
        document.body.classList.add('imagery-open');
        // Default tab = live.
        setImageryTab('live');
    }

    function closeImageryPanel() {
        elImagery.classList.add('hidden');
        document.body.classList.remove('imagery-open');
        // Stop any playing media by clearing the src.
        elImageryFrame.src = 'about:blank';
        elImageryFallback.classList.add('hidden');
    }

    function setImageryTab(key) {
        const src = IMAGERY_SOURCES[key];
        if (!src) return;
        document.querySelectorAll('#imagery .tab').forEach(t => {
            t.classList.toggle('active', t.getAttribute('data-tab') === key);
        });
        elImageryCap.textContent = src.caption;
        elImageryFallback.classList.add('hidden');
        elImageryFrame.style.visibility = 'visible';
        elImageryFrame.src = src.url;

        // If the provider blocks framing (X-Frame-Options / CSP), onload never fires with
        // a readable document. Give it 6 s; if nothing rendered, show the fallback link.
        clearTimeout(imageryLoadTimer);
        let loaded = false;
        elImageryFrame.onload = () => { loaded = true; };
        imageryLoadTimer = setTimeout(() => {
            if (!loaded) {
                elImageryFallbackLink.href = src.url;
                elImageryFallbackLink.textContent = 'Open ' + src.label + ' in new tab →';
                elImageryFallback.classList.remove('hidden');
            }
        }, 6000);
    }

    document.querySelectorAll('#imagery .tab').forEach(t => {
        t.addEventListener('click', () => setImageryTab(t.getAttribute('data-tab')));
    });
    $('imagery-close').addEventListener('click', closeImageryPanel);

    // ---------- Picking ----------
    canvas.addEventListener('click', onCanvasClick);

    function onCanvasClick(ev) {
        if (!state.points || state.sats.length === 0) return;
        const rect = canvas.getBoundingClientRect();
        const mx = ev.clientX - rect.left;
        const my = ev.clientY - rect.top;
        const W = rect.width, H = rect.height;
        // Project each satellite to screen; pick the one within PICK_PX pixels closest to
        // the click. PICK_PX of 10 gives forgiving selection without grabbing the wrong one.
        const PICK_PX = 10;
        const v = new THREE.Vector3();
        let best = -1, bestD = PICK_PX * PICK_PX;
        const pos = state.positions;
        for (let i = 0; i < state.sats.length; i++) {
            v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
            v.project(camera);
            if (v.z > 1 || v.z < -1) continue; // outside frustum
            const sx = (v.x * 0.5 + 0.5) * W;
            const sy = (-v.y * 0.5 + 0.5) * H;
            const dx = sx - mx, dy = sy - my;
            const d2 = dx * dx + dy * dy;
            if (d2 < bestD) { bestD = d2; best = i; }
        }
        if (best >= 0) selectSatellite(best);
    }

    // ---------- Main loop ----------
    function currentDate() {
        if (state.live && state.timeRate === 1) return new Date();
        return new Date(state.simTimeMs);
    }

    let lastFrame = performance.now();
    let lastPropagate = 0;
    const PROPAGATE_INTERVAL_MS = 100; // 10 Hz — more than enough for visible orbital motion.
    function frame(now) {
        const dt = now - lastFrame; lastFrame = now;
        if (state.live) {
            state.simTimeMs = (state.timeRate === 1) ? Date.now() : state.simTimeMs + dt * state.timeRate;
        }
        const d = currentDate();
        // Throttle expensive SGP4 propagation to 10 Hz; render still runs at display rate.
        if (now - lastPropagate > PROPAGATE_INTERVAL_MS || state.timeRate !== 1) {
            propagateAll(d);
            lastPropagate = now;
        }
        elUtc.textContent = d.toISOString().replace('T', ' ').slice(0, 19) + 'Z';

        // Update selected marker ring position/orientation to face camera.
        if (state.selected != null && state.selectedMarker) {
            const i = state.selected;
            const p = state.positions;
            state.selectedMarker.position.set(p[i * 3], p[i * 3 + 1], p[i * 3 + 2]);
            state.selectedMarker.lookAt(camera.position);
        }

        controls.update();
        renderer.render(scene, camera);
        requestAnimationFrame(frame);
    }

    // ---------- Resize ----------
    window.addEventListener('resize', () => {
        const w = window.innerWidth, h = window.innerHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h, false);
    });

    // ---------- Boot ----------
    if (typeof satellite === 'undefined') {
        setStatus('satellite.js failed to load. Check network / CDN.');
        return;
    }
    reloadSatellites().catch(e => setStatus('Load error: ' + e.message));
    requestAnimationFrame(frame);
})();
