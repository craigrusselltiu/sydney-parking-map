"""Greater Sydney off-street parking imports. Uses the same extract and boundary as the street layer."""

from collections import defaultdict
from datetime import date
import json
import re
from urllib.request import Request, urlopen

import osmium
from shapely import STRtree, from_wkb, union_all
from shapely.geometry import Point, Polygon


PARK_RIDE_PAGE = "https://transportnsw.info/travel-info/ways-to-get-around/drive/parking/transport-parkride-car-parks"
PARK_RIDE_DATA = "https://opendata.transport.nsw.gov.au/data/dataset/car-park-api"
PENRITH = "https://www.penrithcity.nsw.gov.au/services/other-services/parking/penrith-city-centre-parking-map"
CAMPBELLTOWN = "https://www.campbelltown.nsw.gov.au/Services-and-Facilities/Campbelltown-Station-Commuter-Car-Park"
HORNSBY = "https://www.hornsby.nsw.gov.au/files/assets/public/v/2/council/forms-and-publications/publications/strategies-and-plans/documents/hornsby-car-parking-study-part-c.pdf"
WAVERLEY = "https://www.waverley.nsw.gov.au/residents/parking/car_parks"
WAVERLEY_DATA = "https://opendata.transport.nsw.gov.au/data/dataset/waverley-council-data"
MAP_TYPES = {"surface": "Surface car park", "multi-storey": "Multi-storey car park",
             "underground": "Underground car park", "rooftop": "Rooftop car park"}
OSM = "OpenStreetMap contributors"
OSM_LICENSE = "© OpenStreetMap contributors · ODbL 1.0"
# Access is ambiguous or misleading at these locations. The Central station
# forecourt is for pickup/dropoff (TfNSW Central station area guide). Other
# lots are connected to venues with customer/member access conditions.
VENUE_LOTS = {"relation/5691879", "node/5746285473", "way/678330321",
              "way/5232632", "way/15674942", "way/352918475", "relation/7966369"}


def park_and_ride(metro):
    # Same public fields used in the official website's car park widget.
    # An inventory snapshot stores locations and standard bays only. Vacancies
    # are highly time-sensitive and are best read on Transport's current page.
    query = "query { widgets { pnrLocations { id name spots location { suburb address latitude longitude } } } }"
    request = Request("https://transportnsw.info/api/graphql", method="POST",
                      data=json.dumps({"query": query}).encode(),
                      headers={"Content-Type": "application/json", "User-Agent": "SydneyParkingMap/1.0"})
    with urlopen(request, timeout=30) as response:
        locations = json.load(response)["data"]["widgets"]["pnrLocations"]
    if not locations:
        raise ValueError("No Park&Ride locations returned")
    for r in locations:
        where = r["location"]
        lat, lon = where["latitude"], where["longitude"]
        if not metro.prepared.covers(Point(lon, lat)):
            continue
        yield {
            "id": f"tfnsw-parkride-{r['id']}", "name": r["name"], "lat": lat, "lon": lon,
            "address": f"{where['address']}, {where['suburb']}", "suburb": where["suburb"],
            "source": "Transport for NSW", "url": PARK_RIDE_PAGE, "locationUrl": PARK_RIDE_PAGE,
            "capacity": r["spots"], "capacityKind": "standard bays", "capacityUrl": PARK_RIDE_DATA,
            "capacitySource": "Transport for NSW · standard bays", "availabilityUrl": PARK_RIDE_PAGE,
            "conditions": ["Up to 18 hours free with an eligible public transport trip. Other stays incur a fee."],
            "hours": None, "reviewed": date.today().isoformat(),
        }


