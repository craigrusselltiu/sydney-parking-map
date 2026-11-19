"""Bundle the Greater Sydney overview and street detail for selected centres."""

import argparse
import gzip
import json
import math
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
AGENT = "SydneyKerbsideMap/1.0 (https://github.com/craigrusselltiu/sydney-parking-map)"
PLANET = "https://tiles.openfreemap.org/planet"
GLYPHS = "https://tiles.openfreemap.org/fonts"
CENTRES = {
    "Central Sydney": [151.14, -33.94, 151.255, -33.835],
    "Hornsby": [151.07, -33.72, 151.13, -33.675],
    "Penrith": [150.666, -33.78, 150.725, -33.727],
    "Campbelltown": [150.78, -34.099, 150.848, -34.044],
}


def download(url):
    request = Request(url, headers={"User-Agent": AGENT, "Accept-Encoding": "gzip"})
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    content = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    return content, len(raw)


def tile_point(lon, lat, zoom):
    scale = 2 ** zoom
    x = (lon + 180) / 360
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2
    return int(scale * x), int(scale * y)


def tiles_in(bounds, min_zoom, max_zoom):
    west, south, east, north = bounds
    for z in range(min_zoom, max_zoom + 1):
        left, top = tile_point(west, north, z)
        right, bottom = tile_point(east, south, z)
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                yield z, x, y


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", help="OpenFreeMap planet snapshot ID (default: latest)")
    args = parser.parse_args()
    style = json.loads((ASSETS / "map-style.json").read_text(encoding="utf-8"))
    city = style["sources"]["city"]
    url_template = json.loads(download(PLANET)[0])["tiles"][0]
    if args.snapshot:
        url_template = PLANET + "/" + quote(args.snapshot, safe="") + "/{z}/{x}/{y}.pbf"
    tiles = set(tiles_in(city["bounds"], city["minzoom"], 11))
    for bounds in CENTRES.values():
        tiles.update(tiles_in(bounds, 12, city["maxzoom"]))
    tasks = [
        (url_template.format(z=z, x=x, y=y), f"tiles/{z}/{x}/{y}.pbf")
        for z, x, y in sorted(tiles)
    ]
    tile_count = len(tasks)
    if tile_count > 3000:
        raise ValueError("Extract exceeds the OpenFreeMap offline tile allowance")
    for font in ("Noto Sans Regular", "Noto Sans Bold"):
        for first in (0, 256, 512, 768, 8192, 8448):
            filename = f"{first}-{first + 255}.pbf"
            tasks.append((f"{GLYPHS}/{quote(font)}/{filename}", f"glyphs/{font}/{filename}"))
    output = ASSETS / "basemap"
    previous = output / "snapshot.json"
    old = json.loads(previous.read_bytes()) if previous.is_file() else {}
    cached_tiles = {f"tiles/{key}.pbf" for key in old.get("localTiles", [])}
    same_build = old.get("tiles") == url_template
    transferred = 0
    with tempfile.TemporaryDirectory() as temp:
        staged = Path(temp)
        for url, relative_path in tasks:
            cached = output / relative_path
            reusable = relative_path in cached_tiles or relative_path.startswith("glyphs/")
            if same_build and reusable and cached.is_file() and cached.stat().st_size:
                continue
            data, size = download(url)
            transferred += size
            if transferred > 50_000_000:
                raise ValueError("Extract exceeds the OpenFreeMap offline size allowance")
            path = staged / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        metadata = {
            "tiles": url_template,
            "bounds": city["bounds"],
            "detailBounds": CENTRES,
            "tileCount": tile_count,
            "localTiles": [f"{z}/{x}/{y}" for z, x, y in sorted(tiles)],
        }
        (staged / "snapshot.json").write_text(json.dumps(metadata, indent=2) + "\n")
        shutil.copytree(staged, output, dirs_exist_ok=True)
    print(f"Prepared {tile_count} vector tiles and {len(tasks) - tile_count} glyph ranges "
          f"({transferred:,} bytes transferred).")


if __name__ == "__main__":
    main()
