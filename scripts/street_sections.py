"""Build Greater Sydney parking evidence from the Geofabrik NSW PBF (osmium, shapely)."""

import argparse
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
import re

import osmium
from shapely.geometry import LineString, Point

from metro_geography import GCCSA, Metro, SAL


OUTPUT = Path(__file__).resolve().parents[1] / "docs/data/street-sections.json"
PBF = "https://download.geofabrik.de/australia-oceania/australia/new-south-wales-latest.osm.pbf"
DAYS = dict(Mo="Mon", Tu="Tue", We="Wed", Th="Thu", Fr="Fri", Sa="Sat", Su="Sun", PH="public holidays")
RESTRICTIONS = {
    "no": "No parking", "no_parking": "No parking", "no_stopping": "No stopping",
    "no-stopping": "No stopping", "no stopping": "No stopping", "loading_only": "Loading only",
    "loading_zone": "Loading zone", "bus_zone": "Bus zone", "clearway": "Clearway",
    "disabled": "Mobility parking", "car_sharing": "Car share only", "delivery": "Deliveries only",
    "private": "Private access", "customers": "Customers only", "residents": "Residents only",
    "permit": "Permit holders only",
}
POSITION = {
    "yes": "Kerbside parking mapped", "lane": "Kerbside parking lane", "on_street": "On-street parking",
    "in-lane": "Kerbside parking lane", "in_lane": "Kerbside parking lane",
    "in-shoulder": "Shoulder parking", "shoulder": "Shoulder parking", "street_side": "Street-side bays",
    "bays": "Street-side bays", "on_kerb": "Kerb-top parking mapped", "half_on_kerb": "Partial kerb parking mapped",
    "parallel": "Parallel parking", "diagonal": "Diagonal parking", "perpendicular": "Perpendicular parking",
    "marked": "Marked parking bays",
}
BAY_TYPES = {"street_side", "lane", "on_kerb", "half_on_kerb"}
CONDITIONS = {**RESTRICTIONS, "free": "No fee recorded", "ticket": "Ticket required",
              "disc": "Parking disc recorded", "yes": "Parking access recorded", "none": "No restriction recorded"}
SPECIAL = ("taxi", "bus", "disabled", "emergency", "car_sharing", "mail", "police")


def readable(value):
    return value.replace("_", " ")


def schedule(value):
    value = re.sub(r"\b(Mo|Tu|We|Th|Fr|Sa|Su|PH)\b", lambda m: DAYS[m[1]], value)
    return re.sub(r"\s*([,;])\s*", r"\1 ", value).replace("-", "–")


def effective(tags, side, section):
    """A side-specific value overrides the 'both' value for the same attribute."""
    values = {}
    for direction in ("both", side):
        prefix = f"parking:{section}{direction}"
        for key, value in tags.items():
            if key == prefix or key.startswith(prefix + ":"):
                values[key[len(prefix):].lstrip(":")] = value
    return values


def format_value(key, value):
    if key == "maxstay":
        if value in ("no", "none", "unlimited"):
            return "No stay limit recorded"
        return f"{value} max"
    if key == "fee":
        return {"yes": "Fee applies", "no": "No fee recorded"}.get(value, "Fee · " + readable(value))
    if key.startswith("authentication:"):
        method = key.split(":", 1)[1]
        return f"{method.capitalize()} " + ("required" if value == "yes" else readable(value))
    if key == "charge":
        return "Charge · " + value
    return CONDITIONS.get(value, readable(value).capitalize())


def conditional(key, text):
    """Split between clauses, preserving semicolons inside a time expression."""
    result = []
    for part in re.split(r";\s*(?=[^();@]+@)", text):
        if "@" not in part:
            result.append(f"{readable(key).capitalize()} · {schedule(part.strip())}")
            continue
        value, when = [s.strip() for s in part.split("@", 1)]
        when = when.removeprefix("(").removesuffix(")").strip('"')
        result.append(f"{format_value(key, value)} · {schedule(when)}")
    return result


