"""
generate_site_photos.py
-----------------------
Generates satellite-imagery PNG thumbnails for each survey site.

  2021 sites (xlsx)  -> photos/2021/<site label>.png
  2024 sites (csv)   -> photos/2024/<site label>.png

Run from the directory containing the data files (same dir as make_track_map.py).
Safe to rerun — skips files that already exist.

Tile source: Esri World Imagery (no API key required).
Dependencies: openpyxl, requests, Pillow
"""

import csv
import math
import time
import re
import glob
import openpyxl
import requests
from PIL import Image, ImageDraw
from io import BytesIO
from pathlib import Path
from collections import defaultdict

# ── 2021 site-name logic ───────────────────────────────────────────────────────

NAME_OVERRIDES_2021 = {'203': 'Ushagat/SW'}

SKIP_PREFIXES = (
    'TAKE OFF', 'TAKEOFF', 'TEST FIRE', 'LAND', 'KL ', 'ALTITUDE',
    'FRAME CHECK', 'LOW CLOUD', 'SKIPPING', 'SAW GROUP', 'CHECK FRAME',
    'FUEL', 'CLOUDS', 'LAST PASS', 'OBSERVERS', 'PAKT', 'PASI LANDING',
    'ADD ', 'CHECK FOR', 'PREVIOUS', 'ACCIDENTAL', 'COUNTERS', 'ALL ANIMALS',
    'LOOK OUT', 'DISTURBANCE', 'START OF', 'WEST SIDE', 'ANIMALS ON',
    'PASS 1 ', 'PASS 2 ', 'PASS 3 ', 'PASS 4 ', 'PASS 5 ', 'PASS 6 ',
    'PASS 7 ', 'PASS 8 ', 'PASS 9 ', 'PASS 183', 'NEW SITE',
    '1529', 'HIT OUR', '10 JUMPER', '2 JUMPER',
)

_labels_2021 = {}

def get_site_label_2021(comment):
    c = re.sub(r'^[^A-Za-z0-9]+', '', comment.strip()).strip()
    if re.match(r'^FORRESTER\s+PASS', c, re.IGNORECASE):
        _labels_2021.setdefault('FORRESTER', 'Forrester')
        return _labels_2021['FORRESTER']
    m = re.match(
        r'^(?:SSL?)?(\d+)[A-Z]?\s+(.+?)'
        r'(?:\s+(?:PASS|ABORTED|ONE\s+PASS|NO\s+ANIMALS|OBSV|VISUAL|PHOTO|PASS\s+ONE)'
        r'|\s*[-–]\s*|\s*$)',
        c, re.IGNORECASE
    )
    if not m:
        return None
    sid  = m.group(1)
    name = m.group(2).strip()
    name = re.sub(r'\s+[A-Z]\s+(?:TO|AND)\s+[A-Z]\s*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+[A-Z]\s*$', '', name).strip()
    name = re.sub(r'\s+\d+\s*$', '', name).strip()
    if sid in NAME_OVERRIDES_2021:
        name = NAME_OVERRIDES_2021[sid]
    name = name.title()
    if not name:
        return None
    _labels_2021.setdefault(sid, f"{name} ({sid})")
    return _labels_2021[sid]

# ── 2024 site-name logic ───────────────────────────────────────────────────────

def nmea_to_dd(val, hemisphere):
    v = float(val)
    deg = int(v / 100)
    dd = deg + (v - deg * 100) / 60.0
    if hemisphere.upper() in ('S', 'W'):
        dd = -dd
    return dd

_labels_2024 = {}

