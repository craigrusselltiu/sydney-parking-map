"""Refresh the street-parking snapshot from City of Sydney and TfNSW open data."""

import io
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile


TARGET = Path(__file__).resolve().parents[1] / "docs/data/kerbs.json"
ITEMS = "https://www.arcgis.com/home/item.html?id="
METER_ID = "71bb12507a3240c4b12e7fbba5be58e1"
METERS = f"https://utility.arcgis.com/usrsvcs/servers/{METER_ID}/rest/services/ParkingMeters/ParkingMeters/MapServer"
MOBILITY = "https://services1.arcgis.com/cNVyNtjGVZybOQWZ/arcgis/rest/services/Mobility_parking/FeatureServer/1"
LOADING_CATALOG = "https://opendata.transport.nsw.gov.au/data/api/3/action/package_show?id=loading-zones-kerbside"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"


def fetch(url):
    headers = {"User-Agent": "SydneyParkingMap/1.0"}
    if url.startswith(METERS):
        headers["Referer"] = "https://cityofsydney.maps.arcgis.com/"
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        return response.read()


def arcgis(layer, path="", **params):
    url = layer + path + "?" + urlencode({"f": "json", **params})
    result = json.loads(fetch(url))
    if "error" in result:
        raise ValueError(f"{layer} returned {result['error']}")
    return result


def read_layer(layer):
    ids = arcgis(layer, "/query", where="1=1", returnIdsOnly="true")["objectIds"]
    features = []
    # ArcGIS caps a single response. Fetch the ID list first to avoid silent truncation.
    for start in range(0, len(ids), 200):
        batch = ids[start:start + 200]
        result = arcgis(layer, "/query", objectIds=",".join(map(str, batch)),
                        outFields="*", outSR=4326)
        records = result["features"]
        if {r["attributes"]["OBJECTID"] for r in records} != set(batch):
            raise ValueError("Source changed during download or returned an incomplete batch.")
        features.extend(records)
    if not features:
        raise ValueError(f"Empty layer: {layer}")
    return features


def position(lon, lat):
    if not (151 < lon < 151.4 and -34.1 < lat < -33.7):
        raise ValueError(f"Unexpected Sydney coordinate {(lon, lat)}")
    return [round(lon, 7), round(lat, 7)]


def point(geometry):
    return {"type": "Point", "coordinates": position(geometry["x"], geometry["y"])}


def clean(text):
    return " ".join(str(text or "").split())


def title(text):
    return text.title() if text.isupper() else text


def meter_rule(raw):
    match = re.fullmatch(r"(\d+(?:/\d+)?)P (\d+(?::\d+)?(?:AM|PM))-(\d+(?::\d+)?(?:AM|PM)) (.+?), (\$[\d.]+) /HR", raw)
    if not match:
        return raw
    limit, start, end, days, rate = match.groups()
    duration = {"1/4": "15 min", "1/2": "30 min", "1": "1 hour"}.get(limit, f"{limit} hours")
    days = days.title().replace("Public Holidays", "public holidays").replace("-", "–")
    time = "all day" if start == end == "12AM" else f"{start.lower()}–{end.lower()}"
    return f"{days}, {time} · {duration} max · {rate}/hr"


def meters():
    free_ticket_ids = {f["attributes"]["Meter_ID"] for f in read_layer(METERS + "/79")}
    for feature in read_layer(METERS + "/78"):
        a = feature["attributes"]
        rules = [meter_rule(r) for r in map(clean, (a["Popup"] or "").split(";")) if r]
        if a["Meter_ID"] in free_ticket_ids:
            rules.insert(0, "Free 15-minute ticket. Buy a paid ticket on arrival for a longer stay.")
        if a["Status_ID"] != 1:
            status = {4: "out of operation", 5: "shut down"}.get(a["Status_ID"], "status unknown")
            rules.insert(0, f"Meter {status} at snapshot date.")
        yield {
            "id": f"meter-{a['Meter_ID']}", "kind": "meter", "source": "meters",
            "name": title(clean(a["Street"])), "area": title(clean(a["Suburb"])),
            "location": f"Meter {a['Meter_ID']} · {a['Location_ID']}",
            "geometry": point(feature["geometry"]),
            "rules": rules or ["Meter times unavailable. Check the signs."],
            "spaces": a["ApproxPaySpaces"],
        }


