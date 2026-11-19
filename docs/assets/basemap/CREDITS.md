# Sydney basemap

Map data © OpenStreetMap contributors, available under the Open Database License 1.0. The downloadable vector tiles in this directory are an extract of that database and are distributed under the same licence. [OpenStreetMap copyright and licence](https://www.openstreetmap.org/copyright)

OpenFreeMap produces the vector tiles using the OpenMapTiles schema. The schema's cartographic design is licensed under CC BY 4.0. Sydney Parking Map supplies its own map style. [OpenFreeMap](https://openfreemap.org/) · [OpenMapTiles licence](https://github.com/openmaptiles/openmaptiles/blob/master/LICENSE.md)

The map labels use Noto Sans glyphs supplied by OpenFreeMap. [SIL Open Font License](NotoSans-LICENSE.txt)

GitHub Pages serves the Greater Sydney overview at zoom levels 7 to 11 and street detail around central Sydney, Hornsby, Penrith, and Campbelltown. Elsewhere the browser requests visible street tiles from OpenFreeMap as you zoom in. The coloured driveway lines show routes tagged as driveways in OpenStreetMap. Surveyed kerb openings require a separate data source.

The snapshot records its source, coverage, and local tile index in [snapshot.json](snapshot.json). Run `python scripts/basemap.py` from the repository root to retrieve the latest extract or pass `--snapshot` with the identifier from the recorded source URL to request that version. The script stores uncompressed protobuf files so a static host can serve them directly. It uses sequential requests and a project-specific user agent.