def get_site_label_2024(site_id_raw, site_name_raw):
    m = re.match(r'(\d+)', str(site_id_raw).strip())
    parent_id = m.group(1) if m else str(site_id_raw).strip()
    if parent_id in _labels_2024:
        return _labels_2024[parent_id]
    name = str(site_name_raw).strip()
    name = re.sub(r'\s+[A-Za-z]\s+to\s+[A-Za-z]\s*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'/[A-Za-z]\s*$', '', name).strip().strip('/')
    name = name.title()
    _labels_2024[parent_id] = f"{name} ({parent_id})"
    return _labels_2024[parent_id]

# ── load passes ────────────────────────────────────────────────────────────────

passes_by_site_2021 = defaultdict(list)   # label -> [[(lat, lon), ...], ...]

for filepath in sorted([f for f in glob.glob('flightlogs/**/2021/*.xlsx', recursive=True) if 'LOGSummary' not in f and 'ASSLAP' not in f]):
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    current_x = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        type_, lat, lon, comment = row[0], row[4], row[5], row[30]
        if type_ == 'X' and lat and lon:
            current_x.append((float(lat), float(lon)))
        elif type_ == 'C' and comment:
            comment = str(comment).strip()
            cu = comment.upper()
            if current_x and not cu.startswith(SKIP_PREFIXES):
                label = get_site_label_2021(comment)
                if label:
                    passes_by_site_2021[label].append(list(current_x))
            current_x = []

passes_by_site_2024 = defaultdict(list)

for filepath in sorted(glob.glob('flightlogs/**/2024/*.csv', recursive=True)):
    file_passes = defaultdict(list)
    file_names  = {}
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 31 or row[0] != '$X':
                continue
            site_name = row[29].strip()
            site_id   = row[27].strip()
            pass_num  = row[30].strip()
            if not (site_name and site_id):
                continue
            try:
                lat = nmea_to_dd(row[6], row[7])
                lon = nmea_to_dd(row[8], row[9])
            except (ValueError, ZeroDivisionError):
                continue
            file_passes[(site_id, pass_num)].append((lat, lon))
            file_names.setdefault(site_id, site_name)
    for (site_id, pass_num), coords in file_passes.items():
        if coords:
            label = get_site_label_2024(site_id, file_names.get(site_id, site_id))
            passes_by_site_2024[label].append(coords)

print(f"Loaded {len(passes_by_site_2021)} 2021 sites, {len(passes_by_site_2024)} 2024 sites.")

# ── tile utilities ─────────────────────────────────────────────────────────────

TILE_SIZE = 256
ESRI_URL  = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
SESSION   = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; site-photo-generator)'})

def deg_to_tile_float(lat, lon, zoom):
    lat_r = math.radians(lat)
    n = 2.0 ** zoom
    tx = (lon + 180.0) / 360.0 * n
    ty = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return tx, ty

def fetch_tile(z, x, y, retries=3, timeout=(5, 10)):
    url = ESRI_URL.format(z=z, y=y, x=x)
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert('RGB')
        except Exception as e:
            if attempt == retries - 1:
                print(f"    Tile fetch failed ({z}/{x}/{y}): {e}")
                return Image.new('RGB', (TILE_SIZE, TILE_SIZE), (40, 40, 40))
            time.sleep(1)

def best_zoom(min_lat, max_lat, min_lon, max_lon, max_tiles=20):
    for zoom in range(15, 7, -1):
        tx0f, ty1f = deg_to_tile_float(max_lat, min_lon, zoom)
        tx1f, ty0f = deg_to_tile_float(min_lat, max_lon, zoom)
        nx = int(tx1f) - int(tx0f) + 1
        ny = int(ty1f) - int(ty0f) + 1
        if nx * ny <= max_tiles:
            return zoom
    return 8

# ── track colour palette ───────────────────────────────────────────────────────

COLORS_HEX = [
    '#e6194b','#3cb44b','#ffe119','#4363d8','#f58231',
    '#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4',
    '#469990','#dcbeff','#9a6324','#800000','#aaffc3',
]

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

COLORS_RGB = [hex_to_rgb(c) for c in COLORS_HEX]

# ── image generation ───────────────────────────────────────────────────────────

PAD = 0.25

