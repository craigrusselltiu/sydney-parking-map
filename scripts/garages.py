"""Refresh the Sydney garage directory from reviewed and community-mapped sources.

The allowlist contains public hourly facilities reviewed on 19 November 2026.
Recheck venue facts and dated capacity references before changing REVIEWED.
An incomplete upstream response leaves the previous snapshot in place.
"""

import json
import re
import argparse
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
from shapely.geometry import Point

from metro_geography import Metro, SOURCE as GEOGRAPHY
from metro_garages import PARK_RIDE_DATA, add_nearby_roads, council_listings, park_and_ride, inventory, merged_inventory


OUTPUT = Path(__file__).resolve().parents[1] / "docs/data/garages.json"
REVIEWED = "2026-11-19"
WILSON = "https://www.wilsonparking.com.au/parking-locations/new-south-wales/"
SECURE = "https://www.secureparking.com.au/en-au/car-parks/australia/nsw/"
CITY = "https://services1.arcgis.com/cNVyNtjGVZybOQWZ/arcgis/rest/services/Council_car_parks/FeatureServer/0"
ICC = "https://iccsydney.com.au/about/venue-information/accessibility-and-inclusion-for-visitors/parking-and-public-transport/"
ICC_GPS = "https://iccsydney.com.au/wp-content/uploads/2023/05/iccsydney-event-guidelines.pdf"
OPERA = "https://www.sydneyoperahouse.com/visit/getting-here/parking"
QVB = "https://www.vicinity.com.au/assets/sb/f/129601/x/6e463c95a7/fy25-annual-results-property-book.pdf#page=17"
METRO = ("https://jcgjv.com.au/wordpress/wp-content/uploads/2025/06/"
         "SMWSTETP-JCG-SWD-SN000-TF-PLN-002043-Constrution-Parking-Access-Strategy_Stage-1_Rev-09-Approved_Redacted-1.pdf#page=47")
METRO_LABEL = "Eastern Tunnelling Package · April 2025 report, table 12"

# Stable operator listings with public hourly parking. Counts with a separate
# source are explicitly dated where they come from a report.
LISTINGS = {
    "sydney-cbd/sydney-opera-house-car-park-2A-macquarie-st-sydney": (1200, "Sydney Opera House", OPERA),
    "cbd-sydney-south/queen-victoria-building-car-park": (669, "Vicinity Centres · June 2025 property report", QVB),
    "sydney-cbd/1-bligh-st-car-park": (91, METRO_LABEL, METRO),
    "sydney-cbd/no.-1-oconnell-st-car-park": (95, METRO_LABEL, METRO),
    "sydney-cbd/20-bond-st": (150, METRO_LABEL, METRO),
    "sydney-cbd/259-george-st-car-park": (201, METRO_LABEL, METRO),
    "sydney-cbd/angel-place-car-park-123-pitt-st-sydney": (260, METRO_LABEL, METRO),
    "sydney-cbd/australia-square-car-park-bond-st-sydney": (385, METRO_LABEL, METRO),
    "sydney-cbd/60-elizabeth-st-car-park": (250, METRO_LABEL, METRO),
    "sydney-cbd/gateway-car-park": (93, METRO_LABEL, METRO),
    "sydney-cbd/25-martin-place-car-park": None,
    "sydney-cbd/st-andrews-house-town-hall-car-park": None,
    "sydney-cbd/quay-west-car-park-111-harrington-st-sydney": None,
    "sydney-cbd/the-domain-car-park": None,
    "cbd-sydney-south/market-city-car-park": None,
    "darling-harbour/harbourside-car-park": None,
    "darling-harbour/darling-park-car-park": None,
    "cbd-sydney-north/1-farrer-car-park": (654, METRO_LABEL, METRO),
    "cbd-sydney-north/6-10-oconnell-st-car-park": (108, METRO_LABEL, METRO),
    "cbd-sydney-north/atrium-car-park-u60": (61, "Eastern Tunnelling Package · April 2025 report, table 11", METRO.replace("page=47", "page=46")),
    "cbd-sydney-north/barangaroo-reserve-car-park": (300, "Barangaroo", "https://www.barangaroo.com/getting-here/related-pages/parking"),
    "eastern-suburbs/st-margarets": None,
    "cbd-sydney-south/383-kent-st-car-park": None,
}

