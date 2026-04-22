# TLE Data

This folder holds per-catalog TLE files served from the same origin as the app.

- **Source:** CelesTrak `gp.php?GROUP=<name>&FORMAT=tle`
- **Refresh:** GitHub Actions (`.github/workflows/refresh-tles.yml`) runs every 6 hours and commits updates.
- **Why same-origin:** avoids CORS, ISP blocks, and third-party rate limiting.

Seed files (`stations.txt`, `science.txt`) are committed so the UI shows something on the very first deploy, before the scheduled workflow runs. After the first successful workflow run they are replaced with live catalogs.

To refresh manually: Actions tab → "Refresh TLE Data" → Run workflow.
