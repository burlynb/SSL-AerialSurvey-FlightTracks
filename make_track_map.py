"""
make_track_map.py
-----------------
Generates index.html with interactive satellite map of SSL aerial survey flight
tracks for 2021 (xlsx) and 2024 (csv).  Run from the directory containing the
data files (xlsx and csv) — outputs index.html there.

Photos are loaded from:
  photos/2021/<site label>.png
  photos/2024/<site label>.png
relative to the repo root (where index.html lives).

Year toggle buttons (2021 / Both / 2024) let the user show/hide layers.
"""

import csv
import openpyxl
import folium
import re
import math
import glob
from collections import defaultdict
from pathlib import Path

# ── NMEA coordinate conversion ─────────────────────────────────────────────────

def nmea_to_dd(val, hemisphere):
    """Convert NMEA DDDMM.MMMMM to decimal degrees (signed)."""
    v = float(val)
    deg = int(v / 100)
    minutes = v - deg * 100
    dd = deg + minutes / 60.0
    if hemisphere.upper() in ('S', 'W'):
        dd = -dd
    return dd

# ── bearing + arrow helpers ────────────────────────────────────────────────────

def compass_bearing(lat1, lon1, lat2, lon2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def stable_bearing(coords, pct_from, pct_to):
    n = len(coords)
    i = max(0, int(n * pct_from))
    j = min(n - 1, int(n * pct_to))
    if i == j:
        j = min(n - 1, i + 1)
    return compass_bearing(*coords[i], *coords[j])

def arrowhead_html(bearing_deg, color, size=20):
    h = size
    w = int(size * 0.75)
    css_rot = bearing_deg - 90
    shadow = "drop-shadow(0px 0px 3px rgba(0,0,0,1))"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'style="transform:rotate({css_rot:.1f}deg);transform-origin:center center;'
        f'filter:{shadow};overflow:visible;">'
        f'<polygon points="0,0 {w},{h//2} 0,{h}" fill="{color}"/>'
        f'</svg>'
    )