def rule_summary(fields, legacy, lane):
    """Keep the hours attached to the exact rule recorded by the mapper."""
    rules = []
    timed = False
    restricted = False
    parking = False
    position = fields.get("", lane.get("", ""))
    base_restriction = fields.get("restriction") or (position if position in RESTRICTIONS else None)
    interval = legacy.get("time_interval")
    if interval and not re.search(r"\d\d:\d\d", interval):
        # Some old records put '1 hour' in the time-window field.
        rules.append("Recorded interval · " + interval)
        interval = None
    for key in ("maxstay", "fee", "authentication:ticket", "authentication:disc",
                "access", "restriction", "parking", "condition", "charge"):
        value = fields.get("conditional" if key == "parking" else key + ":conditional")
        if key in ("maxstay", "condition"):
            value = value or legacy.get("conditional" if key == "condition" else "maxstay:conditional")
        if value:
            rules.extend(conditional(key, value))
            timed = True
    if base_restriction:
        rules.append(format_value("restriction", base_restriction) + (f" · {schedule(interval)}" if interval else ""))
        restricted = base_restriction in RESTRICTIONS
    # Numbered legacy rules carry independent times and limits.
    for number in ("", "2:", "3:"):
        value = legacy.get(number.rstrip(":")) if number else legacy.get("") or lane.get("condition")
        window = legacy.get(number + "time_interval") if number else interval
        maximum = legacy.get(number + "maxstay") if number else fields.get("maxstay") or legacy.get("maxstay") or lane.get("maxstay")
        suffix = " · " + schedule(window) if window else ""
        if value and (not timed or value not in ("free", "ticket") or window):
            rules.append(format_value("condition", value) + suffix)
            restricted |= value in RESTRICTIONS
            parking |= value in ("disc", "ticket", "free")
        if maximum:
            if "@" in maximum:
                rules.extend(conditional("maxstay", maximum))
                timed = True
            elif not fields.get("maxstay:conditional") and not legacy.get("maxstay:conditional"):
                rules.append(format_value("maxstay", maximum) + suffix)
                parking = True
        timed |= bool(window)
    for key in ("access", "fee", "authentication:ticket", "authentication:disc", "charge"):
        val = fields.get(key)
        if not val or fields.get(key + ":conditional"):
            continue
        if "@" in val:
            rules.extend(conditional(key, val))
            timed = True
        else:
            rules.append(format_value(key, val))
            restricted |= key == "access" and val in RESTRICTIONS
            parking |= key == "access" and val in ("yes", "public", "permissive")
    for use in SPECIAL:
        val = fields.get(use)
        if val in ("yes", "designated"):
            exclusive = val == "designated"
            rules.append(f"{readable(use).capitalize()} " + ("designated" if exclusive else "access recorded"))
            restricted |= exclusive
    for key in ("description", "maxstay:conditional:description", "note"):
        if fields.get(key):
            rules.append(fields[key])
    if fields.get("private"):
        rules.append("Access · " + readable(fields["private"]))
        restricted = True
    reason = fields.get("restriction:reason") or fields.get("reason") or legacy.get("reason")
    if reason:
        rules.append("Reason · " + readable(reason))
    if lane.get("no_stopping") == "tow-away":
        rules.append("Tow-away zone recorded")
    if fields.get("restriction:emergency"):
        rules.append("Emergency vehicles · " + format_value("restriction", fields["restriction:emergency"]))
    residents = fields.get("zone:residents") or legacy.get("residents")
    if residents:
        rules.append("Resident permit area " + residents)
    if fields.get("direction"):
        rules.append("Vehicle direction · " + readable(fields["direction"]))
    if position in POSITION:
        rules.append(POSITION[position])
        parking = True
    elif "@" in position:
        rules.extend(conditional("parking", position))
        timed = True
    orientation = fields.get("orientation") or next((k for k in ("parallel", "diagonal", "perpendicular") if k in lane), None)
    if orientation in ("parallel", "diagonal", "perpendicular"):
        rules.append(POSITION[orientation])
        parking = True
    if not rules:
        return None
    if not timed:
        rules.append("Sign hours unrecorded.")
    status = "mixed" if timed else "restricted" if restricted else "parking" if parking else "unknown"
    return status, list(dict.fromkeys(rules))


