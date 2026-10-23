"""Draw public/regions-map.svg (B20): Sydney's LGAs coloured by region, each region
labelled, and a dot for each cinema. Run by hand when the region table or the
cinemas change:

    .venv/bin/python -m scripts.build_regions_map

Regions, LGAs and cinema positions come from venues.yaml. Boundaries come from the
ABS (ASGS 2025 local government areas, generalised layer, CC BY 4.0), simplified
on their server to about 50 m; robots.txt allows the MapServer paths used here.
"""

import math
from html import escape
from pathlib import Path

import requests
import yaml

from export import VENUES_PATH, load_regions, load_venues

OUT = Path(__file__).resolve().parent.parent / "public" / "regions-map.svg"
QUERY = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2025/LGA/MapServer/1/query"
USER_AGENT = "sydney-cine/0.1 (+contact in README)"
ABS_NAMES = {  # our LGA name -> the ABS's, where they differ
    "City of Sydney": "Sydney",
    "Bayside": "Bayside (NSW)",
    "Campbelltown": "Campbelltown (NSW)",
}
COLOURS = {  # fills, readable on the site's navy
    "City": "#E8B86D",
    "East": "#5FB3C8",
    "Inner West": "#C784B5",
    "North": "#74BC85",
    "Parramatta & Hills": "#DD8462",
    "Outer West": "#9590DD",
    "South West": "#CDBF5E",
    "St George & Sutherland": "#5E93D6",
}
NAVY, INK, MUTED = "#181D3B", "#F2EAF1", "#9AA3C7"
WIDTH = 1000  # px across the map itself
MARGIN = 24
TOP = 86  # room for the title
# The view: every cinema with some room around it. Hawkesbury, Wollondilly and the
# Blue Mountains run on past its edges; drawing them whole would leave the city,
# where the cinemas are, a corner of the image.
WEST, EAST, SOUTH, NORTH = 150.2, 151.36, -34.16, -33.52
LABELS = {  # region -> (lon, lat) of its label, and the point a leader line reaches
    "City": ((151.30, -33.855), (151.207, -33.886)),
    "East": ((151.31, -33.95), (151.255, -33.92)),
    "Inner West": ((151.13, -33.855), None),
    "North": ((151.17, -33.70), None),
    "Parramatta & Hills": ((150.98, -33.66), None),
    "Outer West": ((150.62, -33.71), None),
    "South West": ((150.80, -34.02), None),
    "St George & Sutherland": ((151.08, -34.10), None),
}


def fetch_boundaries() -> dict[str, list]:
    """Our LGA name -> list of polygons, each a list of rings of (lon, lat)."""
    ours = [lga for lgas in load_regions().values() for lga in lgas]
    names = ", ".join("'" + ABS_NAMES.get(lga, lga) + "'" for lga in ours)
    response = requests.get(
        QUERY,
        params={
            "where": f"STATE_CODE_2021='1' AND LGA_NAME_2025 IN ({names})",
            "outFields": "LGA_NAME_2025",
            "outSR": "4326",
            "maxAllowableOffset": "0.0005",
            "geometryPrecision": "4",
            "f": "geojson",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    back = {v: k for k, v in ABS_NAMES.items()}
    shapes = {}
    for feature in response.json()["features"]:
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        shapes[back.get(feature["properties"]["LGA_NAME_2025"], feature["properties"]["LGA_NAME_2025"])] = polygons
    missing = set(ours) - set(shapes)
    if missing:
        raise SystemExit(f"No ABS boundary for {sorted(missing)}")
    return shapes


def draw(shapes: dict[str, list], regions: dict[str, list[str]], venues: dict[str, dict]) -> str:
    west, east, south, north = WEST, EAST, SOUTH, NORTH
    squash = math.cos(math.radians((north + south) / 2))  # equirectangular at mid-latitude
    scale = WIDTH / ((east - west) * squash)
    height = (north - south) * scale

    def xy(lon, lat):
        return MARGIN + (lon - west) * squash * scale, TOP + (north - lat) * scale

    def path(polygons):
        parts = []
        for poly in polygons:
            for ring in poly:
                points = [xy(lon, lat) for lon, lat in ring]
                parts.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points) + "Z")
        return "".join(parts)

    region_of = {lga: region for region, lgas in regions.items() for lga in lgas}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH + 2 * MARGIN} '
        f'{TOP + height + 64:.0f}" font-family="system-ui, -apple-system, Segoe UI, Roboto, '
        f'Helvetica, Arial, sans-serif">',
        "<title>Sydney Cinema Guide: regions</title>",
        f'<rect width="100%" height="100%" fill="{NAVY}"/>',
        f'<clipPath id="view"><rect x="{MARGIN}" y="{TOP}" width="{WIDTH}" height="{height:.1f}"/>'
        "</clipPath>",
        f'<text x="{MARGIN}" y="40" font-size="24" font-weight="800" fill="{INK}">Regions</text>',
        f'<text x="{MARGIN}" y="64" font-size="14" fill="{MUTED}">Local government areas by '
        "region, as used by the Region filter. Dots are cinemas.</text>",
        '<g clip-path="url(#view)">',
    ]
    for lga, polygons in sorted(shapes.items()):
        out.append(
            f'<path d="{path(polygons)}" fill="{COLOURS[region_of[lga]]}" fill-opacity="0.55" '
            f'stroke="{NAVY}" stroke-width="0.8" stroke-linejoin="round"><title>{escape(lga)}: '
            f"{escape(region_of[lga])}</title></path>"
        )
    out.append("</g>")
    for region, ((lon, lat), reach) in LABELS.items():
        if reach:
            (x1, y1), (x2, y2) = xy(lon, lat), xy(*reach)
            out.append(
                f'<line x1="{x1:.1f}" y1="{y1 - 5:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{INK}" stroke-width="1" stroke-opacity="0.7"/>'
            )
    for slug, venue in sorted(venues.items(), key=lambda kv: kv[1]["name"]):
        x, y = xy(venue["at"][1], venue["at"][0])
        out.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="{INK}" stroke="{NAVY}" '
            f'stroke-width="1.2"><title>{escape(venue["name"])}</title></circle>'
        )
    for region in regions:
        x, y = xy(*LABELS[region][0])
        out.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="15" '
            f'font-weight="700" text-anchor="middle" fill="{INK}" stroke="{NAVY}" '
            f'stroke-width="4" stroke-linejoin="round" paint-order="stroke">{escape(region)}</text>'
        )
    out.append(
        f'<text x="{MARGIN}" y="{TOP + height + 40:.0f}" font-size="12" fill="{MUTED}">'
        "Boundaries: ABS ASGS 2025 local government areas (CC BY 4.0), simplified. "
        "Cinema positions: © OpenStreetMap contributors.</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    regions = load_regions()
    venues = load_venues()
    yaml.safe_load(VENUES_PATH.read_text(encoding="utf-8"))  # fail early on a broken file
    svg = draw(fetch_boundaries(), regions, venues)
    OUT.write_text(svg, encoding="utf-8")
    print(f"Wrote {OUT} ({len(svg.encode()) // 1024} KB)")


if __name__ == "__main__":
    main()
