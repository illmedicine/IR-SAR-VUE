# NIS SAR Viewer — Real-Time Orbital Tracker

A browser-based 3D globe that tracks every satellite in selected CelesTrak catalogs in real time, using SGP4 propagation. Click any satellite to see its name, operator, purpose, orbit, and external reference links.

## Features
- Real-time SGP4 propagation (via [satellite.js](https://github.com/shashwatak/satellite-js))
- 20+ toggleable catalogs (Starlink, GPS, ISS, weather, military, etc.) from [CelesTrak](https://celestrak.org)
- Click-to-inspect: altitude, lat/lon, speed, period, inclination, eccentricity, operator, purpose
- Orbit-path and ground-footprint overlays
- Search by name or NORAD ID
- Time controls: live / 10× / 60× / 600× / 3600×
- External links to N2YO, CelesTrak, Space-Track, Heavens-Above

## Local preview
No build step. Serve the `docs/` folder with any static server:

```powershell
cd docs
python -m http.server 8000
# then open http://localhost:8000
```

Opening `docs/index.html` directly via `file://` will fail — the CelesTrak fetches require an `http(s)://` origin.

## Deploy to GitHub Pages
The included workflow at `.github/workflows/pages.yml` publishes `docs/` automatically on every push to `main`.

One-time setup:
1. Push this repo to GitHub.
2. In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Push to `main`. The app will be live at `https://<user>.github.io/<repo>/`.

## Deploy to GoDaddy (or any static host)
Upload the entire `docs/` folder contents to your web root (`public_html/`). No server-side code is needed.

## Adding per-satellite metadata
Edit `docs/js/satellites.js` — append to the `KNOWN` object, keyed by NORAD catalog number:

```js
'12345': {
    name: 'MY SAT',
    operator: 'Owner',
    launched: 'YYYY-MM-DD',
    country: 'XX',
    purpose: 'What the satellite does.',
    orbit: 'LEO ~500 km, 51.6°'
}
```

Name-prefix heuristics in `guessMeta()` fill in sensible defaults for STARLINK, ONEWEB, IRIDIUM, GPS, COSMOS, USA, etc.

## Notes & limitations
- TLE accuracy degrades with epoch age; CelesTrak refreshes daily. Position error grows with propagation span — best within a few days of TLE epoch.
- The Earth sphere is currently untextured (wireframe look) to keep dependencies zero. To add a realistic Earth, drop a `textures/earth.jpg` and replace the `MeshPhongMaterial` in `app.js` with a textured one.
- Footprint = geometric horizon circle; it does not account for antenna pattern or minimum elevation.
- JWST and deep-space objects have limited TLE accuracy; treat their positions as approximate.

## Data source
Public TLEs from [CelesTrak](https://celestrak.org/) GP group endpoints. Please respect their fair-use policy; consider hosting your own periodic TLE mirror for production use.
