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
  meter: 'Parking meter',
  mobility: 'Mobility bay',
  garage: 'Car park',
  kerb: '2018 loading zone',
  section: 'Street section',
};
const icons = {
  meter: 'meter',
  mobility: 'mobility',
  garage: 'parking',
  kerb: 'loading',
  section: 'road',
};
const toggles = {
  meter: 'meters',
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
    : r.kind === 'meter'
      ? [r.area, r.location.split(' · ')[0]].filter(Boolean).join(' · ')
      : r.location || r.area;
}
function tag(r) {
  return '<span class="label ' + r.kind + '">' + labels[r.kind] + '</span>';
}
function secondTag(r) {
  if (r.kind === 'garage')
    return r.capacity == null ? '' : fmt(r.capacity) + ' total bays';
  if (r.kind === 'meter') {
    const first = r.rules[0] || '';
    if (/out of operation|shut down/i.test(first)) return 'Meter offline';
    if (/15 minutes free|Free 15-minute/i.test(first)) return '15 min free';
    if (r.spaces != null) return '≈ ' + r.spaces + ' bays';
  }
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
  const rule =
    r.kind === 'meter' ? r.rules.find((t) => t.includes(' · ')) : null;
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
    .filter((r) => savedMode || query || !bounds || bounds.contains(r.point))
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
  $('legend-section').hidden = !active.some((r) => r.kind === 'section');
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
        : '<strong>' + fmt(r.capacity) + ' total spaces</strong>') +
      '</p>' +
      (r.capacityUrl ? srcLink(r.capacityUrl, r.capacitySource) : '') +
      (r.occupancyNote
        ? '<p class="note">' + escape(r.occupancyNote) + '</p>'
        : '') +
      '<p class="note">Live vacancies and hourly counts are unknown.</p><h2>Opening hours</h2><p class="note">' +
      escape(
        r.hours || 'Check the operator for current entry and exit times.',
      ) +
      '</p>';
  } else {
    const heading = {
      meter: 'Published meter hours',
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
        (r.kind === 'meter'
          ? 'Approximate bays served by this meter'
          : r.kind === 'kerb'
            ? 'Spaces in the 2018 survey'
            : 'Designated spaces') +
        ' · <strong>' +
        fmt(r.spaces) +
        '</strong></p>';
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
    (isGarage && r.locationUrl !== r.url
      ? '<p>' +
        srcLink(r.locationUrl, r.locationSource || 'Location source') +
        '</p>'
      : '') +
    '<p class="footnote">' +
    (isGarage
      ? 'Listing reviewed · ' + date(r.reviewed || garagesDate)
      : r.kind === 'section'
        ? 'OSM extract · ' + date(sources[r.source].fileDate)
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
  if (focusMap) map?.focus(r);
  $('detail').querySelector('[data-back]').focus({ preventScroll: true });
}
function showDriveway() {
  closeDetail();
  $('finder').hidden = true;
  $('detail').hidden = false;
  $('detail').innerHTML =
    '<button class="back" data-back>' +
    icon('back') +
    ' Back to results</button><h1>Mapped driveway</h1><p class="note">Keep the vehicle access clear. The dashed line follows the mapped driveway. Its width at the kerb is unknown.</p><p class="note">Other driveways may be missing.</p>' +
    srcLink(
      'https://www.openstreetmap.org/copyright',
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
              r.capacity == null
                ? 'Capacity unknown'
                : fmt(r.capacity) + ' total spaces',
              'Live vacancies unknown',
            ]
          : r.rules;
      box.innerHTML =
        tag(r) +
        '<strong>' +
        escape(r.name) +
        '</strong>' +
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
function sourceInfo() {
  const street = records.filter((r) => r.kind === 'meter').length,
    mobility = records.filter((r) => r.kind === 'mobility').length,
    garage = records.filter((r) => r.kind === 'garage').length;
  $('source-details').innerHTML =
    '<h3>Street parking</h3><p>' +
    fmt(street) +
    ' council meters show tariffs, hours and stay limits. A meter pin describes that machine. Sign changes, unmetered spaces, temporary restrictions and driveway widths have incomplete coverage. Unlisted hours are unknown.</p><p>Green street sections show OpenStreetMap rules for the specified side or sides. A road centreline marks the mapped extent. Check the sign at the exact bay.</p>' +
    '<p>' +
    fmt(mobility) +
    ' mobility locations include the council audit date where published. The optional loading-zone layer shows a 2018 survey.</p>' +
    '<h3>Car parks</h3><p>' +
    fmt(garage) +
    ' public car park listings. Total capacity is shown where a source gives a figure. Each listing links to its source.</p>' +
    '<h3>Driveways</h3><p>Zoom in to see mapped driveway routes as dashed red lines. A gap in the map is unverified.</p>' +
    '<h3>Sources and dates</h3><p class="footnote">Council and transport data retrieved ' +
    date(retrieved) +
    '.</p><ul>' +
    Object.values(sources)
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
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    layers(false);
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
  const [k, g, sections] = await Promise.all([
    json('./data/kerbs.json'),
    json('./data/garages.json'),
    json('./data/street-sections.json'),
  ]);
  sources = { ...k.sources, ...sections.sources, councilGarages: g.sources[0] };
  retrieved = k.retrieved;
  garagesDate = g.updated;
  records = [
    ...k.features,
    ...sections.features,
    ...g.features.map((r) => ({
      ...r,
      id: 'garage-' + r.id,
      kind: 'garage',
      geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    })),
  ];
  for (const r of records) {
    r.point = midpoint(r.geometry);
    r.searchName = normal(r.name);
    r.search = normal(
      [r.name, r.area, r.location, r.address, labels[r.kind]]
        .filter(Boolean)
        .join(' '),
    );
    byId.set(r.id, r);
  }
  loaded = true;
  sourceInfo();
  filter();
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
  })
  .catch(() => {
    $('map-status').hidden = false;
    $('map-status').textContent =
      'Map unavailable on this device. Search or browse the locations below.';
    document.querySelector('.map-controls').hidden = true;
    filter();
  });
