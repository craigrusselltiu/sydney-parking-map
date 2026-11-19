"""Build the ODbL street-section layer. Requires osmium and shapely.

Pass a BBBike Sydney .osm.pbf file. The second optional argument is a saved
copy of the official City of Sydney LGA boundary GeoJSON.
"""

import argparse
from datetime import date
import json
import math
from pathlib import Path
import re
from urllib.request import urlopen

import osmium
from shapely.geometry import LineString, Point, shape
from shapely.prepared import prep


OUTPUT = Path(__file__).resolve().parents[1] / "docs/data/street-sections.json"
BOUNDARY = ("https://services1.arcgis.com/cNVyNtjGVZybOQWZ/arcgis/rest/services/"
            "LGABoundary/FeatureServer/0/query?where=1%3D1&outFields=OBJECTID&outSR=4326&f=geojson")
PBF = "https://download.bbbike.org/osm/bbbike/Sydney/Sydney.osm.pbf"
DAYS = dict(Mo="Mon", Tu="Tue", We="Wed", Th="Thu", Fr="Fri", Sa="Sat", Su="Sun", PH="public holidays")
CONDITIONS = {"ticket": "Ticket required", "no_stopping": "No stopping",
              "no_parking": "No parking", "disabled": "Mobility parking",
              "loading_zone": "Loading zone", "car_sharing": "Car share only",
              "disc": "Parking disc recorded", "free": "No fee recorded"}


def schedule(text):
    text = re.sub(r"\b(Mo|Tu|We|Th|Fr|Sa|Su|PH)\b", lambda m: DAYS[m[1]], text)
    return re.sub(r"\s*([,;])\s*", r"\1 ", text).replace("-", "–")


def conditional(text, label):
    result = []
    # Semicolons can separate windows inside parentheses or introduce a new
    # conditional value. Only the latter are split here.
    for part in re.split(r";\s*(?=[^();@]+@)", text):
        if "@" not in part:
            return []
        value, when = [s.strip() for s in part.split("@", 1)]
        when = when.removeprefix("(").removesuffix(")").strip('"')
        if label == "Stay limit":
            condition = "Stay limit exemption" if value == "none" else f"{value} max"
        elif label == "Payment":
            condition = {"yes": "Fee applies", "ticket": "Ticket required"}.get(value)
        else:
            condition = {"no": "No parking"}.get(value)
        if condition is None:
            return []
        result.append(f"{condition} · {schedule(when)}")
    return result


def road_side(tags, side):
    base = f"parking:{side}"
    old = f"parking:condition:{side}"
    # Mixed vintage clearway tags include both unconditional and timed bans.
    # The source does not resolve that conflict. Do not choose between them.
    if tags.get(base) == "no" and tags.get(old + ":time_interval"):
        return []
    # Legacy numbered restrictions can override each other on specific days.
    if any(k.startswith(old + ":2") for k in tags):
        return []
    details = []
    maximum = tags.get(base + ":maxstay:conditional") or tags.get(old + ":maxstay:conditional")
    stay = tags.get(base + ":maxstay") or tags.get(old + ":maxstay")
    interval = tags.get(old + ":time_interval")
    if interval and not re.search(r"\d\d:\d\d", interval):
        return []
    if maximum or (stay and "@" in stay):
        details = conditional(maximum or stay, "Stay limit")
        if not details:
            return []
    elif stay:
        details.append(f"{stay} max" + (f" · {schedule(interval)}" if interval else " · hours unrecorded"))
    payment = tags.get(base + ":fee:conditional") or tags.get(old + ":conditional")
    if payment:
        parsed = conditional(payment, "Payment")
        if not parsed:
            return []
        details.extend(parsed)
    access = tags.get(base + ":access:conditional") or tags.get(base + ":conditional")
    if access:
        parsed = conditional(access, "Access")
        if not parsed:
            return []
        details.extend(parsed)
    condition = CONDITIONS.get(tags.get(old))
    if condition and interval:
        details.append(f"{condition} · {schedule(interval)}")
    elif condition == "Ticket required" and stay:
        details.append(condition)
    if not details:
        return []
    permit_zone = tags.get(base + ":zone:residents") or tags.get(old + ":residents")
    if permit_zone:
        details.append(f"Resident permit area {permit_zone}")
    if tags.get(base + ":authentication:disc") == "yes" or tags.get("parking:both:authentication:disc") == "yes":
        details.append("Parking disc recorded")
    if tags.get(base + ":access") == "disabled":
        details.insert(0, "Mobility parking")
    return details


def heading(coords):
    lon, lat = coords[0]
    east = (coords[-1][0] - lon) * math.cos(math.radians(lat))
    north = coords[-1][1] - lat
    bearing = math.degrees(math.atan2(east, north)) % 360
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        dx = (x2 - x1) * math.cos(math.radians(y1))
        dy = y2 - y1
        if math.hypot(dx, dy) < 0.00002:
            continue
        local_bearing = math.degrees(math.atan2(dx, dy))
        if abs((local_bearing - bearing + 180) % 360 - 180) > 55:
            return None
    return ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")[int((bearing + 22.5) / 45) % 8]


