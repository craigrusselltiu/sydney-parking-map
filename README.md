# Kerb Atlas

[Open the Greater Sydney parking map](https://craigrusselltiu.github.io/sydney-parking-map/)

Hover or tap a coloured line to read the rules recorded for that side of the street. Open a car park to see its published capacity, opening hours or live availability link where supplied. The map starts at street level in Hornsby. The Greater Sydney menu includes Penrith, Campbelltown, the Sydney CBD and a regional overview. Search also supports 938 suburbs and localities. The theme button switches the map and interface between dark and light. Theme and saved locations stay in the browser.

## Coverage and accuracy

- **Geography.** The regional datasets use the Australian Bureau of Statistics 2026 Greater Sydney boundary (GCCSA 1GSYD). Coverage varies by suburb. [ABS boundary](https://geo.abs.gov.au/arcgis/rest/services/ASGS2026/GCCSA/MapServer/0)
- **Road sides.** OpenStreetMap records supply original road geometry and separate left/right rules. A visual offset identifies the recorded side. Bay polygons have their own footprint. Green means parking was mapped there, amber indicates conditions, red indicates a recorded restriction and grey indicates unverified details. A colour does not establish permission at the current time. Hours are shown only where recorded. [OpenStreetMap data](https://www.openstreetmap.org/copyright)
- **Council kerb lines.** Waverley Council's 2021 survey supplies 2,373 kerb sections with sign text and street side. The importer excludes all 7,623 rows marked “no parking data”, including rows with a placeholder “No parking” value. Updated upload dates do not make an older survey current. [Council dataset](https://opendata.transport.nsw.gov.au/dataset/waverley-council-data)
- **Driveways.** Tagged access routes appear at close zoom. Where a driveway shares a mapped node with a tagged road side, a contrasting break marks the connection. The line width is cartographic. Unrecorded driveways, driveway widths and temporary restrictions still need checking on site.
- **Car parks.** Listings combine operators, councils, Transport for NSW Park&Ride and explicitly public OpenStreetMap facilities. Source dates appear on each record. Capacity can mean all spaces or standard bays as labelled. Park&Ride listings link to TfNSW's current availability. [Transport Park&Ride](https://transportnsw.info/travel-info/ways-to-get-around/drive/parking/transport-parkride-car-parks)
- **Other layers.** City of Sydney mobility bay locations and 278 historical loading zones are optional. The loading-zone source file dates to 2018. [Council mobility data](https://www.arcgis.com/home/item.html?id=2671fdce3f354b3e8f02236ca12271cb) · [Loading-zone survey](https://opendata.transport.nsw.gov.au/dataset/loading-zones-kerbside)

Campbelltown has mapped car parks. Public on-street rules remain particularly sparse there. TfNSW announced the decommissioning of its original on-street parking feed after the vendor stopped providing live observations. A blank kerb is unknown. [TfNSW service notice](https://opendataforum.transport.nsw.gov.au/t/on-street-parking-api/4020)

## Hosting and local use

GitHub Pages serves the static files from **main → /docs**. The parking overlays use local snapshots. The regional overview and detail tiles around Hornsby, Penrith, Campbelltown and central Sydney are bundled. Other detailed basemap tiles load from OpenFreeMap on demand. The app needs no account, API key or backend. Browsers without WebGL can use the parking directory.

To run locally, use:

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory docs
```

Open [the local map](http://127.0.0.1:8000/).

## Refreshing data

Download the [NSW OpenStreetMap extract](https://download.geofabrik.de/australia-oceania/australia/new-south-wales.html). The regional importers clip it to Greater Sydney and share a local cache of official ABS polygons. Review changes in counts, source dates and coverage before committing a refresh.

```sh
python -m pip install osmium shapely pyshp pyproj
python scripts/street_sections.py /path/to/new-south-wales-latest.osm.pbf --cache /path/to/abs-cache
python scripts/garages.py /path/to/new-south-wales-latest.osm.pbf --cache /path/to/abs-cache
python scripts/waverley.py
python scripts/kerbs.py
python scripts/basemap.py
```

The street, garage, suburb and council snapshots carry their own attribution and licences. MapLibre GL JS and the DM Sans font retain their licences in the assets directory. [Basemap credits](docs/assets/basemap/CREDITS.md)