def place_arrowhead(location, bearing_deg, color, group, tooltip='', size=20):
    h, w = size, int(size * 0.75)
    folium.Marker(
        location=location, tooltip=tooltip,
        icon=folium.DivIcon(
            html=arrowhead_html(bearing_deg, color, size),
            icon_size=(w, h), icon_anchor=(w // 2, h // 2),
        )
    ).add_to(group)

def add_arrows(coords, color, group, tip=''):
    n = len(coords)
    if n < 2:
        return
    place_arrowhead(coords[0],    stable_bearing(coords, 0.0,  0.15), color, group, f"START {tip}")
    place_arrowhead(coords[n//2], stable_bearing(coords, 0.40, 0.80), color, group, tip)
    place_arrowhead(coords[-1],   stable_bearing(coords, 0.85, 1.0),  color, group, f"END {tip}")

# ── 2021 comment parsing (xlsx) ────────────────────────────────────────────────

SKIP_PREFIXES = (
    'TAKE OFF', 'TAKEOFF', 'TEST FIRE', 'LAND', 'KL ', 'ALTITUDE',
    'FRAME CHECK', 'LOW CLOUD', 'SKIPPING', 'SAW GROUP', 'CHECK FRAME',
    'FUEL', 'CLOUDS', 'LAST PASS', 'OBSERVERS', 'PAKT', 'PASI LANDING',
    'ADD ', 'CHECK FOR', 'PREVIOUS', 'ACCIDENTAL', 'COUNTERS', 'ALL ANIMALS',
    'LOOK OUT', 'DISTURBANCE', 'START OF', 'WEST SIDE', 'ANIMALS ON',
    'PASS 1 ', 'PASS 2 ', 'PASS 3 ', 'PASS 4 ', 'PASS 5 ', 'PASS 6 ',
    'PASS 7 ', 'PASS 8 ', 'PASS 9 ', 'PASS 183', 'PASS 2\n',
    'NEW SITE', '1529', 'HIT OUR', '10 JUMPER', '2 JUMPER',
)

def is_operational(comment):
    return comment.upper().strip().startswith(SKIP_PREFIXES)

NAME_OVERRIDES_2021 = {'203': 'Ushagat/SW'}

_labels_2021 = {}   # numeric site_id string -> display label

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
    name = name.title()
    if not name:
        return None
    if sid in NAME_OVERRIDES_2021:
        name = NAME_OVERRIDES_2021[sid]
    _labels_2021.setdefault(sid, f"{name} ({sid})")
    return _labels_2021[sid]

# ── 2024 site name parsing (csv) ───────────────────────────────────────────────

_labels_2024 = {}   # parent numeric id string -> display label

def get_site_label_2024(site_id_raw, site_name_raw):
    """Return label like 'Shaw (233)' from raw CSV site_id and site_name."""
    m = re.match(r'(\d+)', str(site_id_raw).strip())
    parent_id = m.group(1) if m else str(site_id_raw).strip()
    if parent_id in _labels_2024:
        return _labels_2024[parent_id]
    name = str(site_name_raw).strip()
    # Strip trailing " X to Y" artifacts (e.g. "NAGAI ROCKS/B to A")
    name = re.sub(r'\s+[A-Za-z]\s+to\s+[A-Za-z]\s*$', '', name, flags=re.IGNORECASE).strip()
    # Strip trailing single-letter sub-site suffix: "/B", "/C" — but keep "/SW", "/NW"
    name = re.sub(r'/[A-Za-z]\s*$', '', name).strip().strip('/')
    name = name.title()
    label = f"{name} ({parent_id})"
    _labels_2024[parent_id] = label
    return label

# ── load 2021 passes (xlsx) ────────────────────────────────────────────────────

passes_by_site_2021 = defaultdict(list)   # label -> [{date, comment, coords}]

xlsx_files = sorted(glob.glob('flightlogs/2021/*.xlsx'))
for filepath in xlsx_files:
    date_str = Path(filepath).stem[:8]
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    current_x = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        type_, lat, lon, comment = row[0], row[4], row[5], row[30]
        if type_ == 'X' and lat and lon:
            current_x.append((float(lat), float(lon)))
        elif type_ == 'C' and comment:
            comment = str(comment).strip()
            if current_x and not is_operational(comment):
                label = get_site_label_2021(comment)
                if label:
                    passes_by_site_2021[label].append({
                        'date': date_str, 'comment': comment, 'coords': list(current_x),
                    })
            current_x = []

print(f"2021: {sum(len(v) for v in passes_by_site_2021.values())} passes across "
      f"{len(passes_by_site_2021)} sites from {len(xlsx_files)} xlsx files.")

# ── load 2024 passes (csv) ─────────────────────────────────────────────────────

passes_by_site_2024 = defaultdict(list)   # label -> [{date, comment, coords}]

csv_files = sorted(glob.glob('flightlogs/2024/*.csv'))
for filepath in csv_files:
    m = re.search(r'(\d{4}-\d{2}-\d{2})', filepath)
    date_str = m.group(1).replace('-', '') if m else 'unknown'

    # Within each file, group coords by (raw_site_id, pass_num)
    file_passes  = defaultdict(list)    # (raw_site_id, pass_num) -> [(lat, lon), ...]
    file_names   = {}                   # raw_site_id -> first-seen site_name

    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)   # skip header
        for row in reader:
            if len(row) < 31 or row[0] != '$X':
                continue
            site_name = row[29].strip()
            site_id   = row[27].strip()
            pass_num  = row[30].strip()
            if not (site_name and site_id):
                continue
            lat_val, lat_ns = row[6], row[7]
            lon_val, lon_ew = row[8], row[9]
            if not (lat_val and lon_val and lat_ns and lon_ew):
                continue
            try:
                lat = nmea_to_dd(lat_val, lat_ns)
                lon = nmea_to_dd(lon_val, lon_ew)
            except (ValueError, ZeroDivisionError):
                continue
            key = (site_id, pass_num)
            file_passes[key].append((lat, lon))
            file_names.setdefault(site_id, site_name)

    for (site_id, pass_num), coords in file_passes.items():
        if not coords:
            continue
        site_name = file_names.get(site_id, site_id)
        label = get_site_label_2024(site_id, site_name)
        passes_by_site_2024[label].append({
            'date': date_str,
            'comment': f"{site_name} pass {pass_num}",
            'coords': coords,
        })

print(f"2024: {sum(len(v) for v in passes_by_site_2024.values())} passes across "
      f"{len(passes_by_site_2024)} sites from {len(csv_files)} csv files.")

# ── match site photos (relative paths for GitHub Pages) ───────────────────────

def find_photo(label, photo_dir):
    """Return relative path string if photo exists, else None."""
    safe = re.sub(r'[\\/:*?"<>|]', '_', label)
    for ext in ('png', 'jpg', 'jpeg'):
        p = Path(photo_dir) / f"{safe}.{ext}"
        if p.exists():
            return str(p).replace('\\', '/')
    return None

site_photos_2021 = {}
for label in passes_by_site_2021:
    path = find_photo(label, 'photos/2021')
    if path:
        site_photos_2021[label] = path

site_photos_2024 = {}
for label in passes_by_site_2024:
    path = find_photo(label, 'photos/2024')
    if path:
        site_photos_2024[label] = path

print(f"Photos found: {len(site_photos_2021)} for 2021, {len(site_photos_2024)} for 2024.")

# ── colour palette ─────────────────────────────────────────────────────────────

COLORS = [
    '#e6194b','#3cb44b','#ffe119','#4363d8','#f58231',
    '#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4',
    '#469990','#dcbeff','#9a6324','#800000','#aaffc3',
    '#808000','#ffd8b1','#000075','#a9a9a9','#e6beff',
]
LIGHT_COLORS = {'#ffe119','#bfef45','#42d4f4','#fabed4','#aaffc3','#ffd8b1','#e6beff'}

# Assign colors by site label so the same site looks the same across years
all_site_labels = sorted(set(passes_by_site_2021) | set(passes_by_site_2024))
color_map = {label: COLORS[i % len(COLORS)] for i, label in enumerate(all_site_labels)}

# ── build map ──────────────────────────────────────────────────────────────────

all_coords = [
    c
    for sites in (passes_by_site_2021, passes_by_site_2024)
    for site_passes in sites.values()
    for p in site_passes
    for c in p['coords']
]
min_lat = min(c[0] for c in all_coords)
max_lat = max(c[0] for c in all_coords)
min_lon = min(c[1] for c in all_coords)
max_lon = max(c[1] for c in all_coords)
center  = ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)

m = folium.Map(location=center, zoom_start=6, tiles=None)
m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri World Imagery', name='Satellite', overlay=False, control=True,
).add_to(m)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    attr='Esri Labels', name='Labels', overlay=True, control=True, opacity=0.7,
).add_to(m)

