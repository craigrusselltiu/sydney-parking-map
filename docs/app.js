import { icon } from './icons.js';
import { parkingMap } from './map.js';

const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        c
      ],
  );
const labels = {
  mobility: 'Mobility bay',
  garage: 'Car park',
  kerb: '2018 loading zone',
  section: 'Street side',
};
const icons = {
  mobility: 'mobility',
  garage: 'parking',
  kerb: 'loading',
  section: 'road',
};
const toggles = {
  mobility: 'mobility',
  garage: 'garages',
  kerb: 'historical',
  section: 'sections',
};
const fmt = (n) => n.toLocaleString('en-AU');
const date = (s) =>
  s
    ? new Intl.DateTimeFormat('en-AU', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC',
      }).format(new Date(s.slice(0, 10) + 'T00:00:00Z'))
    : 'Unknown';
const normal = (s) =>
  s
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
const srcLink = (url, title) =>
  /^https?:\/\//.test(url)
    ? '<a class="detail-link" href="' +
      escape(url) +
      '" target="_blank" rel="noopener">' +
      escape(title) +
      ' ' +
      icon('link') +
      '</a>'
    : escape(title);
const checked = (id) => $(id)?.checked ?? true;
let records = [],
  byId = new Map(),
  map = null,
  bounds = null,
  centre = { lng: 151.2076, lat: -33.868 };
let savedMode = false,
  type = 'all',
  query = '',
  selected = null,
  limit = 25,
  active = [],
  visible = [],
  sources = {},
  retrieved = '',
  garagesDate = '',
  loaded = false,
  failed = false;
let places = [],
  destinationMatches = [],
  initialOpened = false;
