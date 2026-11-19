"""Load ABS Greater Sydney and locality polygons and write the suburb search index."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

from shapely import STRtree, make_valid
from shapely.geometry import Point, shape
from shapely.prepared import prep


ABS = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2026"
GCCSA = f"{ABS}/GCCSA/MapServer/0"
SAL = f"{ABS}/SAL/MapServer/0"
OUTPUT = Path(__file__).resolve().parents[1] / "docs/data/suburbs.json"
SOURCE = {"name": "Australian Bureau of Statistics · ASGS Edition 4 (2026) suburbs and localities",
          "url": SAL, "boundaryUrl": GCCSA, "license": "CC BY 4.0",
          "licenseUrl": "https://creativecommons.org/licenses/by/4.0/"}


def query(layer, **params):
    with urlopen(layer + "/query?" + urlencode(params), timeout=90) as response:
        result = json.load(response)
    if result.get("error"):
        raise ValueError(result["error"])
    return result


def cached(directory, name, fetch):
    target = directory / name
    if target.is_file():
        return json.loads(target.read_bytes())
    result = fetch()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)
    return result


def get_localities(bounds):
    params = dict(geometry=",".join(map(str, bounds)), geometryType="esriGeometryEnvelope",
                  inSR=4326, where="STATE_CODE_2026='1'", returnIdsOnly="true", f="json")
    ids = sorted(query(SAL, **params)["objectIds"])
    if not ids:
        raise ValueError("No NSW localities intersect the Greater Sydney extent")

    def fetch_batch(batch):
        result = query(SAL, objectIds=",".join(map(str, batch)), f="geojson", outSR=4326,
                       outFields="OBJECTID,SAL_CODE_2026,SAL_NAME_2026", geometryPrecision=6)
        features = result["features"]
        if {r["properties"]["OBJECTID"] for r in features} != set(batch):
            raise ValueError("Incomplete suburb polygon response")
        return features

    groups = [ids[n:n+30] for n in range(0, len(ids), 30)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = [r for batch in pool.map(fetch_batch, groups) for r in batch]
    return {"type": "FeatureCollection", "features": records}


class Metro:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        boundary = cached(directory, "greater-sydney-2026.json", lambda: query(
            GCCSA, where="GCCSA_CODE_2026='1GSYD'", outFields="GCCSA_CODE_2026,GCCSA_NAME_2026",
            outSR=4326, f="geojson", geometryPrecision=6))
        row, = boundary["features"]
        if row["properties"]["GCCSA_CODE_2026"] != "1GSYD":
            raise ValueError("Unexpected ABS GCCSA code")
        self.geometry = shape(row["geometry"])
        self.prepared = prep(self.geometry)
        rows = cached(directory, "localities-2026.json", lambda: get_localities(self.geometry.bounds))
        self.names, self.polygons, self.search_points = [], [], {}
        for row in rows["features"]:
            if not row["geometry"]:
                continue
            geometry = shape(row["geometry"])
            if not geometry.is_valid:
                geometry = make_valid(geometry)
            if not self.prepared.intersects(geometry):
                continue
            name = re.sub(r" \((?:NSW|NSW\.)\)$", "", row["properties"]["SAL_NAME_2026"],
                          flags=re.IGNORECASE)
            self.names.append(name)
            self.polygons.append(geometry)
            part = geometry if self.prepared.covers(geometry) else geometry.intersection(self.geometry)
            if part.area < 0.000001 or part.area < geometry.area * 0.01:
                continue
            centre = part.centroid
            self.search_points[name] = centre if part.contains(centre) else part.representative_point()
        self.tree = STRtree(self.polygons)
        self.osm_centres = False
        for city in ("Hornsby", "Penrith", "Campbelltown"):
            if city not in self.search_points:
                raise ValueError(f"Missing Greater Sydney locality {city}")

    def locality(self, point):
        indices = self.tree.query(point, predicate="intersects")
        return self.names[indices[0]] if len(indices) else None

    def set_place(self, name, coords):
        point = Point(coords)
        if name in self.search_points and self.prepared.covers(point) and self.locality(point) == name:
            self.search_points[name] = point
            self.osm_centres = True

    def write_index(self):
        places = [{"name": name, "point": [round(p.x, 6), round(p.y, 6)]}
                  for name, p in sorted(self.search_points.items())]
        source = SOURCE.copy()
        if self.osm_centres:
            source.update(centresName="OpenStreetMap contributors · named place centres",
                          centresUrl="https://www.openstreetmap.org/copyright",
                          centresLicense="ODbL 1.0", centresLicenseUrl="https://opendatacommons.org/licenses/odbl/1-0/")
        result = {"source": source, "places": places}
        tmp = OUTPUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        tmp.replace(OUTPUT)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path, help="Local cache for the 2026 ABS polygons")
    args = parser.parse_args()
    metro = Metro(args.cache)
    metro.write_index()
    print(f"Wrote {len(metro.search_points)} suburb search destinations")
