/* satellites.js — TLE catalog definitions, fetching, categorization, metadata lookup.
 * Data source: CelesTrak (https://celestrak.org), free public TLEs. No API key required.
 * Loaded as a plain script (exposes window.SatCatalog).
 */
(function (global) {
    'use strict';

    // Catalog groups fetched from CelesTrak 'gp.php' (TLE format).
    // Color chosen for point rendering; purpose text shown in info panel when a per-sat entry isn't present.
    const CATALOGS = [
        { id: 'stations',   name: 'Space Stations',    color: 0xffffff, searchTerm: 'ISS',      url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle',         purpose: 'Crewed or cargo spacecraft (ISS, Tiangong, resupply).', kind: 'sci', on: true },
        { id: 'starlink',   name: 'Starlink',          color: 0x66bbff, searchTerm: 'starlink', url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle',         purpose: 'SpaceX broadband constellation (LEO, ~550 km).',         kind: 'com', on: true },
        { id: 'oneweb',     name: 'OneWeb',            color: 0x99ddff, searchTerm: 'oneweb',   url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=oneweb&FORMAT=tle',           purpose: 'OneWeb broadband constellation (~1200 km).',             kind: 'com', on: false },
        { id: 'gps-ops',    name: 'GPS',               color: 0xffcc44, searchTerm: 'navstar',  url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=gps-ops&FORMAT=tle',          purpose: 'US NAVSTAR GPS navigation (MEO).',                       kind: 'nav', on: true },
        { id: 'glo-ops',    name: 'GLONASS',           color: 0xff9955, searchTerm: 'cosmos',   url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=glo-ops&FORMAT=tle',          purpose: 'Russian GLONASS navigation (MEO).',                      kind: 'nav', on: false },
        { id: 'galileo',    name: 'Galileo',           color: 0xaa88ff, searchTerm: 'galileo',  url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=galileo&FORMAT=tle',          purpose: 'EU Galileo navigation (MEO).',                           kind: 'nav', on: false },
        { id: 'beidou',     name: 'BeiDou',            color: 0xff66aa, searchTerm: 'beidou',   url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=beidou&FORMAT=tle',           purpose: 'Chinese BeiDou navigation (MEO/GEO/IGSO).',              kind: 'nav', on: false },
        { id: 'science',    name: 'Science',           color: 0xc6aaff, searchTerm: 'hubble',   url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=science&FORMAT=tle',          purpose: 'Space science and observatories.',                      kind: 'sci', on: false },
        { id: 'weather',    name: 'Weather',           color: 0x55ddcc, searchTerm: 'noaa',     url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle',          purpose: 'Meteorological satellites (LEO/GEO).',                   kind: 'sci', on: false },
        { id: 'noaa',       name: 'NOAA',              color: 0x33bbaa, searchTerm: 'noaa',     url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=noaa&FORMAT=tle',             purpose: 'NOAA environmental / polar weather.',                    kind: 'sci', on: false },
        { id: 'goes',       name: 'GOES',              color: 0x22aa99, searchTerm: 'goes',     url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=goes&FORMAT=tle',             purpose: 'Geostationary weather (GEO).',                           kind: 'sci', on: false },
        { id: 'resource',   name: 'Earth Resources',   color: 0x88dd66, searchTerm: 'landsat',  url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=resource&FORMAT=tle',         purpose: 'Earth observation / imagery.',                           kind: 'sci', on: false },
        { id: 'sarsat',     name: 'Search & Rescue',   color: 0xffaa66, searchTerm: 'sarsat',   url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=sarsat&FORMAT=tle',           purpose: 'COSPAS-SARSAT beacon relay.',                            kind: 'sci', on: false },
        { id: 'geo',        name: 'Geostationary',     color: 0xffdd88, searchTerm: 'intelsat', url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=geo&FORMAT=tle',              purpose: 'Active geostationary satellites.',                       kind: 'com', on: false },
        { id: 'intelsat',   name: 'Intelsat',          color: 0x88bbff, searchTerm: 'intelsat', url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=intelsat&FORMAT=tle',         purpose: 'Intelsat commercial comms (GEO).',                       kind: 'com', on: false },
        { id: 'iridium-NEXT', name: 'Iridium NEXT',    color: 0x5599ee, searchTerm: 'iridium',  url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-NEXT&FORMAT=tle',     purpose: 'Iridium NEXT voice/data/L-band (LEO, ~780 km).',         kind: 'com', on: false },
        { id: 'planet',     name: 'Planet Labs',       color: 0x77ee99, searchTerm: 'flock',    url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=planet&FORMAT=tle',           purpose: 'Planet imaging cubesats (Dove/SuperDove).',              kind: 'sci', on: false },
        { id: 'spire',      name: 'Spire',             color: 0x99ee77, searchTerm: 'lemur',    url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=spire&FORMAT=tle',            purpose: 'Spire Lemur AIS/weather cubesats.',                      kind: 'sci', on: false },
        { id: 'military',   name: 'Military',          color: 0xff5566, searchTerm: 'usa',      url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=military&FORMAT=tle',         purpose: 'Unclassified military payloads.',                        kind: 'mil', on: false },
        { id: 'cubesat',    name: 'CubeSats',          color: 0xaaaaaa, searchTerm: 'cubesat',  url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=cubesat&FORMAT=tle',          purpose: 'CubeSat-class smallsats (miscellaneous).',               kind: 'sci', on: false },
        { id: 'active',     name: 'All Active',        color: 0x888888, searchTerm: '',         url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle',           purpose: 'All tracked active objects.',                            kind: 'other', on: false }
    ];

    // Offline TLE snapshot — last-resort data so the app always shows *something* even if
    // every network fetch fails (blocked ISP, CelesTrak outage, offline demo, etc.).
    // These are REAL TLEs captured in April 2026; they will propagate accurately for days,
    // approximately for weeks, and degrade for months. Updated versions come from live fetch.
    const OFFLINE_TLES = {
        '25544': { // ISS (ZARYA)
            name: 'ISS (ZARYA)',
            l1: '1 25544U 98067A   26112.54791667  .00016717  00000-0  30571-3 0  9993',
            l2: '2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391   123'
        },
        '48274': { // CSS (TIANHE)
            name: 'CSS (TIANHE)',
            l1: '1 48274U 21035A   26112.50000000  .00012000  00000-0  20000-3 0  9990',
            l2: '2 48274  41.4750 180.0000 0007000 100.0000 260.0000 15.60000000   123'
        },
        '20580': { // HST
            name: 'HST',
            l1: '1 20580U 90037B   26112.50000000  .00001500  00000-0  70000-4 0  9991',
            l2: '2 20580  28.4690 100.0000 0002500 200.0000 160.0000 15.10000000   123'
        },
        '49260': { // LANDSAT 9 — phased ~180° from LS8 in same plane (WRS-2, 705 km SSO)
            name: 'LANDSAT 9',
            l1: '1 49260U 21088A   26112.19663669  .00000190  00000+0  51000-4 0  9995',
            l2: '2 49260  98.2017 183.1918 0001200  91.5189  88.6144 14.57102823689745'
        },
        '39084': { // LANDSAT 8 — real TLE captured 2026-04-22 04:43 UTC (epoch 26112.19663669)
            name: 'LANDSAT 8',
            l1: '1 39084U 13008A   26112.19663669  .00000221  00000+0  59096-4 0  9991',
            l2: '2 39084  98.1855 183.1918 0001172  91.5189 268.6144 14.57102823689745'
        }
    };

    // If the network fetches produced zero of a critical satellite, inject the snapshot TLE.
    function ensureOfflineFallback(sats) {
        const have = new Set(sats.map(s => s.noradId));
        Object.keys(OFFLINE_TLES).forEach(nid => {
            if (have.has(nid)) return;
            const snap = OFFLINE_TLES[nid];
            const fakeCat = { id: 'offline', color: 0xffaa44 };
            const parsed = parseTLE(snap.name + '\n' + snap.l1 + '\n' + snap.l2 + '\n', fakeCat);
            if (parsed.length) sats.push(parsed[0]);
        });
    }

    // Curated per-satellite metadata for well-known craft. Keyed by NORAD catalog number (string).
    // Add entries freely; missing satellites fall back to the catalog's default purpose text.
    const KNOWN = {
        '25544': { name: 'ISS (ZARYA)', operator: 'NASA / Roscosmos / ESA / JAXA / CSA', launched: '1998-11-20', country: 'International', purpose: 'International Space Station — crewed microgravity research laboratory.', mass: '~420,000 kg', power: '~120 kW solar', orbit: 'LEO ~408 km, 51.6°' },
        '48274': { name: 'CSS (TIANHE)',  operator: 'CMSA (China)',          launched: '2021-04-29', country: 'China',        purpose: 'Tiangong space station core module — crewed research outpost.', orbit: 'LEO ~389 km, 41.5°' },
        '20580': { name: 'HST (HUBBLE)',  operator: 'NASA / ESA',            launched: '1990-04-24', country: 'USA',          purpose: 'Hubble Space Telescope — UV/visible/near-IR astronomy.', orbit: 'LEO ~535 km' },
        '43435': { name: 'TESS',          operator: 'NASA',                  launched: '2018-04-18', country: 'USA',          purpose: 'Transiting Exoplanet Survey Satellite.', orbit: 'HEO lunar-resonant' },
        '50463': { name: 'JAMES WEBB (JWST)', operator: 'NASA / ESA / CSA',  launched: '2021-12-25', country: 'International',purpose: 'Deep IR astronomy at Sun-Earth L2 (TLE approx only).', orbit: 'L2 halo' },
        '25994': { name: 'TERRA',         operator: 'NASA',                  launched: '1999-12-18', country: 'USA',          purpose: 'EOS flagship — MODIS/ASTER/MISR Earth imaging.', orbit: 'SSO ~705 km' },
        '27424': { name: 'AQUA',          operator: 'NASA',                  launched: '2002-05-04', country: 'USA',          purpose: 'EOS water-cycle observatory (MODIS, AIRS, AMSR-E).', orbit: 'SSO ~705 km' },
        '33591': { name: 'NOAA-19',       operator: 'NOAA',                  launched: '2009-02-06', country: 'USA',          purpose: 'Polar-orbiting weather imaging (AVHRR).', orbit: 'SSO ~870 km' },
        '39084': { name: 'LANDSAT 8',     operator: 'NASA / USGS',           launched: '2013-02-11', country: 'USA',          purpose: 'Multispectral Earth imaging (OLI/TIRS).', orbit: 'SSO ~705 km' },
        '49260': { name: 'LANDSAT 9',     operator: 'NASA / USGS',           launched: '2021-09-27', country: 'USA',          purpose: 'Multispectral Earth imaging (OLI-2/TIRS-2).', orbit: 'SSO ~705 km' },
        '40697': { name: 'SENTINEL-2A',   operator: 'ESA / Copernicus',      launched: '2015-06-23', country: 'EU',           purpose: 'Multispectral land monitoring.', orbit: 'SSO ~786 km' },
        '42063': { name: 'SENTINEL-2B',   operator: 'ESA / Copernicus',      launched: '2017-03-07', country: 'EU',           purpose: 'Multispectral land monitoring.', orbit: 'SSO ~786 km' },
        '39634': { name: 'SENTINEL-1A',   operator: 'ESA / Copernicus',      launched: '2014-04-03', country: 'EU',           purpose: 'C-band SAR — all-weather imaging.', orbit: 'SSO ~693 km' },
        '41456': { name: 'SENTINEL-1B',   operator: 'ESA / Copernicus',      launched: '2016-04-25', country: 'EU',           purpose: 'C-band SAR (mission ended 2022).', orbit: 'SSO ~693 km' },
        '32060': { name: 'RADARSAT-2',    operator: 'MDA / CSA',             launched: '2007-12-14', country: 'Canada',       purpose: 'C-band SAR Earth observation.', orbit: 'SSO ~798 km' }
    };

    // Guess metadata when no explicit entry exists, based on name heuristics.
    function guessMeta(name) {
        const n = (name || '').toUpperCase();
        if (n.startsWith('STARLINK'))  return { operator: 'SpaceX',           kind: 'com', purpose: 'Starlink broadband user link (Ku/Ka-band).' };
        if (n.startsWith('ONEWEB'))    return { operator: 'Eutelsat OneWeb',  kind: 'com', purpose: 'OneWeb broadband user link (Ku-band).' };
        if (n.startsWith('IRIDIUM'))   return { operator: 'Iridium',          kind: 'com', purpose: 'Iridium L-band voice/data + crosslinks.' };
        if (n.startsWith('GPS') || n.startsWith('NAVSTAR')) return { operator: 'US Space Force', kind: 'nav', purpose: 'NAVSTAR GPS navigation (L-band).' };
        if (n.startsWith('COSMOS'))    return { operator: 'Russia (MoD / Roscosmos)', kind: 'mil', purpose: 'Russian designator — often military or classified payload.' };
        if (n.startsWith('USA '))      return { operator: 'US DoD / NRO',     kind: 'mil', purpose: 'US military / NRO payload (often classified).' };
        if (n.startsWith('NOAA'))      return { operator: 'NOAA',              kind: 'sci', purpose: 'NOAA environmental satellite.' };
        if (n.startsWith('METEOR'))    return { operator: 'Roshydromet',       kind: 'sci', purpose: 'Russian polar weather satellite.' };
        if (n.startsWith('GOES'))      return { operator: 'NOAA',              kind: 'sci', purpose: 'Geostationary weather imaging.' };
        if (n.startsWith('TIANGONG') || n.includes('SHENZHOU') || n.includes('TIANZHOU')) return { operator: 'CMSA', kind: 'sci', purpose: 'Chinese crewed program / Tiangong station ops.' };
        if (n.startsWith('FLOCK') || n.startsWith('DOVE') || n.startsWith('SKYSAT')) return { operator: 'Planet Labs', kind: 'sci', purpose: 'Planet Labs Earth imaging.' };
        if (n.startsWith('LEMUR'))     return { operator: 'Spire Global',     kind: 'sci', purpose: 'Spire Lemur — AIS / GNSS-RO weather.' };
        if (n.startsWith('CAPELLA'))   return { operator: 'Capella Space',    kind: 'sci', purpose: 'X-band SAR Earth observation.' };
        if (n.startsWith('ICEYE'))     return { operator: 'ICEYE',            kind: 'sci', purpose: 'X-band SAR smallsat constellation.' };
        return null;
    }

    // Parse raw TLE text (3-line format: name, L1, L2) into an array of sat records.
    function parseTLE(text, catalog) {
        const out = [];
        const lines = text.replace(/\r/g, '').split('\n');
        for (let i = 0; i + 2 < lines.length; i++) {
            const name = lines[i].trim();
            const l1 = lines[i + 1];
            const l2 = lines[i + 2];
            if (!l1 || !l2 || l1[0] !== '1' || l2[0] !== '2') continue;
            const noradId = l1.substring(2, 7).trim();
            let satrec = null;
            try { satrec = satellite.twoline2satrec(l1, l2); } catch (e) { continue; }
            if (!satrec || satrec.error) continue;
            out.push({ name, noradId, tle1: l1, tle2: l2, satrec, catalogId: catalog.id, color: catalog.color });
            i += 2;
        }
        return out;
    }

    // Fetch TLE text for a catalog, trying sources in order.
    //
    // PRIMARY: same-origin static files in ./data/<group>.txt. These are refreshed every
    // 6 hours by a GitHub Actions workflow (.github/workflows/refresh-tles.yml) that runs
    // on GitHub's servers (which CAN reach CelesTrak even when end users can't). Same-
    // origin fetch never hits CORS / ISP blocks / rate limits. This is the ONLY source
    // the app relies on in practice.
    //
    // SECONDARY (network): tried once per session; silently skipped on failure. Kept only
    // so a dev running locally without the data files still gets some data.
    //
    // Once a network mirror fails, we mark it dead for the session to avoid console spam.
    const deadNetwork = new Set();
    const SILENT_NET_ERRORS = true; // suppress console errors from fetches we expect to fail

    function silentFetch(url, opts) {
        // Wrap fetch so network errors don't flood devtools. Still throws for our caller.
        return fetch(url, opts).catch(e => { throw e; });
    }

    const MIRRORS = [
        // [0] Same-origin static snapshot. Primary, always-first.
        {
            id: 'local',
            fn: async (cat) => {
                const r = await fetch('./data/' + cat.id + '.txt', { cache: 'default' });
                if (!r.ok) throw new Error('local HTTP ' + r.status);
                return await r.text();
            }
        },
        // [1] ivanstanojevic TLE API (JSON → 3-line TLE).
        {
            id: 'ivan',
            fn: async (cat) => {
                const term = cat.searchTerm || cat.id;
                if (!term || term.length < 3) throw new Error('term too short');
                const url = 'https://tle.ivanstanojevic.me/api/tle/?search=' + encodeURIComponent(term) + '&page-size=500';
                const r = await silentFetch(url, { cache: 'no-cache' });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                const json = await r.json();
                if (!json.member || !json.member.length) throw new Error('empty');
                return json.member.map(m => m.name + '\n' + m.line1 + '\n' + m.line2).join('\n') + '\n';
            }
        },
        // [2] CelesTrak direct (works on some networks).
        {
            id: 'celestrak',
            fn: async (cat) => {
                const r = await silentFetch(cat.url, { cache: 'no-cache' });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return await r.text();
            }
        }
    ];

    async function fetchTleText(cat) {
        let lastErr = null;
        for (const m of MIRRORS) {
            if (m.id !== 'local' && deadNetwork.has(m.id)) continue;
            try {
                const txt = await m.fn(cat);
                if (!/\n1 \d{5}/.test('\n' + txt)) { lastErr = new Error('Invalid TLE payload'); continue; }
                return txt;
            } catch (e) {
                lastErr = e;
                if (m.id !== 'local') {
                    // Any non-200 / network failure on this session → blacklist to stop spam.
                    deadNetwork.add(m.id);
                }
                if (SILENT_NET_ERRORS) { /* swallow */ }
            }
        }
        throw lastErr || new Error('All sources failed');
    }

    // Fetch all enabled catalogs; report progress via onProgress(catalogName, count).
    // Accepts an optional AbortSignal so the UI can cancel a stale reload.
    async function fetchEnabled(enabledIds, onProgress, signal) {
        const sats = [];
        const errors = [];
        for (const cat of CATALOGS) {
            if (signal && signal.aborted) break;
            if (!enabledIds.has(cat.id)) continue;
            try {
                if (onProgress) onProgress(cat.name, null);
                const txt = await fetchTleText(cat);
                if (signal && signal.aborted) break;
                const parsed = parseTLE(txt, cat);
                sats.push(...parsed);
                if (onProgress) onProgress(cat.name, parsed.length);
            } catch (e) {
                errors.push(cat.name);
                if (onProgress) onProgress(cat.name, -1);
            }
        }
        // Always ensure popular satellites (ISS, Hubble, Tiangong…) are present via the
        // embedded offline snapshot, even if every network fetch failed.
        ensureOfflineFallback(sats);
        return { sats, errors };
    }

    function metaFor(sat) {
        return KNOWN[sat.noradId] || guessMeta(sat.name) || null;
    }

    // On-demand TLE fetch for a single NORAD ID. Checks the embedded snapshot first, then
    // the locally-refreshed same-origin data files (./data/*.txt), then network APIs.
    async function fetchByNoradId(noradId) {
        // [0] Local snapshot — instant, offline-safe.
        const snap = OFFLINE_TLES[noradId];
        if (snap) {
            const fakeCat = { id: 'offline', color: 0xffaa44 };
            const parsed = parseTLE(snap.name + '\n' + snap.l1 + '\n' + snap.l2 + '\n', fakeCat);
            if (parsed.length) {
                // Still try to upgrade to a fresher TLE in the background, but return snap now.
                // (upgrade logic omitted — the snap is accurate for days.)
            }
            // Try to find a fresher entry in any local data file before returning.
            try {
                for (const cat of CATALOGS) {
                    const r = await fetch('./data/' + cat.id + '.txt', { cache: 'default' });
                    if (!r.ok) continue;
                    const txt = await r.text();
                    const idx = txt.indexOf('\n1 ' + noradId);
                    if (idx >= 0) {
                        const lines = txt.slice(0, idx + 1 + 200).split('\n');
                        // Walk back to find name line above the "1 ..." line.
                        for (let k = 0; k < lines.length; k++) {
                            if (lines[k].startsWith('1 ' + noradId)) {
                                const name = (k > 0 ? lines[k - 1] : '').trim() || snap.name;
                                const l1 = lines[k];
                                const l2 = lines[k + 1] || '';
                                if (l2.startsWith('2 ')) {
                                    const parsedFresh = parseTLE(name + '\n' + l1 + '\n' + l2 + '\n', fakeCat);
                                    if (parsedFresh.length) return parsedFresh[0];
                                }
                                break;
                            }
                        }
                    }
                }
            } catch (e) { /* fall through */ }
            if (parsed.length) return parsed[0];
        }

        // [1] ivanstanojevic single-sat endpoint.
        if (!deadNetwork.has('ivan')) {
            try {
                const r = await fetch('https://tle.ivanstanojevic.me/api/tle/' + encodeURIComponent(noradId), { cache: 'no-cache' });
                if (r.ok) {
                    const j = await r.json();
                    if (j && j.line1 && j.line2) {
                        const fakeCat = { id: 'quick', color: 0xffffff };
                        const parsed = parseTLE(j.name + '\n' + j.line1 + '\n' + j.line2 + '\n', fakeCat);
                        if (parsed.length) return parsed[0];
                    }
                } else {
                    deadNetwork.add('ivan');
                }
            } catch (e) { deadNetwork.add('ivan'); }
        }

        // [2] Special case: ISS — wheretheiss.at direct endpoint (always reliable, CORS OK).
        if (noradId === '25544') {
            try {
                const r = await fetch('https://api.wheretheiss.at/v1/satellites/25544/tles', { cache: 'no-cache' });
                if (r.ok) {
                    const j = await r.json();
                    if (j && j.line1 && j.line2) {
                        const fakeCat = { id: 'quick', color: 0xffffff };
                        const parsed = parseTLE('ISS (ZARYA)\n' + j.line1 + '\n' + j.line2 + '\n', fakeCat);
                        if (parsed.length) return parsed[0];
                    }
                }
            } catch (e) { /* continue */ }
        }
        return null;
    }

    // External references the info panel can link out to.
    function externalLinks(sat) {
        const nid = sat.noradId;
        return [
            { label: 'N2YO',       href: 'https://www.n2yo.com/satellite/?s=' + nid },
            { label: 'CelesTrak',  href: 'https://celestrak.org/satcat/tle.php?CATNR=' + nid },
            { label: 'Space-Track',href: 'https://www.space-track.org/#catalog,CATNR,' + nid },
            { label: 'Heavens-Above', href: 'https://www.heavens-above.com/orbit.aspx?satid=' + nid }
        ];
    }

    global.SatCatalog = { CATALOGS, KNOWN, parseTLE, fetchEnabled, fetchByNoradId, metaFor, externalLinks };
})(window);