let bookmarks;
try {
  bookmarks = new Set(
    JSON.parse(localStorage.getItem('kerb-atlas-saved') || '[]'),
  );
} catch {
  bookmarks = new Set();
}
function midpoint(geometry) {
  if (geometry.type === 'Point') return geometry.coordinates;
  let points = geometry.coordinates;
  while (Array.isArray(points[0][0])) points = points[0];
  if (geometry.type.endsWith('LineString')) {
    const lengths = points
      .slice(1)
      .map(([x, y], i) =>
        Math.hypot((x - points[i][0]) * 0.83, y - points[i][1]),
      );
    let remaining = lengths.reduce((sum, n) => sum + n, 0) / 2;
    for (let i = 0; i < lengths.length; i++) {
      if (remaining <= lengths[i])
        return points[i].map(
          (v, j) =>
            v + ((points[i + 1][j] - v) * remaining) / (lengths[i] || 1),
        );
      remaining -= lengths[i];
    }
  }
  const middle = points.reduce(
    ([x, y], [lon, lat]) => [x + lon, y + lat],
    [0, 0],
  );
  return middle.map((n) => n / points.length);
}
function distance(r) {
  return (
    ((r.point[0] - centre.lng) * 0.83) ** 2 + (r.point[1] - centre.lat) ** 2
  );
}
function describe(r) {
  return r.kind === 'garage'
    ? r.address
    : [r.area, r.location].filter(Boolean).join(' · ');
}
function tag(r) {
  const label =
    r.source === 'waverley'
      ? 'Kerb survey · 2021'
      : r.communityMapped
        ? 'Mapped car park'
        : labels[r.kind];
  return '<span class="label ' + r.kind + '">' + escape(label) + '</span>';
}
function capacityText(r) {
  return r.capacity == null
    ? 'Capacity unknown'
    : fmt(r.capacity) + ' ' + (r.capacityKind || 'total spaces');
}
function secondTag(r) {
  if (r.kind === 'garage' && r.capacity != null) return capacityText(r);
  if (r.kind === 'mobility' && r.spaces != null)
    return r.spaces + (r.spaces === 1 ? ' bay' : ' bays');
  return '';
}
function saveButton(r) {
  const marked = bookmarks.has(r.id);
  return (
    '<button class="save-row" aria-pressed="' +
    marked +
    '" aria-label="' +
    escape((marked ? 'Unsave ' : 'Save ') + r.name) +
    '" data-save="' +
    escape(r.id) +
    '">' +
    icon('bookmark') +
    '</button>'
  );
}
function card(r) {
  const extra = secondTag(r);
  const rule = r.kind === 'section' ? r.rules[0] : null;
  return (
    '<article class="card"><button class="row-main" data-open="' +
    escape(r.id) +
    '"><span class="badge-icon ' +
    r.kind +
    '">' +
    icon(icons[r.kind]) +
    '</span><span class="row-text"><span class="row-name">' +
    escape(r.name) +
    '</span><span class="sub">' +
    escape(describe(r)) +
    '</span>' +
    (rule ? '<span class="rule-preview">' + escape(rule) + '</span>' : '') +
    '<span class="tags">' +
    tag(r) +
    (extra ? '<span class="meta-chip">' + escape(extra) + '</span>' : '') +
    '</span></span></button>' +
    saveButton(r) +
    '</article>'
  );
}
function matches(r) {
  if (savedMode && !bookmarks.has(r.id)) return false;
  if (!checked(toggles[r.kind])) return false;
  if (
    (type === 'garage' && r.kind !== 'garage') ||
    (type === 'street' && r.kind === 'garage')
  )
    return false;
  return query.split(' ').every((word) => r.search.includes(word));
}
function renderRows(reset = false) {
  const relevance = (r) =>
    !query
      ? 0
      : r.searchName === query
        ? 0
        : r.searchName.startsWith(query)
          ? 1
          : r.searchName.includes(query)
            ? 2
            : 3;
  visible = active
    .filter(
      (r) =>
        savedMode ||
        query ||
        !bounds ||
        bounds.contains(r.point) ||
        (r.extent && bounds.intersects(r.extent)),
    )
    .sort(
      (a, b) =>
        relevance(a) - relevance(b) ||
        distance(a) - distance(b) ||
        a.name.localeCompare(b.name),
    );
  $('results-title').textContent = savedMode
    ? 'Saved locations'
    : query
      ? 'Search results'
      : bounds
        ? 'In this area'
        : 'Parking locations';
  $('result-count').textContent = loaded
    ? fmt(visible.length) +
      ' ' +
      (visible.length === 1 ? 'location' : 'locations')
    : 'Loading…';
  const page = visible.slice(0, limit);
  $('results').innerHTML =
    page.map(card).join('') +
    (visible.length > limit
      ? '<button class="more" id="more">Show more locations</button>'
      : '');
  if (!page.length)
    $('results').innerHTML =
      '<p class="empty">' +
      (failed
        ? 'Parking data could not load. Reload the page to try again.'
        : !loaded
          ? 'Loading parking locations…'
          : savedMode && !bookmarks.size
            ? 'Save a location with its bookmark button to find it here.'
            : query
              ? 'No matches. Try another street or broaden your filters.'
              : 'No matching locations in this view. Zoom out or change the map layers.') +
      '</p>';
  if (reset) $('results').scrollTop = 0;
}
function filter(reset = true) {
  if (reset) limit = 25;
  active = records.filter(matches);
  map?.setItems(active);
  $('legend-historical').hidden =
    !checked('historical') && !active.some((r) => r.kind === 'kerb');
  updateDestinations();
  renderRows(reset);
}
function showSavedCount() {
  $('saved-count').textContent = bookmarks.size;
  $('saved-count').hidden = !bookmarks.size;
}
function bookmark(id) {
  if (bookmarks.has(id)) bookmarks.delete(id);
  else bookmarks.add(id);
  try {
    localStorage.setItem('kerb-atlas-saved', JSON.stringify([...bookmarks]));
  } catch {}
  showSavedCount();
  if (savedMode && !bookmarks.has(id) && selected?.id === id) closeDetail();
  filter(false);
  if (selected?.id === id) drawDetail(selected);
}
function closeDetail() {
  const url = new URL(location.href);
  if (url.searchParams.has('id')) {
    url.searchParams.delete('id');
    history.replaceState(null, '', url);
  }
  selected = null;
  map?.highlight(null);
  $('detail').hidden = true;
  $('finder').hidden = false;
}
function drawDetail(r) {
  const isGarage = r.kind === 'garage',
    isSaved = bookmarks.has(r.id);
  let content = '';
  if (isGarage) {
    content =
      '<h2>Capacity</h2><p class="note">' +
      (r.capacity == null
        ? 'Total capacity is unpublished in this listing.'
        : '<strong>' + escape(capacityText(r)) + '</strong>') +
      '</p>' +
      (r.capacityUrl ? srcLink(r.capacityUrl, r.capacitySource) : '') +
      (r.occupancyNote
        ? '<p class="note">' + escape(r.occupancyNote) + '</p>'
        : '') +
      (r.availabilityUrl
        ? '<p>' +
          srcLink(
            r.availabilityUrl,
            'Check live availability with Transport for NSW',
          ) +
          '</p>'
        : '<p class="note">Live vacancies and hourly counts are unknown.</p>') +
      '<h2>Opening hours</h2><p class="note">' +
      escape(
        r.hours || 'Check the operator for current entry and exit times.',
      ) +
      '</p>';
    if (r.conditions?.length)
      content +=
        '<h2>Mapped conditions</h2><ul class="detail-rules">' +
        r.conditions.map((t) => '<li>' + escape(t) + '</li>').join('') +
        '</ul>';
  } else {
    const heading = {
      mobility: 'Bay restrictions',
      kerb: '2018 loading hours',
      section: 'Mapped street rules',
    }[r.kind];
    content =
      '<h2>' +
      heading +
      '</h2><ul class="detail-rules">' +
      r.rules.map((t) => '<li>' + escape(t) + '</li>').join('') +
      '</ul>';
    if (r.spaces != null)
      content +=
        '<p class="note">' +
        (r.kind === 'kerb' ? 'Spaces in the 2018 survey' : 'Recorded spaces') +
        ' · <strong>' +
        fmt(r.spaces) +
        '</strong></p>';
    if (r.driveways?.length)
      content +=
        '<p class="note">' +
        r.driveways.length +
        ' mapped driveway ' +
        (r.driveways.length === 1 ? 'connection' : 'connections') +
        ' on this side. Keep access clear.</p>';
    if (r.audited)
      content += '<p class="note">Council audit · ' + date(r.audited) + '</p>';
    content +=
      '<p class="note">' +
      escape(
        sources[r.source]?.note ||
          'Check the posted signs and driveway openings on this side of the street.',
      ) +
      '</p>';
  }
  $('detail').innerHTML =
    '<button class="back" data-back>' +
    icon('back') +
    ' Back to results</button>' +
    tag(r) +
    '<h1>' +
    escape(r.name) +
    '</h1><div class="detail-address">' +
    escape(describe(r)) +
    '</div><button class="save-action" data-save="' +
    escape(r.id) +
    '" aria-pressed="' +
    isSaved +
    '">' +
    icon('bookmark') +
    (isSaved ? 'Saved' : 'Save location') +
    '</button>' +
    content +
    '<h2>Source</h2>' +
    srcLink(
      r.url || sources[r.source]?.url,
      isGarage ? r.source : sources[r.source]?.name || 'View source',
    ) +
    (isGarage && r.locationUrl && r.locationUrl !== r.url
      ? '<p>' +
        srcLink(r.locationUrl, r.locationSource || 'Location source') +
        '</p>'
      : '') +
    '<p class="footnote">' +
    (isGarage
      ? r.communityMapped
        ? 'OSM extract · ' + date(r.asOf)
        : 'Listing reviewed · ' + date(r.reviewed || garagesDate)
      : r.kind === 'section'
        ? 'Source file · ' + date(sources[r.source].fileDate)
        : 'Data retrieved · ' + date(retrieved)) +
    '</p>';
}
function showDetail(id, focusMap) {
  const r = byId.get(id);
  if (!r) return;
  selected = r;
  drawDetail(r);
  $('finder').hidden = true;
  $('detail').hidden = false;
  $('detail').scrollTop = 0;
  map?.highlight(r);
  const url = new URL(location.href);
  url.searchParams.set('id', r.id);
  history.replaceState(null, '', url);
  if (focusMap) map?.focus(r);
  $('detail').querySelector('[data-back]').focus({ preventScroll: true });
}
function showDriveway(way) {
  closeDetail();
  $('finder').hidden = true;
  $('detail').hidden = false;
  $('detail').innerHTML =
    '<button class="back" data-back>' +
    icon('back') +
    ' Back to results</button><h1>Mapped driveway</h1><p class="note">Keep the vehicle access clear. The dashed line follows the mapped driveway. Its width at the kerb is unknown.</p><p class="note">Other driveways may be missing.</p>' +
    srcLink(
      way
        ? 'https://www.openstreetmap.org/way/' + encodeURIComponent(way)
        : 'https://www.openstreetmap.org/copyright',
      'OpenStreetMap contributors',
    );
  $('detail').scrollTop = 0;
  $('detail').querySelector('button').focus({ preventScroll: true });
}
let hoverId;
function hover(id, p) {
  const box = $('tooltip');
  if (!id || window.matchMedia('(hover: none)').matches) {
    box.hidden = true;
    hoverId = null;
    return;
  }
  if (hoverId !== id) {
    const r = byId.get(id);
    if (r) {
      const lines =
        r.kind === 'garage'
          ? [
              capacityText(r),
              r.availabilityUrl
                ? 'Live availability on the Transport for NSW site'
                : 'Live vacancies unknown',
            ]
          : r.rules;
      box.innerHTML =
        tag(r) +
        '<strong>' +
        escape(r.name) +
        '</strong>' +
        (r.kind === 'section' ? '<p>' + escape(r.location) + '</p>' : '') +
        lines.map((l) => '<p>' + escape(l) + '</p>').join('');
    } else if (id === 'driveway')
      box.innerHTML =
        '<strong>Mapped driveway</strong><p>Keep access clear. Kerb width unverified.</p>';
    else {
      return;
    }
    hoverId = id;
  }
  box.hidden = false;
  const view = $('map');
  box.style.left =
    Math.max(5, Math.min(p.x + 14, view.clientWidth - box.offsetWidth - 6)) +
    'px';
  box.style.top =
    Math.max(
      5,
      p.y + box.offsetHeight + 16 > view.clientHeight
        ? p.y - box.offsetHeight - 8
        : p.y + 14,
    ) + 'px';
}
function mode(saved) {
  savedMode = saved;
  if (saved)
    for (const id of bookmarks) {
      const record = byId.get(id);
      if (record) $(toggles[record.kind]).checked = true;
    }
  type = 'all';
  query = '';
  $('query').value = '';
  closeDetail();
  $('explore').setAttribute('aria-pressed', !saved);
  $('saved').setAttribute('aria-pressed', saved);
  $('page-title').textContent = saved ? 'Saved parking' : 'Find parking';
  document
    .querySelectorAll('[data-type]')
    .forEach((b) => b.setAttribute('aria-pressed', b.dataset.type === type));
  filter();
}
function updateDestinations() {
  destinationMatches =
    savedMode || query.length < 2
      ? []
      : places
          .filter((p) => normal(p.name).startsWith(query))
          .sort(
            (a, b) =>
              Number(normal(b.name) === query) -
                Number(normal(a.name) === query) ||
              a.name.localeCompare(b.name),
          )
          .slice(0, 4);
  const list = $('destinations');
  list.hidden = !destinationMatches.length;
  list.innerHTML = destinationMatches
    .map(
      (p, i) =>
        '<button data-place="' +
        i +
        '">' +
        icon('pin') +
        escape(p.name) +
        '<small>Show area</small></button>',
    )
    .join('');
}
function jump(p) {
  areaMenu(false);
  mode(false);
  if (!map) {
    $('query').value = p.name;
    query = normal(p.name);
    filter();
    return;
  }
  map.goTo(p.point, 15.8);
  const url = new URL(location.href);
  url.searchParams.set('area', p.name);
  url.searchParams.delete('id');
  history.replaceState(null, '', url);
}
function areaMenu(open) {
  $('areas').hidden = !open;
  $('resetmap').setAttribute('aria-expanded', open);
  if (open) layers(false);
}
const quickAreas = [
  'Hornsby',
  'Penrith',
  'Campbelltown',
  'Parramatta',
  'Sydney',
  'Bondi Beach',
];
$('area-options').innerHTML =
  '<button data-region>Regional overview</button>' +
  quickAreas
    .map(
      (name) =>
        '<button data-area="' +
        name +
        '">' +
        (name === 'Sydney' ? 'Sydney CBD' : name) +
        '</button>',
    )
    .join('');