def council_listings(fetch):
    # Published Waverley CarParks.shp point records 0–2 (EPSG:28356 → 4326).
    # Current public access, entrances, hours and holiday closures come from
    # council's car parks page. The dated count remains explicitly attributed.
    waverley = (
        ("eastgate", "Eastgate Car Park", -33.893256, 151.247684, "Ebley Street or Newland Street", 896, "11:30 pm"),
        ("library", "Waverley Library Car Park", -33.893000, 151.245302, "Ebley Street", 120, "11 pm"),
        ("hollywood", "Hollywood Avenue Car Park", -33.892570, 151.252669, "Waverley Street", 173, "11 pm"),
    )
    for slug, name, lat, lon, address, capacity, closing in waverley:
        yield {"id": "waverley-" + slug, "name": name, "lat": lat, "lon": lon,
               "address": address + ", Bondi Junction", "source": "Waverley Council", "url": WAVERLEY,
               "locationUrl": WAVERLEY_DATA, "capacity": capacity, "capacityUrl": WAVERLEY_DATA,
               "capacitySource": "Waverley Council · 2023 open data release",
               "hours": f"5 am–{closing} daily, except Good Friday, Easter Sunday and Christmas Day",
               "reviewed": "2026-11-19"}
    # The public facility snapshot includes time-specific zones of the same car
    # park as separate polygons. Group them by name and place one marker inside.
    html = fetch(PENRITH)
    permanent = {"Allen Place car park", "Civic Centre car park", "Edwards Place car park",
                 "Judges Place car park", "Masters Place car park", "Woodriff St car park",
                 "The Broadway car park", "Union Road (central) car park",
                 "Union Road (east) car park", "Union Road (west)"}
    pieces = defaultdict(list)
    for coords, name in re.findall(r"points:\s*\[([^\]]+)\],\s*id:\s*[^,]+,\s*categoryid:\s*[^,]+,\s*title:\s*'([^']+)'", html):
        if name in permanent:
            points = [(float(lon), float(lat)) for lat, lon in re.findall(r"LatLng\(([-\d.]+),\s*([-\d.]+)\)", coords)]
            pieces[name].append(Polygon(points))
    if not pieces:
        raise ValueError("Penrith City Council map has no recognised facilities")
    for name, polygons in pieces.items():
        p = union_all(polygons).representative_point()
        yield {
            "id": "penrith-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "name": name, "lat": round(p.y, 6), "lon": round(p.x, 6), "address": "Penrith",
            "source": "Penrith City Council", "url": PENRITH, "locationUrl": PENRITH,
            "capacity": None, "reviewed": "2026-11-19",
        }
    # This council facility is separate from TfNSW's Farrow Road (north)
    # and Hurley Street Park&Ride stations. The figure includes both structures.
    yield {"id": "campbelltown-council-farrow", "name": "Campbelltown Station Commuter Car Park",
           "lat": -34.063809, "lon": 150.813054, "address": "Farrow Road, Campbelltown",
           "source": "Campbelltown City Council", "url": CAMPBELLTOWN, "locationUrl": CAMPBELLTOWN,
           "hours": "24 hours daily", "capacity": 946, "capacitySource": "Campbelltown City Council",
           "conditions": ["Ground floor: 6 hours free. Upper levels and outdoor spaces: 18 hours free. Overstay fees apply."],
           "capacityUrl": CAMPBELLTOWN, "reviewed": "2026-11-19"}
    yield {"id": "hornsby-dural-street", "name": "Dural Street Car Park",
           "lat": -33.703109, "lon": 151.096565, "address": "1–3 Dural Street, Hornsby",
           "source": "Hornsby Shire Council", "url": HORNSBY,
           "locationSource": OSM_LICENSE, "locationUrl": "https://www.openstreetmap.org/way/209937098",
           "capacity": 49, "capacitySource": "Hornsby Shire Council · car parking management study",
           "capacityUrl": HORNSBY, "reviewed": "2026-11-19"}


def public_off_street(tags):
    if tags.get("access") not in {"yes", "public"} or tags.get("parking") not in MAP_TYPES:
        return False
    for key in ("access", "vehicle", "motor_vehicle", "motorcar"):
        if tags.get(key, "yes") not in {"yes", "public"} or key + ":conditional" in tags:
            return False
    if any(tags.get(k, "no") != "no" for k in ("kiss_ride", "disabled_only", "access:permit", "seasonal", "access:customers")):
        return False
    if "restriction:conditional" in tags:
        return False
    if tags.get("capacity") and any(tags["capacity"] == tags.get("capacity:" + kind)
                                    for kind in ("disabled", "bus", "hgv", "motorcycle")):
        return False
    labels = " ".join(tags.get(k, "") for k in ("name", "description", "access:description"))
    return not re.search(r"\b(private|staff|employees?|residents?|customers? only|visitor parking|visitors? only|permit holders?|"
                         r"students? parking|disabled parking|truck parking|RSL parking|"
                         r"loading (?:dock|zone)|pick.?up|drop.?off|kiss.{0,5}ride)\b", labels, re.I)