def add_site_layers(passes_by_site, site_photos, year_prefix):
    """Add one FeatureGroup per site, prefixed with year."""
    for site in sorted(passes_by_site):
        color      = color_map[site]
        text_color = '#000' if color in LIGHT_COLORS else '#fff'
        group_name = f"{year_prefix} | {site}"
        group      = folium.FeatureGroup(name=group_name, show=True)
        site_passes = passes_by_site[site]

        for pass_num, p in enumerate(site_passes, 1):
            coords = p['coords']
            badge  = f"P{pass_num}"
            tip    = f"{badge} ({p['date']}) — {p['comment']}"

            folium.PolyLine(
                locations=coords, color=color, weight=3, opacity=0.9, tooltip=tip,
            ).add_to(group)

            add_arrows(coords, color, group, tip)

            q = max(0, len(coords) // 4)
            folium.Marker(
                location=coords[q], tooltip=tip,
                icon=folium.DivIcon(
                    html=(f'<div style="background:{color};color:{text_color};'
                          f'border-radius:50%;width:20px;height:20px;line-height:20px;'
                          f'text-align:center;font-size:10px;font-weight:bold;'
                          f'font-family:sans-serif;border:1.5px solid rgba(0,0,0,0.4);'
                          f'box-shadow:1px 1px 3px rgba(0,0,0,0.6);">{badge}</div>'),
                    icon_size=(20, 20), icon_anchor=(10, 10),
                )
            ).add_to(group)

        if site in site_photos:
            all_site_coords = [c for p in site_passes for c in p['coords']]
            centroid = (
                sum(c[0] for c in all_site_coords) / len(all_site_coords),
                sum(c[1] for c in all_site_coords) / len(all_site_coords),
            )
            site_name_short = re.sub(r'\s*\(\d+\)\s*$', '', site).strip()
            popup_html = (
                f'<div style="text-align:center;font-family:sans-serif;padding:4px;">'
                f'<b style="font-size:13px;">{site} ({year_prefix})</b><br>'
                f'<img src="{site_photos[site]}" '
                f'style="max-width:300px;max-height:220px;margin-top:6px;border-radius:4px;">'
                f'</div>'
            )
            folium.Marker(
                location=centroid,
                tooltip=f"{site} ({year_prefix}) — click for photo",
                popup=folium.Popup(popup_html, max_width=320),
                icon=folium.DivIcon(
                    html=(f'<div style="background:{color};color:{text_color};'
                          f'border-radius:4px;padding:2px 6px;'
                          f'font-size:10px;font-weight:bold;font-family:sans-serif;'
                          f'border:1.5px solid rgba(0,0,0,0.4);'
                          f'box-shadow:1px 1px 3px rgba(0,0,0,0.5);white-space:nowrap;">'
                          f'&#128247; {site_name_short}</div>'),
                    icon_size=(len(site_name_short) * 7 + 30, 20),
                    icon_anchor=((len(site_name_short) * 7 + 30) // 2, 10),
                )
            ).add_to(group)

        group.add_to(m)

add_site_layers(passes_by_site_2021, site_photos_2021, '2021')
add_site_layers(passes_by_site_2024, site_photos_2024, '2024')

folium.LayerControl(collapsed=True).add_to(m)

# ── year-toggle buttons ────────────────────────────────────────────────────────

toggle_html = """
<style>
  #year-toggle button {
    padding: 8px 20px; border: none; cursor: pointer;
    font-family: sans-serif; font-size: 13px; font-weight: bold;
    background: #eee; color: #333; transition: background .15s, color .15s;
  }
  #year-toggle button.active { background: #4363d8; color: #fff; }

  /* Search box injected into the layer control panel */
  #layer-search {
    display: block; width: calc(100% - 16px); margin: 6px 8px 4px;
    padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px;
    font-size: 12px; font-family: sans-serif; box-sizing: border-box;
  }
  #layer-search:focus { outline: none; border-color: #4363d8; }
  .layer-hidden { display: none !important; }
</style>

<div id="year-toggle" style="
  position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
  z-index: 9999; display: flex; border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.35); overflow: hidden;
">
  <button data-yr="2021" onclick="setYear('2021')">2021</button>
  <button data-yr="both" onclick="setYear('both')" class="active">Both</button>
  <button data-yr="2024" onclick="setYear('2024')">2024</button>
</div>

<script>
// ── year toggle ───────────────────────────────────────────────────────────────
function setYear(yr) {
  document.querySelectorAll('#year-toggle button').forEach(function(b) {
    b.classList.toggle('active', b.getAttribute('data-yr') === yr);
  });
  document.querySelectorAll(
    '.leaflet-control-layers-overlays label'
  ).forEach(function(lbl) {
    var txt = lbl.innerText.trim();
    var inp = lbl.querySelector('input[type="checkbox"]');
    if (!inp) return;
    var is2021 = txt.startsWith('2021 |');
    var is2024 = txt.startsWith('2024 |');
    if (!is2021 && !is2024) return;
    var show = yr === 'both'
            || (yr === '2021' && is2021)
            || (yr === '2024' && is2024);
    if (inp.checked !== show) inp.click();
  });
}

// ── search box ────────────────────────────────────────────────────────────────
// Inject a search input at the top of the layer control panel once it exists.
function injectSearch() {
  var overlays = document.querySelector('.leaflet-control-layers-overlays');
  if (!overlays || document.getElementById('layer-search')) return;

  var input = document.createElement('input');
  input.id = 'layer-search';
  input.type = 'text';
  input.placeholder = 'Search sites…';

  // Insert before the overlays list
  overlays.parentNode.insertBefore(input, overlays);

  input.addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    document.querySelectorAll(
      '.leaflet-control-layers-overlays label'
    ).forEach(function(lbl) {
      var name = lbl.innerText.trim().toLowerCase();
      // Strip year prefix for matching so "shaw" finds both "2021 | Shaw" and "2024 | Shaw"
      var stripped = name.replace(/^\\d{4} \\| /, '');
      var match = !q || stripped.includes(q) || name.includes(q);
      lbl.classList.toggle('layer-hidden', !match);
    });
  });
}

// The layer control panel is only added to the DOM when the user expands it.
// Watch for that using a MutationObserver so the search box is always ready.
var _searchObserver = new MutationObserver(function() {
  if (document.querySelector('.leaflet-control-layers-overlays')) {
    injectSearch();
  }
});
window.addEventListener('load', function() {
  _searchObserver.observe(document.body, { childList: true, subtree: true });
  // Also try immediately in case it's already expanded.
  injectSearch();
});
</script>
"""

m.get_root().html.add_child(folium.Element(toggle_html))

# ── write output ───────────────────────────────────────────────────────────────

outfile = 'index.html'
m.save(outfile)
print(f"\nSaved: {outfile}")
print(f"\n{'Site':<45} {'2021':>4}  {'2024':>4}  {'Photo 2021':>10}  {'Photo 2024':>10}")
print('-' * 80)
all_labels = sorted(set(passes_by_site_2021) | set(passes_by_site_2024))
for site in all_labels:
    n21  = len(passes_by_site_2021.get(site, []))
    n24  = len(passes_by_site_2024.get(site, []))
    p21  = 'yes' if site in site_photos_2021 else ''
    p24  = 'yes' if site in site_photos_2024 else ''
    print(f"{site:<45} {n21 or '':>4}  {n24 or '':>4}  {p21:>10}  {p24:>10}")