$('resetmap').onclick = () => areaMenu($('areas').hidden);
$('area-options').onclick = (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.hasAttribute('data-region')) {
    areaMenu(false);
    mode(false);
    map?.overview();
    history.replaceState(null, '', location.pathname);
    return;
  }
  const p = places.find((p) => p.name === b.dataset.area);
  if (p) jump(p);
};
$('destinations').onclick = (e) => {
  const b = e.target.closest('[data-place]');
  if (b) jump(destinationMatches[Number(b.dataset.place)]);
};
function openInitialArea() {
  if (!loaded || !map || initialOpened) return;
  initialOpened = true;
  const params = new URLSearchParams(location.search);
  const area = places.find(
    (p) => normal(p.name) === normal(params.get('area') || ''),
  );
  if (area) jump(area);
  const id = params.get('id');
  if (byId.has(id)) {
    const r = byId.get(id);
    $(toggles[r.kind]).checked = true;
    filter();
    showDetail(id, true);
  }
}
function applyTheme(dark) {
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  const button = $('theme');
  button.innerHTML = dark ? icon('sun') : icon('moon');
  button.title = button.ariaLabel = dark
    ? 'Switch to light mode'
    : 'Switch to dark mode';
  map?.setTheme(dark);
}
applyTheme(document.documentElement.dataset.theme === 'dark');
$('theme').onclick = () => {
  const dark = document.documentElement.dataset.theme !== 'dark';
  applyTheme(dark);
  try {
    localStorage.setItem('kerb-atlas-theme', dark ? 'dark' : 'light');
  } catch {}
};
function sourceInfo() {
  const streets = records.filter((r) => r.kind === 'section').length;
  const garage = records.filter((r) => r.kind === 'garage').length;
  $('source-details').innerHTML =
    '<h3>Street sides</h3><p>' +
    fmt(streets) +
    ' mapped street-side records across Greater Sydney. A coloured line identifies a recorded side or bay. Hover or tap it for conditions. Unmarked roads have unknown coverage.</p>' +
    '<p>OpenStreetMap lines are offset to the recorded side of travel. Waverley Council lines use its 2021 kerb survey. Line positions and endpoints are approximate. Signs, driveway openings and temporary controls still need checking on site.</p>' +
    '<h3>Car parks</h3><p>' +
    fmt(garage) +
    ' mapped facilities. Capacities describe the bays recorded by each source. Selected Park&amp;Ride listings link to Transport for NSW for current availability.</p>' +
    '<h3>Other layers</h3><p>Zoom in for known driveway access routes. The optional City of Sydney mobility layer includes council audit dates. Loading zones show a historical 2018 survey.</p>' +
    '<h3>Sources</h3><ul>' +
    Object.values(sources)
      .filter(
        (source, i, all) =>
          all.findIndex((other) => other.url === source.url) === i,
      )
      .map(
        (s) =>
          '<li>' +
          srcLink(s.url, s.name) +
          ' · ' +
          srcLink(s.licenseUrl, s.license) +
          '</li>',
      )
      .join('') +
    '</ul>';
}
$('explore').onclick = () => mode(false);
$('saved').onclick = () => mode(true);
$('query').oninput = (e) => {
  query = normal(e.target.value);
  filter();
};
$('query').onkeydown = (e) => {
  if (e.key === 'Enter' && destinationMatches.length) {
    e.preventDefault();
    jump(destinationMatches[0]);
    return;
  }
  if (e.key === 'Enter' && visible.length) {
    e.preventDefault();
    showDetail(visible[0].id, true);
  }
};
document.querySelector('.tabs').onclick = (e) => {
  const b = e.target.closest('[data-type]');
  if (!b) return;
  type = b.dataset.type;
  document
    .querySelectorAll('[data-type]')
    .forEach((t) => t.setAttribute('aria-pressed', t === b));
  filter();
};
$('sidebar').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.open) showDetail(b.dataset.open, true);
  if (b.dataset.save) bookmark(b.dataset.save);
  if (b.hasAttribute('data-back')) {
    const id = selected?.id;
    closeDetail();
    const target =
      id && $('results').querySelector('[data-open="' + CSS.escape(id) + '"]');
    (target || $('query')).focus({ preventScroll: true });
  }
  if (b.id === 'more') {
    limit += 25;
    const start = limit - 25;
    renderRows();
    $('results')
      .querySelectorAll('[data-open]')
      [start]?.focus({ preventScroll: true });
  }
});
function layers(open) {
  if (open) areaMenu(false);
  $('layers').hidden = !open;
  $('layers-button').setAttribute('aria-expanded', open);
}
$('layers-button').onclick = () => layers($('layers').hidden);
$('layers').onchange = () => {
  if (selected && !matches(selected)) closeDetail();
  filter();
};
document.addEventListener('pointerdown', (e) => {
  if (!e.target.closest('#layers,#layers-button')) layers(false);
  if (!e.target.closest('#areas,#resetmap')) areaMenu(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    layers(false);
    areaMenu(false);
    hover(null);
  }
});
$('about').onclick = $('coverage').onclick = () => $('info-dialog').showModal();
$('close-info').onclick = () => $('info-dialog').close();
$('info-dialog').onclick = (e) => {
  if (e.target === $('info-dialog')) {
    const r = e.target.getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      e.target.close();
  }
};
function clock() {
  const s = new Intl.DateTimeFormat('en-AU', {
    timeZone: 'Australia/Sydney',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date());
  $('clock').textContent = 'Sydney · ' + s;
}
clock();
setInterval(clock, 30000);
showSavedCount();
async function json(url) {
  const res = await fetch(url);
  if (!res.ok) throw Error(url);
  return res.json();
}
async function initData() {
  const [k, g, sections, waverley, suburbs] = await Promise.all([
    json('./data/kerbs.json'),
    json('./data/garages.json'),
    json('./data/street-sections.json'),
    json('./data/waverley.json'),
    json('./data/suburbs.json'),
  ]);
  sources = {
    ...k.sources,
    ...sections.sources,
    ...waverley.sources,
    suburbs: suburbs.source,
  };
  g.sources
    .filter((s) => s.licenseUrl)
    .forEach((s, i) => (sources['garages' + i] = s));
  places = suburbs.places;
  retrieved = k.retrieved;
  garagesDate = g.updated;
  records = [
    ...k.features,
    ...sections.features,
    ...waverley.features,
    ...g.features.map((r) => ({
      ...r,
      id: 'garage-' + r.id,
      kind: 'garage',
      geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    })),
  ];
  for (const r of records) {
    r.point = midpoint(r.geometry);
    if (r.geometry.type !== 'Point') {
      const box = [
        [180, 90],
        [-180, -90],
      ];
      function extend(c) {
        if (typeof c[0] === 'number') {
          box[0][0] = Math.min(box[0][0], c[0]);
          box[0][1] = Math.min(box[0][1], c[1]);
          box[1][0] = Math.max(box[1][0], c[0]);
          box[1][1] = Math.max(box[1][1], c[1]);
        } else c.forEach(extend);
      }
      extend(r.geometry.coordinates);
      r.extent = box;
    }
    r.searchName = normal(r.name);
    r.search = normal(
      [r.name, r.area, r.suburb, r.location, r.address, labels[r.kind]]
        .filter(Boolean)
        .join(' '),
    );
    byId.set(r.id, r);
  }
  loaded = true;
  bookmarks = new Set([...bookmarks].filter((id) => byId.has(id)));
  showSavedCount();
  sourceInfo();
  filter();
  openInitialArea();
}
initData().catch(() => {
  failed = true;
  loaded = true;
  renderRows();
  $('source-details').textContent =
    'Source records could not load. Reload to try again.';
});
parkingMap({
  onMove: (b, c) => {
    bounds = b;
    centre = c;
    limit = 25;
    renderRows();
  },
  onPick: (id) => showDetail(id, false),
  onHover: hover,
  onDriveway: showDriveway,
})
  .then((m) => {
    map = m;
    bounds = m.bounds();
    centre = m.center();
    filter();
    openInitialArea();
  })
  .catch(() => {
    $('map-status').hidden = false;
    $('map-status').textContent =
      'Map unavailable on this device. Search or browse the locations below.';
    document.querySelector('.map-controls').hidden = true;
    filter();
  });
