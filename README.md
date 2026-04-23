# SSL Aerial Survey Flight Tracks

**[Open the Interactive Map](https://burlynb.github.io/SSL-AerialSurvey-FlightTracks/)**

Interactive visualization of Steller sea lion (*Eumetopias jubatus*) aerial survey flight tracks from NMFS/AFSC camera-triggered survey flights in Alaska.

---

## What this shows

Each survey flight captures GPS-tagged camera trigger points as the aircraft transects haul-out sites. This map renders those triggers as flight track lines overlaid on satellite imagery, grouped by survey site and year.

- **Lines** show the camera pass track for each site visit
- **Arrows** show flight direction (start, mid, end of each pass)
- **Numbered badges** (P1, P2 …) identify individual passes at multi-pass sites
- **Camera icons** open a satellite thumbnail of the site when clicked
- **Year toggle** (top center) switches between 2021, 2024, or both years simultaneously

Survey years currently included: **2021**, **2024**

---

## Repository contents

| File / Folder | Description |
|---|---|
| `index.html` | The interactive map (hosted via GitHub Pages) |
| `make_track_map.py` | Generates `index.html` from flight log data |
| `generate_site_photos.py` | Fetches satellite tile thumbnails for each site |
| `generate_kml.py` | Generates ForeFlight-compatible KML files |
| `2021_flighttracks.kml` | 2021 flight tracks for ForeFlight import |
| `2024_flighttracks.kml` | 2024 flight tracks for ForeFlight import |
| `photos/2021/` | Satellite thumbnail images for 2021 sites |
| `photos/2024/` | Satellite thumbnail images for 2024 sites |
| `flightlogs/` | Raw survey log files — **gitignored, not shared publicly** |

---

## Using in ForeFlight

The KML files can be imported as a map layer in ForeFlight for use during survey flights:

1. Transfer `2021_flighttracks.kml` or `2024_flighttracks.kml` to your iPad (AirDrop, email, or Files app)
2. Tap the file → **Open in ForeFlight**
3. The tracks appear as a toggleable layer on the moving map

---

## Regenerating the map

Run all scripts from the repo root. Raw flight logs must be present in `flightlogs/2021/` (`.xlsx`) and `flightlogs/2024/` (`.csv`).

```bash
# 1. Generate satellite thumbnails (skips existing — safe to rerun)
python generate_site_photos.py

# 2. Rebuild the interactive HTML map
python make_track_map.py

# 3. Rebuild the ForeFlight KML files
python generate_kml.py
```

Dependencies: `openpyxl`, `folium`, `requests`, `Pillow`

```bash
pip install openpyxl folium requests Pillow
```