def direction(coords):
    start, end = coords[0], coords[-1]
    lat = math.radians(start[1])
    east, north = (end[0] - start[0]) * math.cos(lat), end[1] - start[1]
    bearing = math.degrees(math.atan2(east, north)) % 360
    for (x, y), (u, v) in zip(coords, coords[1:]):
        dx, dy = (u - x) * math.cos(lat), v - y
        if math.hypot(dx, dy) < 0.00002:
            continue
        if abs((math.degrees(math.atan2(dx, dy)) - bearing + 180) % 360 - 180) > 55:
            return None
    return ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")[int((bearing + 22.5) / 45) % 8]


def number(text):
    return int(text) if text and text.isdigit() else None


def side_records(tags, coords):
    bearing = direction(coords)
    geometry = {"type": "LineString", "coordinates": coords}
    for side in ("left", "right"):
        fields = effective(tags, side, "")
        lane = effective(tags, side, "lane:")
        legacy = effective(tags, side, "condition:")
        if not fields.get("") and tags.get("parking:lane") in ("both", side):
            fields[""] = "lane"
        if not (fields or lane or legacy) or fields.get("") == "separate":
            continue
        # Global parking tags can qualify explicitly mapped sides.
        for key in ("fee:conditional", "maxstay"):
            if tags.get("parking:" + key):
                fields.setdefault(key, tags["parking:" + key])
        if tags.get("parking:condition"):
            legacy.setdefault("", tags["parking:condition"])
        result = rule_summary(fields, legacy, lane)
        if not result:
            continue
        status, rules = result
        # Access restrictions on the road itself also apply to drivers
        # approaching these mapped spaces.
        road_access = next((tags[k] for k in ("motorcar", "motor_vehicle", "vehicle", "access") if k in tags), None)
        if road_access in ("private", "no", "permit", "customers", "destination"):
            rules.insert(0, {"private": "Private road access", "no": "Motor vehicle access prohibited",
                             "permit": "Road access requires a permit", "customers": "Customer road access",
                             "destination": "Road access for local destinations only"}[road_access])
            status = "restricted"
        # Shared capacity is not a per-side count.
        capacity = next((tags.get(k) for k in (f"parking:{side}:capacity", f"parking:condition:{side}:capacity",
                                              f"parking:lane:{side}:capacity") if tags.get(k)), None)
        yield {"name": tags.get("name") or tags.get("ref") or "Unnamed road", "geometry": geometry,
               "side": side, "status": status, "rules": rules, "spaces": number(capacity),
               "location": f"{side.title()} heading {bearing}" if bearing else f"{side.title()} side along mapped way"}


def bay_record(tags, coords):
    if len(coords) < 4 or coords[0] != coords[-1] or tags.get("access") in ("no", "private"):
        return
    rules = []
    access = tags.get("access")
    restricted = access in RESTRICTIONS
    if access not in ("yes", "public", "permissive"):
        rules.append(format_value("access", access) if access else "Public access unrecorded.")
    for key in ("fee", "charge", "maxstay", "access", "restriction"):
        if tags.get(key + ":conditional"):
            rules.extend(conditional(key, tags[key + ":conditional"]))
        elif key in ("fee", "charge", "maxstay") and tags.get(key):
            value = tags[key]
            rules.extend(conditional(key, value) if "@" in value else [format_value(key, value)])
    for key in ("disabled", "car_sharing", "charging"):
        count = tags.get("capacity:" + key)
        if count and count.isdigit() and int(count) > 0:
            rules.append(f"{count} {readable(key)} " + ("space" if int(count) == 1 else "spaces"))
            restricted |= count == tags.get("capacity")
    timed = any(k.endswith(":conditional") for k in tags) or any("@" in v for k,v in tags.items() if k in ("fee", "maxstay", "access"))
    if tags.get("opening_hours"):
        rules.append("Hours · " + schedule(tags["opening_hours"]))
    elif not timed:
        rules.append("Sign hours unrecorded.")
    status = "mixed" if timed else "restricted" if restricted else "parking" if access in ("yes", "permissive", "public") else "unknown"
    yield {"geometry": {"type": "Polygon", "coordinates": [coords]}, "side": None, "status": status,
           "name": tags.get("name") or tags.get("addr:street") or "Street-side parking",
           "location": "Mapped bay footprint", "rules": rules, "spaces": number(tags.get("capacity"))}


