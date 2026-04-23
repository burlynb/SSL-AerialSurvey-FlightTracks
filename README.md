# SSL Aerial Survey Flight Tracks

**[Open the Interactive Map](https://burlynb.github.io/SSL-AerialSurvey-FlightTracks/)**

Interactive visualization of Steller sea lion (*Eumetopias jubatus*) aerial survey flight tracks from NMFS/AFSC camera-triggered survey flights in Alaska.

---

## What this shows

Each survey flight captures GPS-tagged camera trigger points as the aircraft transects haul-out sites. This map renders those triggers as flight track lines overlaid on satellite imagery, grouped by survey region, year, and site.

- **Region toggle** (top center) switches between Gulf of Alaska and Aleutian Islands
- **Year toggle** switches between individual survey years or both years simultaneously
- **Lines** show the camera pass track for each site visit
- **Arrows** show flight direction (start, mid, end of each pass)
- **Numbered badges** (P1, P2 …) identify individual passes at multi-pass sites
- **Camera icons** open a satellite thumbnail of the site when clicked, with observer pass notes below the image
- **Zoom in** past zoom level 9 to see full detail; zoom out for a simplified dot overview

Survey data currently included:

| Region | Years |
|---|---|
| Gulf of Alaska | 2021, 2024 |
| Aleutian Islands | 2022, 2023 |

---

## Repository contents

| File / Folder | Description |
|---|---|
| `index.html` | The interactive map (hosted via GitHub Pages) |
| `make_track_map.py` | Generates `index.html` from flight log data |
| `generate_site_photos.py` | Fetches satellite tile thumbnails for each site |
| `generate_kml.py` | Generates ForeFlight-compatible KML files |
| `2021_flighttracks.kml` | GOA 2021 flight tracks for ForeFlight |
| `2024_flighttracks.kml` | GOA 2024 flight tracks for ForeFlight |
| `2022_flighttracks.kml` | ALI 2022 flight tracks for ForeFlight |
| `2023_flighttracks.kml` | ALI 2023 flight tracks for ForeFlight |
| `photos/2021/` | Satellite thumbnails for GOA 2021 sites |
| `photos/2024/` | Satellite thumbnails for GOA 2024 sites |
| `photos/2022/` | Satellite thumbnails for ALI 2022 sites |
| `photos/2023/` | Satellite thumbnails for ALI 2023 sites |
| `flightlogs/` | Raw survey log files — **gitignored, not shared publicly** |

---

## Using in ForeFlight

The KML files can be imported as map layers in ForeFlight for use during survey flights:

1. Transfer the desired `.kml` file to your iPad (AirDrop, email, or Files app)
2. Tap the file → **Open in ForeFlight**
3. The tracks appear as a toggleable layer on the moving map

---

## Regenerating the map

Run all scripts from the repo root. Raw flight logs must be present in the `flightlogs/` directory (gitignored).

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
