# Kerb Atlas

A free, static parking map for the City of Sydney. Search a street, suburb or facility, then hover or tap a map feature to see its source and parking details. Bookmarks stay in the browser. The optional location button uses the device's location to centre the map.

## Run locally

From this directory, run:

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory docs
```

Open [the map](http://127.0.0.1:8000/). The site uses MapLibre GL JS, local vector tiles, a local font and three small parking data files. No build, API key or backend is required. Browsers without WebGL can still use the searchable directory.

## GitHub Pages

Push this repository to GitHub and set **Settings → Pages → Deploy from a branch → main → /docs**. The checked-in files use relative paths, including map tiles and fonts, so the site can run under a repository subpath. Changes to `docs/` deploy through Pages.

## Coverage

| Layer | What the map shows | Accuracy boundary |
| --- | --- | --- |
| Council meters | 1,375 meter locations with published tariff periods, fees, maximum stays and approximate bay counts where supplied | Meter hours apply at the machine. The records do not identify every sign boundary or determine permission outside the published hours. |
| Street sections | 50 road sections with explicit mapped conditions and 7 street-side bay locations | A line follows the mapped road centre. Rules identify the side and direction where recorded. Community coverage is sparse. |
| Mobility | 365 locations, with council audit dates and sign text where recorded | Some audits date to 2017. Verify the current signs. |
| Driveways | Explicitly tagged driveway access routes at close zoom | Road lines do not measure the width of a kerb opening. More entrances exist on the ground. |
| Public car parks | 33 operator- or venue-checked facilities, 20 with sourced total capacities | Figures can come from dated reports. No live or hourly vacancy series is available in this release. |
| Historical loading zones | 278 polygons from a 2018 TfNSW source file | This optional layer is off by default. Use it as a historical reference. |

The initial parking snapshots were retrieved on 19 November 2026. Source links appear on each record. A blank area has unknown coverage. Meter totals and mapped bays can refer to the same physical space, so their counts must not be added to estimate citywide capacity.

A complete parking-permission map would need a maintained inventory of sign panels, arrows, kerb endpoints, driveway openings, temporary controls and field verification. Live vacancies and typical occupancy need facility-specific feeds or observations with timestamps. The publicly documented NSW occupancy API covers selected Transport Park&Ride facilities. [NSW Car Park API](https://opendata.transport.nsw.gov.au/dataset/car-park-api)

## Refresh the snapshots

Run a script from the repository root, review its output and changes in source dates and counts, then commit the updated snapshot. Dates on historical observations and reports remain distinct from retrieval dates.

- `python scripts/kerbs.py` fetches City of Sydney meter and mobility records and the TfNSW loading-zone archive. [Meters](https://www.arcgis.com/home/item.html?id=71bb12507a3240c4b12e7fbba5be58e1) · [Mobility bays](https://www.arcgis.com/home/item.html?id=2671fdce3f354b3e8f02236ca12271cb) · [Loading zones](https://opendata.transport.nsw.gov.au/dataset/loading-zones-kerbside)
- `python scripts/street_sections.py /path/to/Sydney.osm.pbf` builds the attributed ODbL street section extract. Install Python packages `osmium` and `shapely` for this script. It uses the City of Sydney boundary and explicitly tagged restrictions. [Sydney OSM extract](https://download.bbbike.org/osm/bbbike/Sydney/)
- `python scripts/garages.py` refreshes the curated public car park directory. Recheck operator listings and capacity evidence before updating review dates or adding a facility. Some facilities use attributed OSM geometry. Sources and licences are in [the garage snapshot](docs/data/garages.json).
- `python scripts/basemap.py` refreshes the local OpenFreeMap tiles and glyphs. [Basemap credits and licence](docs/assets/basemap/CREDITS.md)

Council data is attributed to the City of Sydney and loading zones to Transport for NSW. The street section extract and downloaded OpenStreetMap tiles are available under the Open Database Licence. MapLibre GL JS and the DM Sans font retain their licences in [assets](docs/assets/).