def inventory(pbf, metro):
    factory = osmium.geom.WKBFactory()
    processor = osmium.FileProcessor(str(pbf)).with_areas().with_filter(osmium.filter.TagFilter(("amenity", "parking")))
    stamp = processor.header.get("osmosis_replication_timestamp")
    if not stamp:
        raise ValueError("A dated Geofabrik extract is required")
    rows = []
    for obj in processor:
        if not (obj.is_node() or obj.is_area()):
            continue
        tags = dict(obj.tags)
        if not public_off_street(tags):
            continue
        if obj.is_node():
            ref = f"node/{obj.id}"
            footprint = point = Point(obj.location.lon, obj.location.lat)
        else:
            ref = ("way/" if obj.from_way() else "relation/") + str(obj.orig_id())
            footprint = from_wkb(factory.create_multipolygon(obj))
            point = footprint.representative_point()
        if ref in VENUE_LOTS or not metro.prepared.covers(point):
            continue
        suburb = metro.locality(point) or "Greater Sydney"
        address = " ".join(tags.get(k, "") for k in ("addr:housenumber", "addr:street")).strip()
        name = tags.get("name") or MAP_TYPES[tags["parking"]]
        url = f"https://www.openstreetmap.org/{ref}"
        row = {"id": "osm-" + ref.replace("/", "-"), "name": name,
               "lat": round(point.y, 6), "lon": round(point.x, 6), "suburb": suburb,
               "address": f"{address}, {suburb}" if address else suburb, "communityMapped": True,
               "source": OSM, "url": url, "locationUrl": url, "asOf": stamp[:10], "capacity": None}
        if tags.get("capacity", "").isdecimal() and int(tags["capacity"]) > 0:
            row.update(capacity=int(tags["capacity"]), capacitySource=OSM, capacityUrl=url)
        if tags.get("opening_hours") == "24/7":
            row["hours"] = "24 hours daily (community mapped)"
        elif tags.get("opening_hours"):
            row["hours"] = tags["opening_hours"]
        # Keep source-specified limits and fees so an access=yes feature never
        # silently loses a stay-duration restriction during import.
        details = []
        for k, label in (("maxstay", "Maximum stay"), ("maxstay:conditional", "Conditional maximum stay"),
                         ("fee:conditional", "Conditional fee"), ("charge", "Charge")):
            if k in tags:
                details.append(f"{label} · {tags[k]}")
        if tags.get("fee") == "yes":
            details.append("Parking fee applies")
        if details:
            row["conditions"] = details
        rows.append((row, footprint))
    return rows, stamp[:10]


def normal_name(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(car ?parks?|parking|park.?ride)\b", "", name.lower()))


def add_nearby_roads(rows, pbf):
    # Map context only. A nearest named road is not a verified vehicle entry.
    items = [row for row in rows if row["address"] == row["suburb"]]
    if not items:
        return
    points = [Point(row["lon"], row["lat"]) for row in items]
    tree = STRtree(points)
    factory = osmium.geom.WKBFactory()
    nearest = {}
    roads = {"motorway", "trunk", "primary", "secondary", "tertiary",
             "unclassified", "residential", "living_street", "service"}
    processor = (osmium.FileProcessor(str(pbf)).with_locations()
                 .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
                 .with_filter(osmium.filter.KeyFilter("highway")).with_filter(osmium.filter.KeyFilter("name")))
    for way in processor:
        if way.tags["highway"] not in roads or len(way.nodes) < 2:
            continue
        line = from_wkb(factory.create_linestring(way))
        for i in tree.query(line, predicate="dwithin", distance=0.0011):
            distance = line.distance(points[i])
            if i not in nearest or distance < nearest[i][0]:
                nearest[i] = (distance, way.tags["name"])
    for i, (_, road) in nearest.items():
        items[i]["address"] = f"Near {road}, {items[i]['suburb']}"


def merged_inventory(candidates, verified):
    known_points = [Point(v["lon"], v["lat"]) for v in verified]
    known_tree = STRtree(known_points)
    known_urls = {v.get("locationUrl") for v in verified}
    areas = [(r, g) for r, g in candidates if g.geom_type != "Point"]
    area_tree = STRtree([g for _, g in areas])
    result = []
    named_points = defaultdict(list)
    for row, geometry in candidates:
        if row["url"] in known_urls:
            continue
        point = Point(row["lon"], row["lat"])
        # Strong spatial evidence for a curated marker at or within a lot.
        if len(known_tree.query(geometry, predicate="dwithin", distance=0.00020)):
            continue
        name = normal_name(row["name"])
        neighbours = known_tree.query(point, predicate="dwithin", distance=0.00165)
        if name and any(name == normal_name(verified[i]["name"]) or
                        (len(name) >= 7 and name in normal_name(verified[i]["name"])) for i in neighbours):
            continue
        if geometry.geom_type == "Point":
            # Area + POI representations of one car park are common. Suppress
            # a point only if it lies within an accepted parking footprint.
            if len(area_tree.query(geometry, predicate="intersects")):
                continue
            if row["name"] not in MAP_TYPES.values():
                if any(p.distance(point) < 0.00045 for p in named_points[name]):
                    continue
                named_points[name].append(point)
        result.append(row)
    return result