# These named OSM facilities were matched to independent public-access
# evidence after clipping the 14 Nov 2026 BBBike Sydney extract to the
# City of Sydney LGA. Unnamed, ambiguous and duplicate markers were omitted.
# A point inside a mapped building represents the facility, not its driveway.
OSM_PARKS = {
    "node/1333106686": ("261–293 Kent Street, Sydney", "King Street Wharf",
                        "https://kingstreetwharf.com.au/getting-here/"),
    "node/11233060393": ("100 Bathurst Street, Sydney", "Meriton",
                         "https://www.meriton.com.au/parking/meriton-parking-pitt-street-sydney/"),
    "way/196621009": ("521 Kent Street, Sydney", "Centro Parking",
                      "https://www.centroparking.com.au/syd-cinema-centre-car-park"),
    "way/46205383": ("Shepherd Street at Cleveland Street, Darlington", "Seymour Centre",
                     "https://www.seymourcentre.com/visit/location-transport/"),
}

FIRST_PARKS = {
    "528-kent-street": ("528 Kent Street Car Park", "528 Kent Street, Sydney"),
    "darling-square": ("Darling Square Car Park", "Zollner Circuit, Haymarket"),
    "darling-quarter": ("Darling Quarter Car Park", "1–25 Harbour Street, Sydney"),
}


def fetch(url):
    request = Request(url, headers={"User-Agent": "SydneyParkingMap/1.0 (public parking directory)"})
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def facility(key, name, lat, lon, address, source, url, hours, capacity, location_url=None):
    if not (-34 < lat < -33.8 and 151.1 < lon < 151.3 and address and name):
        raise ValueError(f"Invalid Sydney location for {key}")
    return {
        "id": key, "name": name, "lat": round(lat, 6), "lon": round(lon, 6),
        "address": address, "hours": hours, "source": source, "url": url,
        "locationUrl": location_url or url, "reviewed": REVIEWED,
        "capacity": capacity[0] if capacity else None,
        "capacitySource": capacity[1] if capacity else None,
        "capacityUrl": capacity[2] if capacity else None,
        "occupancy": None,
    }


def wilson_facilities():
    days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    for path, capacity in LISTINGS.items():
        url = WILSON + path + "/"
        html = fetch(url)
        blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.I | re.S)
        items = [json.loads(block) for block in blocks]
        data = next((item for item in items if isinstance(item, dict) and item.get("@type") == "ParkingFacility"), None)
        if not data or not re.search(r'>\s*hourly\s*<|casual hourly', html, re.I):
            raise ValueError(f"Review public hourly access for {url}")
        schedule = data.get("openingHoursSpecification") or []
        all_day = {s.get("dayOfWeek") for s in schedule if (s.get("opens"), s.get("closes")) == ("00:00", "23:59")}
        hours = "24 hours daily" if len(schedule) == 7 and all_day == days else None
        yield facility(
            path.split("/")[-1], data["name"], data["geo"]["latitude"], data["geo"]["longitude"],
            data["address"]["streetAddress"], "Wilson Parking", url, hours, capacity,
        )


def council_facilities():
    data = json.loads(fetch(CITY + "/query?where=1%3D1&outFields=*&outSR=4326&f=geojson"))
    parks = {row["properties"]["CarParkName"]: row for row in data["features"]}
    expected = {
        "Goulburn Street Car Park": ("goulburn-street-sydney-car-park", "101 Goulburn Street, Haymarket", None),
        "Kings Cross Car Park": ("kings-cross-elizabeth-bay-car-park", "Ward Avenue, Elizabeth Bay", 383),
    }
    for name, (slug, address, spaces) in expected.items():
        lon, lat = parks[name]["geometry"]["coordinates"]
        url = SECURE + slug + "/"
        yield facility(
            slug, name, lat, lon, address, "Secure Parking", url, "24 hours daily",
            (spaces, "Secure Parking", url) if spaces else None, CITY,
        )


def first_parking_facilities():
    for slug, (name, address) in FIRST_PARKS.items():
        url = f"https://www.firstparking.com.au/locations/{slug}/"
        html = fetch(url)
        point = re.search(r"id=['\"]map['\"]\s+data-lat=['\"](-?[\d.]+)['\"]\s+data-lng=['\"]([\d.]+)", html)
        count = re.search(r">\s*([\d,]+) Spaces\s*<", html, re.I)
        if not point or not count or "flat rate" not in html.lower():
            raise ValueError(f"Review current public parking listing for {url}")
        spaces = int(count[1].replace(",", ""))
        yield facility(slug, name, float(point[1]), float(point[2]), address,
                       "First Parking", url, None, (spaces, "First Parking", url))


