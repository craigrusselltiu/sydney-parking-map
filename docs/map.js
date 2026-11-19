import { prepareBasemap, applyBasemapTheme } from './assets/basemap-source.js';

const REGION = [
  [149.95, -34.36],
  [151.66, -32.97],
];
const OVERVIEW = [
  [150.64, -34.1],
  [151.31, -33.64],
];
const $ = (id) => document.getElementById(id);
const collection = (features) => ({ type: 'FeatureCollection', features });
const feature = (r) => ({
  type: 'Feature',
  geometry: r.geometry,
  properties: {
    id: r.id,
    kind: r.kind,
    side: r.side || '',
    status: r.status || 'unknown',
  },
});
const width = [
  'interpolate',
  ['linear'],
  ['zoom'],
  9,
  1.2,
  13,
  2,
  16,
  3.2,
  19,
  5,
];
const side = ['match', ['get', 'side'], 'right', 1, 'left', -1, 0];
// Offset the two sides of an OSM road independently. Council kerb lines and bay footprints already have positions.
const offset = [
  'interpolate',
  ['exponential', 1.45],
  ['zoom'],
  9,
  ['*', side, 1],
  13,
  ['*', side, 2.4],
  15,
  ['*', side, 4],
  17,
  ['*', side, 8.5],
  20,
  ['*', side, 30],
];
function lineColour(dark) {
  return [
    'case',
    ['==', ['get', 'kind'], 'kerb'],
    '#b77c38',
    [
      'match',
      ['get', 'status'],
      'parking',
      dark ? '#58d9b6' : '#007d65',
      'mixed',
      dark ? '#ffcb77' : '#b3680c',
      'restricted',
      dark ? '#ff8f91' : '#bd424c',
      dark ? '#a5bfcc' : '#657d8a',
    ],
  ];
}
function drivewayLine(d) {
  // Expose only the approach to the kerb. The styling represents a connection, not its surveyed width.
  const [x, y] = d.point,
    dx = d.toward[0] - x,
    dy = d.toward[1] - y;
  const length = Math.hypot(dx * Math.cos((y * Math.PI) / 180), dy) * 111195;
  const scale = Math.min(1, 14 / (length || 1));
  return {
    type: 'Feature',
    geometry: {
      type: 'LineString',
      coordinates: [d.point, [x + dx * scale, y + dy * scale]],
    },
    properties: { way: d.way },
  };
}
function markerImage(map, kind) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.scale(2, 2);
  ctx.fillStyle = kind === 'garage' ? '#365dd4' : '#7650a0';
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  ctx.roundRect(3, 3, 26, 26, 7);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = '#fff';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = 'bold 19px Arial';
  ctx.fillText(kind === 'garage' ? 'P' : '♿︎', 16, 17);
  map.addImage(kind, ctx.getImageData(0, 0, 64, 64), { pixelRatio: 2 });
}
export async function parkingMap({ onMove, onPick, onHover, onDriveway }) {
  const response = await fetch('./assets/map-style.json');
  if (!response.ok) throw Error('Map style unavailable');
  const style = await response.json();
  const transformRequest = await prepareBasemap(
    style,
    document.documentElement.dataset.theme === 'dark',
  );
  const map = new maplibregl.Map({
    container: 'map',
    style,
    transformRequest,
    center: [151.100585, -33.704025],
    zoom: 15.8,
    maxBounds: REGION,
    minZoom: 7,
    maxZoom: 20,
    pitchWithRotate: false,
    dragRotate: false,
    attributionControl: { compact: true },
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(
    new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 85 }),
    'bottom-left',
  );
  let ready = false,
    items = [],
    selected = null;
  let dark = document.documentElement.dataset.theme === 'dark';
  function setTheme(value) {
    dark = value;
    if (!ready) return;
    applyBasemapTheme(map, dark);
    map.setPaintProperty(
      'access-gap',
      'line-color',
      dark ? '#263238' : '#f2f0e9',
    );
    map.setPaintProperty(
      'access-routes',
      'line-color',
      dark ? '#f8a79c' : '#a35754',
    );
    map.setPaintProperty('zone-edges', 'line-color', lineColour(dark));
    map.setPaintProperty('zones', 'fill-color', lineColour(dark));
  }
  function setItems(records, force = false) {
    if (
      !force &&
      ready &&
      items.length === records.length &&
      items.every((r, i) => r === records[i])
    )
      return;
    items = records;
    if (!ready) return;
    const points = [],
      lines = [],
      driveways = [];
    for (const r of records) {
      (r.geometry.type === 'Point' ? points : lines).push(feature(r));
      if (r.driveways)
        for (const entrance of r.driveways)
          driveways.push(drivewayLine(entrance));
    }
    map.getSource('connections').setData(collection(driveways));
    map.getSource('parking').setData(collection(points));
    map.getSource('kerb-shapes').setData(collection(lines));
  }
  function highlight(r) {
    selected = r;
    if (ready)
      map
        .getSource('selected-location')
        .setData(collection(r ? [feature(r)] : []));
  }
  function moved() {
    onMove(map.getBounds(), map.getCenter());
    $('legend-driveway').hidden = map.getZoom() < 16.5;
  }
  map.on('moveend', moved);
  map.on('movestart', () => onHover(null));
  map.on('load', () => {
    ['garage', 'mobility'].forEach((k) => markerImage(map, k));
    map.addSource('parking', {
      type: 'geojson',
      data: collection([]),
      cluster: true,
      clusterMaxZoom: 12,
      clusterRadius: 34,
    });
    for (const id of ['kerb-shapes', 'connections', 'selected-location'])
      map.addSource(id, {
        type: 'geojson',
        data: collection([]),
        tolerance: 0.1,
        maxzoom: 18,
      });
    map.addLayer({
      id: 'zones',
      type: 'fill',
      source: 'kerb-shapes',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: { 'fill-color': lineColour(dark), 'fill-opacity': 0.42 },
    });
    map.addLayer({
      id: 'selected-kerb',
      type: 'line',
      source: 'selected-location',
      filter: ['!=', ['geometry-type'], 'Point'],
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: {
        'line-color': '#d6fa91',
        'line-width': 9,
        'line-offset': offset,
      },
    });
    map.addLayer({
      id: 'zone-edges',
      type: 'line',
      source: 'kerb-shapes',
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: {
        'line-color': lineColour(dark),
        'line-width': width,
        'line-offset': offset,
      },
    });
    // Keep access crossings legible where the cartographic kerb line passes over them.
    map.addLayer({
      id: 'access-gap',
      type: 'line',
      source: 'connections',
      minzoom: 16.5,
      paint: { 'line-color': dark ? '#263238' : '#f2f0e9', 'line-width': 6 },
    });
    if (map.getLayer('driveways')) map.moveLayer('driveways');
    map.addLayer({
      id: 'access-routes',
      type: 'line',
      source: 'connections',
      minzoom: 16.5,
      paint: {
        'line-color': dark ? '#f8a79c' : '#a35754',
        'line-width': 2.5,
        'line-dasharray': [1.5, 1],
      },
    });
    map.addLayer({
      id: 'selected-point',
      type: 'circle',
      source: 'selected-location',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': 21,
        'circle-color': '#d6fa91',
        'circle-opacity': 0.7,
      },
    });
    map.addLayer({
      id: 'groups',
      source: 'parking',
      type: 'circle',
      filter: ['has', 'point_count'],
      paint: {
        'circle-radius': ['step', ['get', 'point_count'], 13, 20, 16, 100, 19],
        'circle-color': '#3e58a9',
        'circle-stroke-width': 2,
        'circle-stroke-color': '#dae5ff',
      },
    });
    map.addLayer({
      id: 'group-labels',
      source: 'parking',
      type: 'symbol',
      filter: ['has', 'point_count'],
      layout: {
        'text-field': ['get', 'point_count_abbreviated'],
        'text-size': 12,
        'text-font': ['Noto Sans Bold'],
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: { 'text-color': 'white' },
    });
    map.addLayer({
      id: 'parking-symbols',
      type: 'symbol',
      source: 'parking',
      filter: ['!', ['has', 'point_count']],
      layout: {
        'icon-image': ['get', 'kind'],
        'icon-size': ['interpolate', ['linear'], ['zoom'], 9, 0.7, 15, 1],
        'icon-padding': 2,
      },
    });
    ready = true;
    setItems(items, true);
    highlight(selected);
    setTheme(document.documentElement.dataset.theme === 'dark');
    moved();
  });
  function hit(p) {
    if (!ready) return;
    const layers = [
      'parking-symbols',
      'zone-edges',
      'zones',
      'groups',
      'driveways',
      'access-routes',
    ];
    for (const target of [
      p,
      [
        [p.x - 3, p.y - 3],
        [p.x + 3, p.y + 3],
      ],
    ]) {
      const hits = map.queryRenderedFeatures(target, { layers });
      if (hits.length) return hits[0];
    }
  }
  map.on('mousemove', (e) => {
    const f = hit(e.point);
    map.getCanvas().style.cursor = f ? 'pointer' : '';
    onHover(
      ['driveways', 'access-routes'].includes(f?.layer.id)
        ? 'driveway'
        : f?.properties.id,
      e.point,
    );
  });
  map.getCanvas().addEventListener('mouseleave', () => onHover(null));
  map.on('click', async (e) => {
    const f = hit(e.point);
    onHover(null);
    if (!f) return;
    if (['driveways', 'access-routes'].includes(f.layer.id))
      onDriveway(f.properties.way);
    else if (f.layer.id === 'groups') {
      const zoom = await map
        .getSource('parking')
        .getClusterExpansionZoom(f.properties.cluster_id);
      map.easeTo({
        center: f.geometry.coordinates,
        zoom: Math.max(zoom, map.getZoom() + 1),
      });
    } else onPick(f.properties.id);
  });
  $('zoomin').onclick = () => map.zoomIn();
  $('zoomout').onclick = () => map.zoomOut();
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
        if (!new maplibregl.LngLatBounds(...REGION).contains(point)) {
          status('Your location is outside Greater Sydney.');
          return;
        }
        positionMarker ??= new maplibregl.Marker({ color: '#236cb4' });
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
    setTheme,
    goTo: (point, zoom = 15) =>
      map.easeTo({ center: point, zoom, duration: 380 }),
    overview: () => map.fitBounds(OVERVIEW, { padding: 24, duration: 480 }),
    focus: (r) =>
      map.easeTo({
        center: r.point,
        zoom: Math.max(map.getZoom(), 17.5),
        duration: 380,
      }),
    bounds: () => map.getBounds(),
    center: () => map.getCenter(),
  };
}
