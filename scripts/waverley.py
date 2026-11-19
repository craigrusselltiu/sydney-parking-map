"""Refresh published Waverley kerb polylines. Install pyshp and pyproj to run."""

import io
import json
import re
from datetime import date
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import shapefile
from pyproj import CRS, Transformer

CATALOG = "https://opendata.transport.nsw.gov.au/data/api/3/action/package_show?id=waverley-council-data"
PAGE = "https://opendata.transport.nsw.gov.au/dataset/waverley-council-data"
OUTPUT = Path(__file__).resolve().parents[1] / "docs/data/waverley.json"


def main():
    with urlopen(CATALOG, timeout=45) as response:
        dataset = json.load(response)["result"]
    resource = next(r for r in dataset["resources"] if r["name"] == "On street car parking bays v2")
    with urlopen(resource["url"], timeout=60) as response, ZipFile(io.BytesIO(response.read())) as archive:
        shp = next(i for i in archive.infolist() if i.filename.endswith(".shp"))
        base = shp.filename[:-4]
        file_date = date(*shp.date_time[:3]).isoformat()
        transform = Transformer.from_crs(CRS.from_wkt(archive.read(base + ".prj").decode()), 4326, always_xy=True)
        reader = shapefile.Reader(**{ext: io.BytesIO(archive.read(base+"."+ext)) for ext in ("shp","shx","dbf")}, encoding="cp1252")
        records = []
        for item in reader.iterShapeRecords():
            r = item.record.as_dict()
            # The export gives its "no parking data" records a placeholder "No parking".
            # Those records carry no rule evidence and must stay off the map.
            if r["ParkData"] != "available parking data" or not r["Rules_orig"].strip():
                continue
            ranges = list(item.shape.parts) + [len(item.shape.points)]
            parts = []
            for start, end in zip(ranges, ranges[1:]):
                line = [[round(x, 7), round(y, 7)] for x, y in transform.itransform(item.shape.points[start:end])]
                if len(line) >= 2:
                    parts.append(line)
            if not parts:
                continue
            rule = r["Rules_orig"].strip()
            status = "mixed"
            if rule.lower() == "unrestricted":
                status = "parking"
            elif not re.search(r"\d", rule) and re.search(r"no parking|no stopping|bus zone|mobility parking|taxi zone|loading zone|mail zone|only", rule, re.I):
                status = "restricted"
            records.append({
                "id": f"waverley-{r['ID']}", "kind":"section","source":"waverley",
                "name": r["Street"].title(), "area":"Waverley council area",
                "location": f"{r['Side'].title()} side · {r['From'].title()} to {r['To'].title()}",
                "side": None, "status":status, "rules":[rule[0].upper()+rule[1:]],
                "geometry":{"type":"LineString" if len(parts)==1 else "MultiLineString",
                            "coordinates":parts[0] if len(parts)==1 else parts},
            })
    if not records or len({r["id"] for r in records}) != len(records):
        raise ValueError("Unexpected empty export or duplicate IDs")
    data = {"retrieved":date.today().isoformat(),"sources":{"waverley":{
        "name":"Waverley Council · On-street parking bays","url":PAGE,"fileDate":file_date,
        "license":dataset["license_title"],"licenseUrl":dataset.get("license_url") or PAGE,
        "note":f"Council kerb survey file dated {file_date}. Changes since the survey and unrecorded driveway openings need checking on site."
    }},"features":records}
    tmp=OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")), encoding="utf-8")
    tmp.replace(OUTPUT)
    print(f"{len(records):,} recorded kerb sections. Survey file date {file_date}.")


if __name__=="__main__":
    main()
