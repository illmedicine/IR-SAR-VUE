/* geo.js — lightweight reverse-geocoding for World SAR.
 *
 * Loads two public-domain GeoJSON datasets at startup:
 *   1. Natural Earth 1:110m country polygons (~250 KB).
 *   2. US Census state polygons (~150 KB).
 *
 * Exposes window.WorldGeo with:
 *   load()                        → Promise<void> (idempotent)
 *   countryAt(lat, lon)           → string | null
 *   subdivisionAt(lat, lon)       → string | null   (US state today; extensible)
 *   locationFor(lat, lon)         → e.g. "United States — Texas" | "Pacific Ocean"
 *   countries                     → loaded country features (used for label overlay)
 *   states                        → loaded US state features (used for label overlay)
 */
(function () {
    'use strict';

    const COUNTRY_URL =
        'https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_110m_admin_0_countries.geojson';
    const STATES_URL =
        'https://cdn.jsdelivr.net/gh/PublicaMundi/MappingAPI@master/data/geojson/us-states.json';

    const W = window;
    W.WorldGeo = {
        countries: [],
        states: [],
        loaded: false,
        loading: null,

        load() {
            if (this.loaded) return Promise.resolve();
            if (this.loading) return this.loading;
            this.loading = Promise.all([
                fetch(COUNTRY_URL).then(r => r.json()).catch(() => null),
                fetch(STATES_URL).then(r => r.json()).catch(() => null)
            ]).then(([countries, states]) => {
                if (countries && countries.features) {
                    this.countries = countries.features.map(f => buildFeature(
                        f,
                        f.properties.NAME_LONG || f.properties.NAME || f.properties.name || 'Unknown'
                    ));
                }
                if (states && states.features) {
                    this.states = states.features.map(f => buildFeature(
                        f,
                        f.properties.name || f.properties.NAME || 'State'
                    ));
                }
                this.loaded = true;
            });
            return this.loading;
        },

        countryAt(lat, lon) {
            return featureAt(this.countries, lat, lon);
        },

        subdivisionAt(lat, lon) {
            return featureAt(this.states, lat, lon);
        },

        locationFor(lat, lon) {
            if (!this.loaded) return '—';
            const country = this.countryAt(lat, lon);
            if (country) {
                // Extra granularity for the United States.
                if (/united states|usa|u\.s\./i.test(country)) {
                    const st = this.subdivisionAt(lat, lon);
                    return st ? country + ' — ' + st : country;
                }
                return country;
            }
            return oceanAt(lat, lon);
        }
    };

    // ---------- Helpers ----------
    function buildFeature(f, name) {
        const geom = f.geometry;
        const polys = !geom ? [] :
            geom.type === 'Polygon' ? [geom.coordinates] :
            geom.type === 'MultiPolygon' ? geom.coordinates : [];
        let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90;
        let cx = 0, cy = 0, cn = 0;
        for (const poly of polys) {
            for (const ring of poly) {
                for (const pt of ring) {
                    const lon = pt[0], lat = pt[1];
                    if (lon < minLon) minLon = lon;
                    if (lon > maxLon) maxLon = lon;
                    if (lat < minLat) minLat = lat;
                    if (lat > maxLat) maxLat = lat;
                    cx += lon; cy += lat; cn++;
                }
            }
        }
        return {
            name,
            polys,
            bbox: [minLon, minLat, maxLon, maxLat],
            centroid: cn ? [cy / cn, cx / cn] : [0, 0]
        };
    }

    function featureAt(features, lat, lon) {
        for (const f of features) {
            const b = f.bbox;
            if (lon < b[0] || lon > b[2] || lat < b[1] || lat > b[3]) continue;
            for (const poly of f.polys) {
                if (!pointInRing(lon, lat, poly[0])) continue;
                let inHole = false;
                for (let h = 1; h < poly.length; h++) {
                    if (pointInRing(lon, lat, poly[h])) { inHole = true; break; }
                }
                if (!inHole) return f.name;
            }
        }
        return null;
    }

    // Standard ray-casting point-in-polygon (longitude as x, latitude as y).
    function pointInRing(x, y, ring) {
        let inside = false;
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const xi = ring[i][0], yi = ring[i][1];
            const xj = ring[j][0], yj = ring[j][1];
            const intersect = ((yi > y) !== (yj > y)) &&
                (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }

    // Coarse ocean / sea labels when the point misses every country polygon.
    function oceanAt(lat, lon) {
        if (lat > 66) return 'Arctic Ocean';
        if (lat < -60) return 'Southern Ocean';
        // Mediterranean rough box.
        if (lon >= -6 && lon <= 36 && lat >= 30 && lat <= 46) return 'Mediterranean Sea';
        // Caribbean rough box.
        if (lon >= -88 && lon <= -60 && lat >= 9 && lat <= 23) return 'Caribbean Sea';
        // Gulf of Mexico.
        if (lon >= -98 && lon <= -81 && lat >= 18 && lat <= 31) return 'Gulf of Mexico';
        // Indian Ocean.
        if (lon >= 20 && lon <= 110 && lat <= 30) return 'Indian Ocean';
        // Atlantic.
        if (lon >= -70 && lon <= 20) return 'Atlantic Ocean';
        // Otherwise Pacific.
        return 'Pacific Ocean';
    }
})();