def road(tags, coords):
    sides = {s: road_side(tags, s) for s in ("both", "left", "right")}
    if not any(sides.values()):
        return None
    # Where the opposite side also carries an explicit access restriction,
    # retain it on the same road feature even when no hours are recorded.
    for side in ("left", "right"):
        if sides[side]:
            continue
        base = f"parking:{side}"
        old = f"parking:condition:{side}"
        restriction = (tags.get(base + ":restriction") or tags.get(old)
                       or tags.get(base + ":access"))
        if restriction in ("disabled", "loading_zone", "car_sharing", "no_stopping", "no_parking"):
            if any(k.startswith(old + ":2") for k in tags):
                continue
            time = tags.get(old + ":time_interval")
            if time and not re.search(r"\d\d:\d\d", time):
                continue
            sides[side] = [CONDITIONS[restriction] + (" · " + schedule(time) if time else " · check sign for hours")]
    if sides["left"] and sides["left"] == sides["right"] and not sides["both"]:
        sides = {"both": sides["left"], "left": [], "right": []}
    rules = []
    labels = []
    direction = heading(coords)
    for side, values in sides.items():
        if not values:
            continue
        if side != "both" and not direction:
            continue
        label = "Both sides" if side == "both" else f"{side.title()} heading {direction}"
        labels.append(label)
        rules.extend(f"{label} · {r}" for r in values)
    if not rules:
        return None
    return {"geometry": {"type": "LineString", "coordinates": coords},
            "name": tags["name"], "location": " / ".join(labels), "rules": rules, "spaces": None}


def public_bay(tags, coords):
    if tags.get("access") not in ("yes", "permissive", "public"):
        return None
    if len(coords) == 1:
        geometry = {"type": "Point", "coordinates": coords[0]}
    elif len(coords) >= 4 and coords[0] == coords[-1]:
        geometry = {"type": "Polygon", "coordinates": [coords]}
    else:
        return None
    rules = []
    if tags.get("capacity:disabled") and tags.get("capacity:disabled") == tags.get("capacity"):
        rules.append("Mobility parking")
    if tags.get("fee") == "yes":
        rules.append("Fee applies" + (" · " + tags["charge"] if tags.get("charge") else ""))
    elif tags.get("fee") == "no":
        rules.append("No fee recorded")
    if tags.get("maxstay"):
        rules.append(f"{tags['maxstay']} max")
    if tags.get("opening_hours"):
        rules.append(schedule(tags["opening_hours"]))
    else:
        rules.append("Sign hours unrecorded.")
    return {"geometry": geometry, "name": tags.get("name") or tags.get("addr:street") or "Street-side parking",
            "location": "Mapped street-side bay", "rules": rules,
            "spaces": int(tags["capacity"]) if tags.get("capacity", "").isdigit() else None}


def build(pbf, boundary):
    city = prep(shape(boundary["features"][0]["geometry"]))
    with osmium.io.Reader(pbf) as reader:
        timestamp = reader.header().get("osmosis_replication_timestamp")
    if not timestamp:
        raise ValueError("PBF is missing its source timestamp")
    data = []
    for obj in osmium.FileProcessor(pbf).with_locations():
        t = obj.tags
        is_road = obj.is_way() and t.get("highway") and t.get("name") and any(z.k.startswith("parking:") for z in t)
        is_bay = (t.get("amenity") == "parking" and t.get("parking") in ("lane", "street_side", "on_kerb", "half_on_kerb")
                  and (obj.is_node() or obj.is_way()))
        if not (is_road or is_bay):
            continue
        coords = ([[obj.location.lon, obj.location.lat]] if obj.is_node()
                  else [[n.lon, n.lat] for n in obj.nodes if n.location.valid()])
        if not coords or (obj.is_way() and len(coords) != len(obj.nodes)):
            continue
        if not city.covers(Point(coords[0]) if len(coords) == 1 else LineString(coords)):
            continue
        tags = dict(t)
        result = road(tags, coords) if is_road else public_bay(tags, coords)
        if result:
            obj_type = "node" if obj.is_node() else "way"
            result.update(id=f"osm-section-{obj_type}-{obj.id}", kind="section", source="osm",
                          area="City of Sydney", url=f"https://www.openstreetmap.org/{obj_type}/{obj.id}")
            data.append(result)
    if not data:
        raise ValueError("No parking sections in extract")
    return {"retrieved": date.today().isoformat(), "sources": {"osm": {
        "name": "OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright",
        "license": "ODbL 1.0", "licenseUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
        "extractUrl": PBF, "fileDate": timestamp[:10],
        "note": "Community-mapped road sections and street-side bays. Lines follow the road centre. Check signs and driveway openings at the kerb.",
        "boundary": "City of Sydney · CC BY 4.0",
        "boundaryUrl": "https://www.arcgis.com/home/item.html?id=6e8360afd7f9499ab9425b2d17db730d"
    }}, "features": data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pbf", type=Path, help=f"Sydney extract, e.g. {PBF}")
    parser.add_argument("boundary", type=Path, nargs="?")
    args = parser.parse_args()
    if args.boundary:
        boundary = json.loads(args.boundary.read_bytes())
    else:
        with urlopen(BOUNDARY, timeout=60) as response:
            boundary = json.load(response)
    result = build(args.pbf, boundary)
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(OUTPUT)
    print(f"Wrote {len(result['features'])} OSM street sections and bays")


if __name__ == "__main__":
    main()
