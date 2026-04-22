import openpyxl
import folium
import re
import math
import glob
from collections import defaultdict
from pathlib import Path

# ── helpers ────────────────────────────────────────────────────────────────────

def compass_bearing(lat1, lon1, lat2, lon2):
    """True bearing (degrees, 0=N) from point 1 to point 2."""
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def stable_bearing(coords, pct_from, pct_to):
    """Bearing over a span of the track to avoid GPS jitter."""
    n = len(coords)
    i = max(0, int(n * pct_from))
    j = min(n - 1, int(n * pct_to))
    if i == j:
        j = min(n - 1, i + 1)
    return compass_bearing(*coords[i], *coords[j])

def arrowhead_html(bearing_deg, color, size=20):
    """
    Plain triangular arrowhead as an inline SVG.
    The triangle naturally points right; css_rot corrects to compass bearing.
    size = height in pixels; width = 75% of that.
    """
    h = size
    w = int(size * 0.75)
    css_rot = bearing_deg - 90
    shadow  = "drop-shadow(0px 0px 3px rgba(0,0,0,1))"
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
    """Three arrowheads per pass: start, mid, end — replacing start/end circles."""
    n = len(coords)
    if n < 2:
        return
    place_arrowhead(coords[0],    stable_bearing(coords, 0.0,  0.15), color, group, f"START {tip}")
    place_arrowhead(coords[n//2], stable_bearing(coords, 0.40, 0.80), color, group, tip)
    place_arrowhead(coords[-1],   stable_bearing(coords, 0.85, 1.0),  color, group, f"END {tip}")

# ── comment parsing ────────────────────────────────────────────────────────────

# Comments that begin with these strings are operational notes, not survey ends
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
    cu = comment.upper().strip()
    return cu.startswith(SKIP_PREFIXES)

# Manual name overrides — keyed by numeric site ID string.
# Add entries here whenever a site's auto-parsed name needs correction.
NAME_OVERRIDES = {
    '203': 'Ushagat/SW',
}

# site_id (numeric string) → display label; first-seen name wins per ID
_site_labels = {}

def get_site_label(comment):
    """
    Parse a survey comment into a site display label.
    Returns a string like "Jacob Rock (121)" or "Forrester", or None if unrecognised.

    Handles formats found across all files:
      121 JACOB ROCK PASS 1
      113A HAZY PASS 1          (letter suffix on ID)
      SL186 GRANITE CAPE        (SL/SSL prefix)
      SSL117 CAPE OMMANEY
      230 KODIAK/MALINA POINT - 0 ANIMALS   (dash + notes)
      231 KODIAK/STEEP CAPE - PASS 1
      FORRESTER PASS 1          (named group, no numeric ID)
    """
    c = comment.strip()
    # Strip leading non-alphanumeric garbage (e.g. _x0002_ encoding artifacts)
    c = re.sub(r'^[^A-Za-z0-9]+', '', c).strip()

    # ── special named group: Forrester ──
    if re.match(r'^FORRESTER\s+PASS', c, re.IGNORECASE):
        _site_labels.setdefault('FORRESTER', 'Forrester')
        return _site_labels['FORRESTER']

    # ── general numeric pattern ──
    # Optional prefix (SL / SSL) + digits + optional letter suffix + space + name
    # Name ends at: PASS / ABORTED / ONE PASS / NO ANIMALS / OBSV / VISUAL / PHOTO / dash / end
    m = re.match(
        r'^(?:SSL?)?(\d+)[A-Z]?\s+(.+?)'
        r'(?:\s+(?:PASS|ABORTED|ONE\s+PASS|NO\s+ANIMALS|OBSV|VISUAL|PHOTO|PASS\s+ONE)'
        r'|\s*[-–]\s*'
        r'|\s*$)',
        c, re.IGNORECASE
    )
    if not m:
        return None

    sid  = m.group(1)                       # numeric ID (strips letter suffix)
    name = m.group(2).strip()

    # Clean trailing sub-site letters: " A TO B", " B", " A"
    name = re.sub(r'\s+[A-Z]\s+(?:TO|AND)\s+[A-Z]\s*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+[A-Z]\s*$', '', name).strip()
    # Strip trailing digits that leaked in (e.g. "PERRY 1", "CAPE HINCHINBROOK 1")
    name = re.sub(r'\s+\d+\s*$', '', name).strip()
    name = name.title()

    if not name:
        return None

    if sid in NAME_OVERRIDES:
        name = NAME_OVERRIDES[sid]
    label = f"{name} ({sid})"
    _site_labels.setdefault(sid, label)
    return _site_labels[sid]

# ── load all xlsx files ────────────────────────────────────────────────────────

passes_by_site = defaultdict(list)   # site_label → [{date, comment, coords}]

for filepath in sorted(glob.glob('*.xlsx')):
    date_str = Path(filepath).stem[:8]   # "20210623"
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
                label = get_site_label(comment)
                if label:
                    passes_by_site[label].append({
                        'date':    date_str,
                        'comment': comment,
                        'coords':  list(current_x),
                    })
            current_x = []   # always reset after any C row

print(f"Loaded {sum(len(v) for v in passes_by_site.values())} passes across "
      f"{len(passes_by_site)} sites from {len(glob.glob('*.xlsx'))} files.")

# ── match site photos by filename (referenced by relative path, not embedded) ──

site_photos = {}   # site_label → filename (e.g. "Jacob Rock (121).png")
# Filenames now match site labels exactly; just look for <label>.png (with / replaced by _)
for label in passes_by_site:
    safe_label = re.sub(r'[\\/:*?"<>|]', '_', label)
    for ext in ('png', 'jpg', 'jpeg'):
        fname = f"{safe_label}.{ext}"
        if Path(fname).exists():
            site_photos[label] = fname
            print(f"  Photo: {fname}")
            break
    else:
        # Fallback for legacy names (e.g. ForresterIsland.png)
        for imgpath in glob.glob('*.png') + glob.glob('*.jpg') + glob.glob('*.jpeg'):
            stem = re.sub(r'[\s_\-]', '', Path(imgpath).stem).lower()
            site_key = re.sub(r'\s', '', re.sub(r'\s*\(\d+\)\s*$', '', label)).lower()
            if site_key == stem or (len(site_key) > 4 and site_key in stem):
                site_photos[label] = Path(imgpath).name
                print(f"  Photo (fallback): {Path(imgpath).name}")
                break

# ── build map ─────────────────────────────────────────────────────────────────

all_coords = [c for site_passes in passes_by_site.values()
                for p in site_passes
                for c in p['coords']]
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

# Colour palette — visually distinct, same as before
COLORS = [
    '#e6194b','#3cb44b','#ffe119','#4363d8','#f58231',
    '#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4',
    '#469990','#dcbeff','#9a6324','#800000','#aaffc3',
    '#808000','#ffd8b1','#000075','#a9a9a9','#e6beff',
]
LIGHT_COLORS = {'#ffe119','#bfef45','#42d4f4','#fabed4','#aaffc3','#ffd8b1','#e6beff'}

for idx, site in enumerate(sorted(passes_by_site)):
    color      = COLORS[idx % len(COLORS)]
    text_color = '#000' if color in LIGHT_COLORS else '#fff'
    group      = folium.FeatureGroup(name=site, show=True)
    site_passes = passes_by_site[site]

    for pass_num, p in enumerate(site_passes, 1):
        coords = p['coords']
        badge  = f"P{pass_num}"
        tip    = f"{badge} ({p['date']}) — {p['comment']}"

        # ── track line ──
        folium.PolyLine(
            locations=coords, color=color, weight=3, opacity=0.9,
            tooltip=tip,
        ).add_to(group)

        # ── directional arrowheads (start, mid, end — replaces circles) ──
        add_arrows(coords, color, group, tip)

        # ── pass number badge at ~¼ of the way along ──
        q = max(0, len(coords) // 4)
        folium.Marker(
            location=coords[q],
            tooltip=tip,
            icon=folium.DivIcon(
                html=(f'<div style="background:{color};color:{text_color};'
                      f'border-radius:50%;width:20px;height:20px;line-height:20px;'
                      f'text-align:center;font-size:10px;font-weight:bold;'
                      f'font-family:sans-serif;border:1.5px solid rgba(0,0,0,0.4);'
                      f'box-shadow:1px 1px 3px rgba(0,0,0,0.6);">{badge}</div>'),
                icon_size=(20, 20), icon_anchor=(10, 10),
            )
        ).add_to(group)


    # ── site photo marker (click to open popup with embedded image) ──
    if site in site_photos:
        all_site_coords = [c for p in site_passes for c in p['coords']]
        centroid = (
            sum(c[0] for c in all_site_coords) / len(all_site_coords),
            sum(c[1] for c in all_site_coords) / len(all_site_coords),
        )
        site_name_short = re.sub(r'\s*\(\d+\)\s*$', '', site).strip()
        popup_html = (
            f'<div style="text-align:center;font-family:sans-serif;padding:4px;">'
            f'<b style="font-size:13px;">{site}</b><br>'
            f'<img src="{site_photos[site]}" '
            f'style="max-width:300px;max-height:220px;margin-top:6px;border-radius:4px;">'
            f'</div>'
        )
        folium.Marker(
            location=centroid,
            tooltip=f"{site} — click for photo",
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

folium.LayerControl(collapsed=False).add_to(m)

outfile = 'index.html'
m.save(outfile)
print(f"\nSaved: {outfile}")
print(f"\n{'Site':<40} {'Passes':>6}  {'Photo':>5}")
print('-' * 55)
for site in sorted(passes_by_site):
    n     = len(passes_by_site[site])
    photo = 'yes' if site in site_photos else ''
    print(f"{site:<40} {n:>6}  {photo:>5}")
