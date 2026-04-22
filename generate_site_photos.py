"""
generate_site_photos.py
-----------------------
Automatically generates a satellite-imagery PNG for each survey site and saves
it to the current folder.  Run this once (or after adding new data files), then
run make_track_map.py to rebuild the interactive HTML with the photos embedded.

Naming: photos are saved as <site_id>.png  (e.g. 121.png, 203.png)
        Forrester (no numeric ID) is saved as Forrester.png
The main map script matches these filenames automatically.

Tile source: Esri World Imagery (no API key required).
Dependencies: openpyxl, requests, Pillow  (all already installed)
"""

import math
import time
import re
import glob
import openpyxl
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from pathlib import Path
from collections import defaultdict

# ── same site-name logic as make_track_map.py ─────────────────────────────────

NAME_OVERRIDES = {
    '203': 'Ushagat/SW',
}

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

_site_labels = {}

def get_site_label(comment):
    c = re.sub(r'^[^A-Za-z0-9]+', '', comment.strip()).strip()
    if re.match(r'^FORRESTER\s+PASS', c, re.IGNORECASE):
        _site_labels.setdefault('FORRESTER', 'Forrester')
        return _site_labels['FORRESTER']
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
    if sid in NAME_OVERRIDES:
        name = NAME_OVERRIDES[sid]
    name = name.title()
    if not name:
        return None
    _site_labels.setdefault(sid, f"{name} ({sid})")
    return _site_labels[sid]

def site_filename(label):
    """Return the PNG filename for a site label."""
    m = re.search(r'\((\d+)\)', label)
    return f"{m.group(1)}.png" if m else f"{label}.png"

# ── load passes ───────────────────────────────────────────────────────────────

passes_by_site = defaultdict(list)

for filepath in sorted(glob.glob('*.xlsx')):
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
                label = get_site_label(comment)
                if label:
                    passes_by_site[label].append(list(current_x))
            current_x = []

print(f"Loaded {len(passes_by_site)} sites.")

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

def fetch_tile(z, x, y, retries=3):
    url = ESRI_URL.format(z=z, y=y, x=x)
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=10)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert('RGB')
        except Exception as e:
            if attempt == retries - 1:
                print(f"    Tile fetch failed ({z}/{x}/{y}): {e}")
                return Image.new('RGB', (TILE_SIZE, TILE_SIZE), (40, 40, 40))
            time.sleep(1)

def best_zoom(min_lat, max_lat, min_lon, max_lon, max_tiles=20):
    """Pick highest zoom that keeps tile count <= max_tiles."""
    for zoom in range(15, 7, -1):
        tx0, ty1 = deg_to_tile_float(max_lat, min_lon, zoom)
        tx1, ty0 = deg_to_tile_float(min_lat, max_lon, zoom)
        nx = int(tx1) - int(tx0) + 1
        ny = int(ty1) - int(ty0) + 1
        if nx * ny <= max_tiles:
            return zoom
    return 8

# ── track colours (matches make_track_map.py palette) ────────────────────────

COLORS_HEX = [
    '#e6194b','#3cb44b','#ffe119','#4363d8','#f58231',
    '#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4',
    '#469990','#dcbeff','#9a6324','#800000','#aaffc3',
]

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

COLORS_RGB = [hex_to_rgb(c) for c in COLORS_HEX]

# ── image generation ──────────────────────────────────────────────────────────

PAD = 0.25   # fractional padding around track extent

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

    # Tile index range
    tx0f, ty0f = deg_to_tile_float(max_lat, min_lon, zoom)
    tx1f, ty1f = deg_to_tile_float(min_lat, max_lon, zoom)
    tx0, ty0 = int(tx0f), int(ty0f)
    tx1, ty1 = int(tx1f), int(ty1f)
    nx = tx1 - tx0 + 1
    ny = ty1 - ty0 + 1

    # Fetch and stitch tiles
    canvas = Image.new('RGB', (nx * TILE_SIZE, ny * TILE_SIZE))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = fetch_tile(zoom, tx, ty)
            canvas.paste(tile, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))
            time.sleep(0.05)   # be polite to the tile server

    # Helper: geographic coord → pixel in canvas
    def to_px(lat, lon):
        txf, tyf = deg_to_tile_float(lat, lon, zoom)
        px = int((txf - tx0) * TILE_SIZE)
        py = int((tyf - ty0) * TILE_SIZE)
        return px, py

    draw = ImageDraw.Draw(canvas)

    # Draw each pass
    for pi, pass_coords in enumerate(all_passes):
        color = COLORS_RGB[pi % len(COLORS_RGB)]
        pixels = [to_px(lat, lon) for lat, lon in pass_coords]

        if len(pixels) < 2:
            continue

        # Line
        draw.line(pixels, fill=color, width=3)

        # Start dot (filled circle)
        sx, sy = pixels[0]
        r = 5
        draw.ellipse([sx-r, sy-r, sx+r, sy+r], fill=color, outline='white', width=1)

        # End dot (hollow circle)
        ex, ey = pixels[-1]
        draw.ellipse([ex-r, ey-r, ex+r, ey+r], fill='white', outline=color, width=2)

        # Pass number near start
        draw.text((sx + r + 2, sy - 7), f"P{pi+1}", fill=color)

    # Crop to exact geographic bounds
    px_min, py_min = to_px(max_lat, min_lon)
    px_max, py_max = to_px(min_lat, max_lon)
    px_min = max(0, px_min)
    py_min = max(0, py_min)
    px_max = min(canvas.width,  px_max)
    py_max = min(canvas.height, py_max)
    canvas = canvas.crop((px_min, py_min, px_max, py_max))

    # Site label banner at top
    banner_h = 24
    banner = Image.new('RGB', (canvas.width, banner_h), (30, 30, 30))
    bdraw  = ImageDraw.Draw(banner)
    bdraw.text((6, 4), label, fill='white')
    final  = Image.new('RGB', (canvas.width, canvas.height + banner_h))
    final.paste(banner, (0, 0))
    final.paste(canvas, (0, banner_h))

    final.save(output_path)

# ── main loop ─────────────────────────────────────────────────────────────────

sites = sorted(passes_by_site.keys())
print(f"Generating photos for {len(sites)} sites...\n")

for label in sites:
    fname = site_filename(label)
    if Path(fname).exists():
        print(f"  Skipping {fname} (already exists — delete to regenerate)")
        continue
    print(f"  {label} -> {fname} ...", end=' ', flush=True)
    try:
        generate_photo(label, passes_by_site[label], fname)
        print("done")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone. Run make_track_map.py to rebuild the HTML with photos embedded.")
