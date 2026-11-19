const HOME = [151.2076, -33.868];
const CITY = [
  [151.14, -33.94],
  [151.255, -33.835],
];
const pointLayers = ['parking-symbols', 'parking-dots', 'zones', 'zone-edges'];
const $ = (id) => document.getElementById(id);
const collection = (features) => ({ type: 'FeatureCollection', features });
const feature = (geometry, properties) => ({
  type: 'Feature',
  geometry,
  properties,
});

function markerImage(map, kind) {
  const canvas = document.createElement('canvas');
  canvas.width = 68;
  canvas.height = 68;
  const ctx = canvas.getContext('2d');
  ctx.scale(2, 2);
  ctx.shadowColor = '#1b353a55';
  ctx.shadowBlur = 3;
  ctx.shadowOffsetY = 1;
  ctx.fillStyle = {
    garage: '#345ed3',
    meter: '#007d71',
    mobility: '#8050aa',
    kerb: '#a56622',
    section: '#287859',
  }[kind];
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 1.7;
  ctx.beginPath();
  if (kind === 'meter' || kind === 'section')
    ctx.arc(17, 17, 7, 0, Math.PI * 2);
  else if (kind === 'mobility') ctx.roundRect(10, 10, 14, 14, 4);
  else ctx.roundRect(4, 3, 26, 27, 7);
  ctx.fill();
  ctx.shadowColor = 'transparent';
  ctx.stroke();
  ctx.fillStyle = '#fff';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  if (kind === 'garage') {
    ctx.font = 'bold 19px Arial';
    ctx.fillText('P', 17, 17.5);
  } else if (kind === 'mobility') {
    ctx.font = 'bold 11px Arial';
    ctx.fillText('♿︎', 17, 17.5);
  } else if (kind === 'meter') {
    ctx.beginPath();
    ctx.arc(17, 17, 1.7, 0, Math.PI * 2);
    ctx.fill();
  }
  map.addImage(kind, ctx.getImageData(0, 0, 68, 68), { pixelRatio: 2 });
}
export async function parkingMap({ onMove, onPick, onHover, onDriveway }) {
  const styleResponse = await fetch('./assets/map-style.json');
  if (!styleResponse.ok) throw Error('Street map could not load.');
  const style = await styleResponse.json();
  style.sources.city.tiles = [
    new URL('assets/basemap/tiles/', document.baseURI).href + '{z}/{x}/{y}.pbf',
  ];
  style.glyphs =
    new URL('assets/basemap/glyphs/', document.baseURI).href +
    '{fontstack}/{range}.pbf';
  const map = new maplibregl.Map({
    container: 'map',
    style,
    center: HOME,
    zoom: 14.2,
    maxBounds: CITY,
    minZoom: 10,
    maxZoom: 20,
    pitchWithRotate: false,
    dragRotate: false,
    attributionControl: { compact: true },
    canvasContextAttributes: { antialias: false },
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(
    new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 85 }),
    'bottom-left',
  );
  map.on('moveend', () => {
    onMove(map.getBounds(), map.getCenter());
    $('legend-driveway').hidden = map.getZoom() < 16.5;
  });
  map.on('movestart', () => onHover(null));
  let ready = false;
  let items = [],
    selected = null;
  function setItems(records) {
    items = records;
    if (!ready) return;
    const points = [],
      areas = [];
    for (const r of records) {
      const prop = {
        id: r.id,
        kind: r.kind,
        rank: r.kind === 'garage' ? 0 : r.kind === 'meter' ? 2 : 3,
      };
      if (r.geometry.type === 'Point') points.push(feature(r.geometry, prop));
      else areas.push(feature(r.geometry, prop));
    }
    map.getSource('parking').setData(collection(points));
    map.getSource('kerb-shapes').setData(collection(areas));
  }
  function highlight(r) {
    selected = r;
    if (ready)
      map
        .getSource('selected-location')
        .setData(
          collection(
            r ? [feature({ type: 'Point', coordinates: r.point }, {})] : [],
          ),
        );
  }
  map.on('load', () => {
    ['garage', 'mobility', 'meter', 'kerb', 'section'].forEach((k) =>
      markerImage(map, k),
    );
    for (const id of ['parking', 'kerb-shapes', 'selected-location'])
      map.addSource(id, { type: 'geojson', data: collection([]) });
    map.addLayer({
      id: 'zones',
      type: 'fill',
      source: 'kerb-shapes',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: {
        'fill-color': [
          'match',
          ['get', 'kind'],
          'section',
          '#4da679',
          '#c8872d',
        ],
        'fill-opacity': 0.55,
      },
    });
    map.addLayer({
      id: 'zone-edges',
      type: 'line',
      source: 'kerb-shapes',
      paint: {
        'line-color': [
          'match',
          ['get', 'kind'],
          'section',
          '#18745c',
          '#aa681e',
        ],
        'line-width': [
          'interpolate',
          ['linear'],
          ['zoom'],
          12,
          1.6,
          15,
          3.3,
          18,
          5.5,
        ],
      },
    });
    map.addLayer({
      id: 'parking-selection',
      type: 'circle',
      source: 'selected-location',
      paint: {
        'circle-radius': 20,
        'circle-color': '#e1f7a5',
        'circle-opacity': 0.7,
        'circle-stroke-color': '#3b5c3d',
        'circle-stroke-width': 2,
      },
    });
    map.addLayer({
      id: 'parking-dots',
      type: 'circle',
      source: 'parking',
      paint: {
        'circle-color': [
          'match',
          ['get', 'kind'],
          'garage',
          '#345ed3',
          'mobility',
          '#8050aa',
          '#007e72',
        ],
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          11,
          1.7,
          15,
          3.6,
          18,
          5,
        ],
        'circle-stroke-width': 0.8,
        'circle-stroke-color': 'white',
      },
    });
    map.addLayer({
      id: 'parking-symbols',
      type: 'symbol',
      source: 'parking',
      layout: {
        'icon-image': ['get', 'kind'],
        'symbol-sort-key': ['get', 'rank'],
        'icon-allow-overlap': false,
        'icon-ignore-placement': false,
        'icon-padding': 2,
        'icon-size': [
          'interpolate',
          ['linear'],
          ['zoom'],
          11,
          0.65,
          14,
          0.94,
          17,
          1.1,
        ],
      },
    });
    ready = true;
    setItems(items);
    highlight(selected);
    onMove(map.getBounds(), map.getCenter());
  });
  function hit(p) {
    if (!ready) return;
    // Prefer the visible marker before trying a wider touch target.
    for (const box of [
      p,
      [
        [p.x - 4, p.y - 4],
        [p.x + 4, p.y + 4],
      ],
    ]) {
      const hits = map.queryRenderedFeatures(box, { layers: pointLayers });
      const found =
        hits.find((f) => f.layer.id === 'parking-symbols') || hits[0];
      if (found) return found.properties.id;
    }
    if (
      map.getLayer('driveways') &&
      map.queryRenderedFeatures(
        [
          [p.x - 3, p.y - 3],
          [p.x + 3, p.y + 3],
        ],
        { layers: ['driveways'] },
      ).length
    )
      return 'driveway';
  }
  map.on('mousemove', (e) => {
    const id = hit(e.point);
    map.getCanvas().style.cursor = id ? 'pointer' : '';
    onHover(id, e.point);
  });
  map.getCanvas().addEventListener('mouseleave', () => onHover(null));
  map.on('click', (e) => {
    const id = hit(e.point);
    onHover(null);
    if (id === 'driveway') onDriveway();
    else if (id) onPick(id);
  });
  $('zoomin').onclick = () => map.zoomIn();
  $('zoomout').onclick = () => map.zoomOut();
  $('resetmap').onclick = () => map.easeTo({ center: HOME, zoom: 14.2 });
  let positionMarker, statusTimer;
  function status(message) {
    clearTimeout(statusTimer);
    $('map-status').textContent = message;
    $('map-status').hidden = false;
    statusTimer = setTimeout(() => {
      $('map-status').hidden = true;
    }, 6500);
  }
  $('recenter').onclick = () => {
    if (!navigator.geolocation) {
      status('Location is unavailable on this device.');
      return;
    }
    status('Finding your location…');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const point = [pos.coords.longitude, pos.coords.latitude];
        if (!new maplibregl.LngLatBounds(...CITY).contains(point)) {
          status('Your location is outside the Sydney map.');
          return;
        }
        positionMarker ??= new maplibregl.Marker({ color: '#126a88' });
        positionMarker.setLngLat(point).addTo(map);
        map.easeTo({ center: point, zoom: 17 });
        $('map-status').hidden = true;
      },
      (err) =>
        status(
          err.code === 1
            ? 'Location permission was declined.'
            : 'Your location is unavailable.',
        ),
      { timeout: 10000 },
    );
  };
  return {
    setItems,
    highlight,
    focus: (r) =>
      map.easeTo({
        center: r.point,
        zoom: Math.max(map.getZoom(), 16.9),
        duration: 380,
      }),
    bounds: () => map.getBounds(),
    center: () => map.getCenter(),
  };
}