def osm_facilities():
    for ref, (address, publisher, page) in OSM_PARKS.items():
        kind, identifier = ref.split("/")
        suffix = "/full.json" if kind == "way" else ".json"
        elements = json.loads(fetch(f"https://api.openstreetmap.org/api/0.6/{ref}{suffix}"))["elements"]
        item = next(e for e in elements if e["type"] == kind and e["id"] == int(identifier))
        tags = item.get("tags", {})
        vehicle_access = ("access", "vehicle", "motor_vehicle", "motorcar")
        if (tags.get("amenity") != "parking" or tags.get("access") != "yes"
                or any(tags.get(key, "yes") != "yes" or key + ":conditional" in tags for key in vehicle_access)):
            continue
        if kind == "way":
            # Both reviewed building footprints are compact and convex.
            nodes = {e["id"]: e for e in elements if e["type"] == "node"}
            vertices = [nodes[n] for n in dict.fromkeys(item["nodes"])]
            lat = sum(n["lat"] for n in vertices) / len(vertices)
            lon = sum(n["lon"] for n in vertices) / len(vertices)
        else:
            lat, lon = item["lat"], item["lon"]
        osm_url = f"https://www.openstreetmap.org/{ref}"
        count = tags.get("capacity", "")
        capacity = (int(count), "OpenStreetMap contributors", osm_url) if count.isdecimal() else None
        hours = "24 hours daily" if tags.get("opening_hours") == "24/7" else None
        entry = facility("osm-" + ref.replace("/", "-"), tags["name"], lat, lon, address,
                         publisher, page, hours, capacity, location_url=osm_url)
        entry["locationSource"] = "© OpenStreetMap contributors · ODbL 1.0"
        if ref == "way/46205383":
            entry["occupancyNote"] = "Seymour Centre reports this car park often fills during university semesters, particularly for weekday matinees."
        yield entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pbf", type=Path, help="Geofabrik New South Wales .osm.pbf extract")
    parser.add_argument("--cache", type=Path, help="Directory for ABS GCCSA and locality polygons (default: alongside PBF)")
    args = parser.parse_args()
    metro = Metro(args.cache or args.pbf.parent)
    features = [*wilson_facilities(), *council_facilities(), *first_parking_facilities(), *osm_facilities()]
    # Entrance coordinates from section 3.1 of ICC Sydney's event guidelines.
    features.append(facility(
        "icc-exhibition-centre", "ICC Exhibition Centre · Car Park 1",
        -(33 + 52/60 + 30.28/3600), 151 + 11/60 + 55.58/3600,
        "14 Darling Drive, Darling Harbour", "ICC Sydney", "https://iccsydney.com.au/visitors/getting-here/",
        "24 hours daily", (620, "ICC Sydney", ICC), ICC_GPS,
    ))
    features.extend(council_listings(fetch))
    features.extend(park_and_ride(metro))
    for r in features:
        point = Point(r["lon"], r["lat"])
        if not metro.prepared.covers(point):
            raise ValueError(f"Outside the Greater Sydney boundary: {r['name']}")
        r.setdefault("suburb", metro.locality(point))
    candidates, extract_date = inventory(args.pbf, metro)
    community = merged_inventory(candidates, features)
    add_nearby_roads(community, args.pbf)
    features.extend(community)
    sources = [
        {"name": "City of Sydney · Council car parks", "url": CITY, "license": "CC BY 4.0",
         "licenseUrl": "https://creativecommons.org/licenses/by/4.0/"},
        {"name": "Operator, venue and project publications", "url": OPERA,
         "license": "Individual factual references linked on each facility."},
        {"name": "© OpenStreetMap contributors · selected location and tag records",
         "url": "https://www.openstreetmap.org/copyright", "license": "ODbL 1.0",
         "licenseUrl": "https://opendatacommons.org/licenses/odbl/1-0/", "extractDate": extract_date,
         "download": "https://download.geofabrik.de/australia-oceania/australia/new-south-wales.html"},
        {"name": "Transport for NSW · Park&Ride", "url": PARK_RIDE_DATA, "license": "Creative Commons Attribution",
         "licenseUrl": "https://opendata.transport.nsw.gov.au/data/licence"}, GEOGRAPHY,
    ]
    payload = {"updated": REVIEWED, "retrieved": date.today().isoformat(), "sources": sources,
               "features": sorted(features, key=lambda f: f["name"])}
    OUTPUT.parent.mkdir(exist_ok=True, parents=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=OUTPUT.parent, delete=False) as temp:
        json.dump(payload, temp, ensure_ascii=False, separators=(",", ":"))
        temp.write("\n")
    Path(temp.name).replace(OUTPUT)
    print(f"Wrote {len(features)} public car parks with {sum(f['capacity'] is not None for f in features)} documented capacities")
    print(f"{len(community)} community-mapped car parks after deduplication")


if __name__ == "__main__":
    main()