def mobility():
    for feature in read_layer(MOBILITY):
        a = feature["attributes"]
        day = datetime.strptime(a["AuditDate"], "%d/%m/%Y").date().isoformat() if a["AuditDate"] else None
        side = clean(a["SideOfStreet"]).lower().replace("side", " side").capitalize()
        address = clean(a["Address"])
        details = [side, f"{address} {a['Street']}" if address else "", clean(a["Location"])]
        yield {
            "id": f"mobility-{a['OBJECTID']}", "kind": "mobility", "source": "mobility",
            "name": title(clean(a["Street"])), "area": title(clean(a["Suburb"])),
            "location": " · ".join(filter(None, details)), "geometry": point(feature["geometry"]),
            "audited": day, "spaces": a["NumberParkingSpaces"],
            "rules": [clean(a["SignText"]) or "Sign hours unavailable. Check the sign at this bay."],
        }


def loading_hours(value, period):
    value = clean(value)
    if not value:
        return f"{period} loading hours unrecorded."
    if value == "24 H":
        return f"{period} · loading zone all day"
    value = re.sub(r"\b(\d{1,2})(\d{2})\b", lambda m: f"{int(m[1]):02d}:{m[2]}", value)
    return "Loading zone · " + value.replace("Mn-Fri", "Mon-Fri").replace("Mon - Fri", "Mon-Fri").replace("-", "–")


def polygon(rings):
    # The source has disjoint clockwise outer rings. Refuse new topology rather
    # than treating a hole as a permitted or restricted area.
    polygons = []
    for ring in rings:
        x0, y0 = ring[0]
        twice_area = sum((x - x0) * (v - y0) - (u - x0) * (y - y0)
                         for (x, y), (u, v) in zip(ring, ring[1:]))
        if twice_area >= 0 or ring[0] != ring[-1]:
            raise ValueError("Unrecognised loading-zone polygon orientation or closure")
        polygons.append([[position(x, y) for x, y in reversed(ring)]])
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def load_zones():
    package = json.loads(fetch(LOADING_CATALOG))["result"]
    resource = next(r for r in package["resources"] if r["id"] == "b8cc6593-fc6d-4ab8-b007-078ab72b8302")
    with ZipFile(io.BytesIO(fetch(resource["url"]))) as archive:
        member = archive.getinfo("LoadingzoneData.json")
        file_date = datetime(*member.date_time).date().isoformat()
        result = json.loads(archive.read(member))
    if result["spatialReference"].get("wkid") != 4326 or not result["features"]:
        raise ValueError("Unexpected loading-zone source format")
    features = []
    for feature in result["features"]:
        a = feature["attributes"]
        side = clean(a["SIDE"]).title()
        location = " · ".join(filter(None, (side if side == "Central" else f"{side} side",
                                             clean(a["BETWEEN_"]))))
        features.append({
            "id": f"loading-{a['OBJECTID']}", "kind": "kerb", "source": "loading",
            "name": clean(f"{a['STREET']} {a['SUFFIX']}"), "area": "Sydney CBD",
            "location": location, "geometry": polygon(feature["geometry"]["rings"]),
            "rules": [loading_hours(a["HRS_OPERATION_WEEKDAY"], "Weekday"),
                      loading_hours(a["HRS_OPERATION_WEEKEND"], "Weekend")],
            "spaces": a["SPACES_AVAILABLE"],
        })
    return features, file_date, resource["last_modified"][:10]


def main():
    loading, file_date, modified = load_zones()
    features = [*meters(), *mobility(), *loading]
    if len({r["id"] for r in features}) != len(features):
        raise ValueError("Duplicate record ID")
    sources = {
        "meters": {"name": "City of Sydney · Parking meters", "url": ITEMS + METER_ID,
                   "license": "CC BY 4.0", "licenseUrl": CC_BY,
                   "note": "Meter positions, published tariffs and approximate spaces. Sign boundaries and driveway gaps are unverified."},
        "mobility": {"name": "City of Sydney · Mobility parking", "url": ITEMS + "2671fdce3f354b3e8f02236ca12271cb",
                     "license": "CC BY 4.0", "licenseUrl": CC_BY,
                     "note": "Designated mobility bays. Each record includes the council’s audit date when available."},
        "loading": {"name": "Transport for NSW · Loading Zones Kerbside",
                    "url": "https://opendata.transport.nsw.gov.au/dataset/loading-zones-kerbside",
                    "license": "Creative Commons Attribution", "licenseUrl": "https://opendata.transport.nsw.gov.au/dataset/loading-zones-kerbside",
                    "fileDate": file_date, "resourceModified": modified,
                    "note": f"Historical loading-zone polygons. Source file dated {file_date}, archive updated {modified}. Other times are unverified."},
    }
    snapshot = {"retrieved": datetime.now(timezone.utc).date().isoformat(), "sources": sources, "features": features}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temp = TARGET.with_suffix(".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(TARGET)
    print(f"Wrote {len(features):,} records to {TARGET}")


if __name__ == "__main__":
    main()
