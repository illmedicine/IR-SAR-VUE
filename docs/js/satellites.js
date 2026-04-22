/* satellites.js — TLE catalog definitions, fetching, categorization, metadata lookup.
 * Data source: CelesTrak (https://celestrak.org), free public TLEs. No API key required.
 * Loaded as a plain script (exposes window.SatCatalog).
 */
(function (global) {
    'use strict';

    // Catalog groups fetched from CelesTrak 'gp.php' (TLE format).
    // Color chosen for point rendering; purpose text shown in info panel when a per-sat entry isn't present.
    const CATALOGS = [
        { id: 'stations',   name: 'Space Stations',    color: 0xffffff, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle',         purpose: 'Crewed or cargo spacecraft (ISS, Tiangong, resupply).', kind: 'sci', on: true },
        { id: 'starlink',   name: 'Starlink',          color: 0x66bbff, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle',         purpose: 'SpaceX broadband constellation (LEO, ~550 km).',         kind: 'com', on: true },
        { id: 'oneweb',     name: 'OneWeb',            color: 0x99ddff, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=oneweb&FORMAT=tle',           purpose: 'OneWeb broadband constellation (~1200 km).',             kind: 'com', on: false },
        { id: 'gps-ops',    name: 'GPS',               color: 0xffcc44, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=gps-ops&FORMAT=tle',          purpose: 'US NAVSTAR GPS navigation (MEO).',                       kind: 'nav', on: true },
        { id: 'glo-ops',    name: 'GLONASS',           color: 0xff9955, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=glo-ops&FORMAT=tle',          purpose: 'Russian GLONASS navigation (MEO).',                      kind: 'nav', on: false },
        { id: 'galileo',    name: 'Galileo',           color: 0xaa88ff, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=galileo&FORMAT=tle',          purpose: 'EU Galileo navigation (MEO).',                           kind: 'nav', on: false },
        { id: 'beidou',     name: 'BeiDou',            color: 0xff66aa, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=beidou&FORMAT=tle',           purpose: 'Chinese BeiDou navigation (MEO/GEO/IGSO).',              kind: 'nav', on: false },
        { id: 'science',    name: 'Science',           color: 0xc6aaff, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=science&FORMAT=tle',          purpose: 'Space science and observatories.',                      kind: 'sci', on: false },
        { id: 'weather',    name: 'Weather',           color: 0x55ddcc, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle',          purpose: 'Meteorological satellites (LEO/GEO).',                   kind: 'sci', on: false },
        { id: 'noaa',       name: 'NOAA',              color: 0x33bbaa, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=noaa&FORMAT=tle',             purpose: 'NOAA environmental / polar weather.',                    kind: 'sci', on: false },
        { id: 'goes',       name: 'GOES',              color: 0x22aa99, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=goes&FORMAT=tle',             purpose: 'Geostationary weather (GEO).',                           kind: 'sci', on: false },
        { id: 'resource',   name: 'Earth Resources',   color: 0x88dd66, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=resource&FORMAT=tle',         purpose: 'Earth observation / imagery.',                           kind: 'sci', on: false },
        { id: 'sarsat',     name: 'Search & Rescue',   color: 0xffaa66, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=sarsat&FORMAT=tle',           purpose: 'COSPAS-SARSAT beacon relay.',                            kind: 'sci', on: false },
        { id: 'geo',        name: 'Geostationary',     color: 0xffdd88, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=geo&FORMAT=tle',              purpose: 'Active geostationary satellites.',                       kind: 'com', on: false },
        { id: 'intelsat',   name: 'Intelsat',          color: 0x88bbff, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=intelsat&FORMAT=tle',         purpose: 'Intelsat commercial comms (GEO).',                       kind: 'com', on: false },
        { id: 'iridium-NEXT', name: 'Iridium NEXT',    color: 0x5599ee, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-NEXT&FORMAT=tle',     purpose: 'Iridium NEXT voice/data/L-band (LEO, ~780 km).',         kind: 'com', on: false },
        { id: 'planet',     name: 'Planet Labs',       color: 0x77ee99, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=planet&FORMAT=tle',           purpose: 'Planet imaging cubesats (Dove/SuperDove).',              kind: 'sci', on: false },
        { id: 'spire',      name: 'Spire',             color: 0x99ee77, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=spire&FORMAT=tle',            purpose: 'Spire Lemur AIS/weather cubesats.',                      kind: 'sci', on: false },
        { id: 'military',   name: 'Military',          color: 0xff5566, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=military&FORMAT=tle',         purpose: 'Unclassified military payloads.',                        kind: 'mil', on: false },
        { id: 'cubesat',    name: 'CubeSats',          color: 0xaaaaaa, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=cubesat&FORMAT=tle',          purpose: 'CubeSat-class smallsats (miscellaneous).',               kind: 'sci', on: false },
        { id: 'active',     name: 'All Active',        color: 0x888888, url: 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle',           purpose: 'All tracked active objects.',                            kind: 'other', on: false }
    ];

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

    // Fetch all enabled catalogs; report progress via onProgress(catalogName, count).
    async function fetchEnabled(enabledIds, onProgress) {
        const sats = [];
        const errors = [];
        for (const cat of CATALOGS) {
            if (!enabledIds.has(cat.id)) continue;
            try {
                if (onProgress) onProgress(cat.name, null);
                const resp = await fetch(cat.url, { cache: 'force-cache' });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const txt = await resp.text();
                const parsed = parseTLE(txt, cat);
                sats.push(...parsed);
                if (onProgress) onProgress(cat.name, parsed.length);
            } catch (e) {
                errors.push(cat.name + ': ' + e.message);
                if (onProgress) onProgress(cat.name, -1);
            }
        }
        return { sats, errors };
    }

    function metaFor(sat) {
        return KNOWN[sat.noradId] || guessMeta(sat.name) || null;
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

    global.SatCatalog = { CATALOGS, KNOWN, parseTLE, fetchEnabled, metaFor, externalLinks };
})(window);