def generate_photo(label, all_passes, output_path):
    all_coords = [c for p in all_passes for c in p]
    lats = [c[0] for c in all_coords]
    lons = [c[1] for c in all_coords]

    lat_span = max(lats) - min(lats) or 0.002
    lon_span = max(lons) - min(lons) or 0.003

    min_lat = min(lats) - lat_span * PAD
    max_lat = max(lats) + lat_span * PAD
    min_lon = min(lons) - lon_span * PAD
    max_lon = max(lons) + lon_span * PAD

    zoom = best_zoom(min_lat, max_lat, min_lon, max_lon)

    tx0f, ty0f = deg_to_tile_float(max_lat, min_lon, zoom)
    tx1f, ty1f = deg_to_tile_float(min_lat, max_lon, zoom)
    tx0, ty0 = int(tx0f), int(ty0f)
    tx1, ty1 = int(tx1f), int(ty1f)
    nx = tx1 - tx0 + 1
    ny = ty1 - ty0 + 1

    canvas = Image.new('RGB', (nx * TILE_SIZE, ny * TILE_SIZE))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = fetch_tile(zoom, tx, ty)
            canvas.paste(tile, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))
            time.sleep(0.05)

    def to_px(lat, lon):
        txf, tyf = deg_to_tile_float(lat, lon, zoom)
        return int((txf - tx0) * TILE_SIZE), int((tyf - ty0) * TILE_SIZE)

    draw = ImageDraw.Draw(canvas)
    for pi, pass_coords in enumerate(all_passes):
        color = COLORS_RGB[pi % len(COLORS_RGB)]
        pixels = [to_px(lat, lon) for lat, lon in pass_coords]
        if len(pixels) < 2:
            continue
        draw.line(pixels, fill=color, width=3)
        sx, sy = pixels[0]
        r = 5
        draw.ellipse([sx-r, sy-r, sx+r, sy+r], fill=color, outline='white', width=1)
        ex, ey = pixels[-1]
        draw.ellipse([ex-r, ey-r, ex+r, ey+r], fill='white', outline=color, width=2)
        draw.text((sx + r + 2, sy - 7), f"P{pi+1}", fill=color)

    px_min, py_min = to_px(max_lat, min_lon)
    px_max, py_max = to_px(min_lat, max_lon)
    px_min = max(0, px_min); py_min = max(0, py_min)
    px_max = min(canvas.width, px_max); py_max = min(canvas.height, py_max)
    canvas = canvas.crop((px_min, py_min, px_max, py_max))

    banner_h = 24
    banner = Image.new('RGB', (canvas.width, banner_h), (30, 30, 30))
    ImageDraw.Draw(banner).text((6, 4), label, fill='white')
    final = Image.new('RGB', (canvas.width, canvas.height + banner_h))
    final.paste(banner, (0, 0))
    final.paste(canvas, (0, banner_h))
    final.save(output_path)

def safe_filename(label):
    return re.sub(r'[\\/:*?"<>|]', '_', label) + '.png'

# ── main loop ──────────────────────────────────────────────────────────────────

Path('photos/2021').mkdir(parents=True, exist_ok=True)
Path('photos/2024').mkdir(parents=True, exist_ok=True)

for year, passes_by_site, photo_dir in [
    ('2021', passes_by_site_2021, Path('photos/2021')),
    ('2024', passes_by_site_2024, Path('photos/2024')),
]:
    sites = sorted(passes_by_site.keys())
    print(f"\nGenerating {year} photos for {len(sites)} sites...")
    for label in sites:
        fname = safe_filename(label)
        outpath = photo_dir / fname
        if outpath.exists():
            print(f"  Skipping {outpath} (already exists)")
            continue
        print(f"  {label} -> {outpath} ...", end=' ', flush=True)
        try:
            generate_photo(label, passes_by_site[label], outpath)
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")

print("\nDone. Run make_track_map.py to rebuild the HTML.")