def approach_side(before, junction, after, toward):
    """Require the approach vector to be clearly on the same side of both road arms."""
    scale = math.cos(math.radians(junction[1]))
    dx = (toward[0] - junction[0]) * scale
    dy = toward[1] - junction[1]
    sides = []
    for a, b in ((before, junction), (junction, after)):
        rx, ry = (b[0] - a[0]) * scale, b[1] - a[1]
        length = math.hypot(dx, dy) * math.hypot(rx, ry)
        if not length:
            return None
        cross = (rx * dy - ry * dx) / length
        # Omit near-tangential approaches and ambiguous inside corners.
        if abs(cross) < 0.35:
            return None
        sides.append("left" if cross > 0 else "right")
    return sides[0] if sides[0] == sides[1] else None


def attach_driveways(pbf, roads):
    # Use only interior nodes. A driveway abutting a way endpoint may belong
    # to a different parking section or to a different street at a corner.
    nodes = {}
    for way, (ids, coords, sides) in roads.items():
        for n in range(1, len(ids) - 1):
            nodes[ids[n]] = (way, n) if ids[n] not in nodes else None
    entrances = defaultdict(dict)
    driveways = (osmium.FileProcessor(pbf).with_locations()
                 .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
                 .with_filter(osmium.filter.TagFilter(("service", "driveway"))))
    for obj in driveways:
        if obj.tags.get("highway") != "service" or obj.tags.get("area") == "yes" or len(obj.nodes) < 2:
            continue
        for end, neighbour in ((0, 1), (-1, -2)):
            node, next_node = obj.nodes[end], obj.nodes[neighbour]
            candidate = nodes.get(node.ref)
            if not candidate or not next_node.location.valid():
                continue
            way, index = candidate
            ids, coords, sides = roads[way]
            if next_node.ref in ids:
                continue
            toward = [round(next_node.lon, 7), round(next_node.lat, 7)]
            side = approach_side(coords[index - 1], coords[index], coords[index + 1], toward)
            if side in sides:
                entrances[node.ref].setdefault(side, {"point": coords[index], "toward": toward, "way": obj.id})
    if not entrances:
        return
    # Exclude intersections with another vehicle road. This ID-only pass
    # needs neither a geometry index nor a second copy of the road network.
    others = (osmium.FileProcessor(pbf, osmium.osm.WAY)
              .with_filter(osmium.filter.KeyFilter("highway")))
    for obj in others:
        if obj.tags.get("service") == "driveway" or obj.tags["highway"] in (
            "footway", "path", "cycleway", "steps", "bridleway", "crossing"):
            continue
        for node in obj.nodes:
            if node.ref in entrances and nodes[node.ref][0] != obj.id:
                del entrances[node.ref]
    for node, matches in entrances.items():
        sides = roads[nodes[node][0]][2]
        for side, entrance in matches.items():
            sides[side].setdefault("driveways", []).append(entrance)


def build(pbf, metro):
    with osmium.io.Reader(pbf) as reader:
        header = reader.header()
        timestamp = header.get("osmosis_replication_timestamp")
        box = header.box()
    if not timestamp or not box.valid():
        raise ValueError("PBF must declare a snapshot date and geographic bounds")
    bounds = metro.geometry.bounds
    if not (box.bottom_left.lon <= bounds[0] and box.bottom_left.lat <= bounds[1]
            and box.top_right.lon >= bounds[2] and box.top_right.lat >= bounds[3]):
        raise ValueError("PBF bounds do not cover Greater Sydney")
    data = []
    roads = {}
    processor = osmium.FileProcessor(pbf).with_locations().with_filter(osmium.filter.KeyFilter("highway", "amenity", "place"))
    for obj in processor:
        t = obj.tags
        if obj.is_node() and t.get("place") in ("suburb", "town", "city", "village") and t.get("name") in metro.search_points:
            metro.set_place(t["name"], [obj.location.lon, obj.location.lat])
        if not obj.is_way():
            continue
        road = t.get("highway") and any(tag.k.startswith("parking:") for tag in t)
        bay = t.get("amenity") == "parking" and t.get("parking") in BAY_TYPES
        if not (road or bay):
            continue
        coords = [[round(n.lon, 6), round(n.lat, 6)] for n in obj.nodes if n.location.valid()]
        if len(coords) < 2 or len(coords) != len(obj.nodes):
            continue
        line = LineString(coords)
        if not metro.prepared.covers(line):
            continue
        mid = line.interpolate(.5, normalized=True)
        area = metro.locality(mid) or "Greater Sydney"
        records = side_records(dict(t), coords) if road else bay_record(dict(t), coords)
        sides = {}
        for record in records:
            locality = area
            if record["side"] is not None:
                # A road can form the suburb boundary. Look a few metres
                # toward this side when assigning its search locality.
                delta = min(0.00002, line.length / 4)
                a, b = (line.interpolate(line.length / 2 + offset) for offset in (-delta, delta))
                scale = math.cos(math.radians(mid.y))
                dx, dy = (b.x - a.x) * scale, b.y - a.y
                magnitude = math.hypot(dx, dy)
                if magnitude:
                    normal = (1 if record["side"] == "left" else -1) * 0.00003 / magnitude
                    target = Point(mid.x - dy * normal / scale, mid.y + dx * normal)
                    locality = metro.locality(target) or area
            suffix = "-" + record["side"] if record["side"] else "-bay"
            record.update(id=f"osm-section-way-{obj.id}{suffix}", kind="section", source="osm",
                          area=locality, url=f"https://www.openstreetmap.org/way/{obj.id}")
            data.append(record)
            if road:
                sides[record["side"]] = record
        if sides:
            roads[obj.id] = ([n.ref for n in obj.nodes], coords, sides)
    attach_driveways(pbf, roads)
    if not data or len({f["id"] for f in data}) != len(data):
        raise ValueError("Empty or duplicate Greater Sydney parking records")
    return {"retrieved": date.today().isoformat(), "sources": {"osm": {
        "name": "OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright",
        "license": "ODbL 1.0", "licenseUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
        "extractUrl": PBF, "fileDate": timestamp[:10],
        "note": "Community-mapped road sides and bay footprints. Driveway markers use shared map nodes with driveway entrances. Widths and unmapped entrances are unknown.",
        "boundary": "Australian Bureau of Statistics · Greater Sydney GCCSA 1GSYD and SAL 2026 · CC BY 4.0",
        "boundaryUrl": GCCSA, "localityUrl": SAL
    }}, "features": data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pbf", type=Path, help=PBF)
    parser.add_argument("--cache", type=Path, help="Local cache for ABS geographic data")
    args = parser.parse_args()
    metro = Metro(args.cache or args.pbf.parent)
    result = build(args.pbf, metro)
    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(OUTPUT)
    metro.write_index()
    print(f"Wrote {len(result['features'])} Greater Sydney parking sides and bay footprints")


if __name__ == "__main__":
    main()
