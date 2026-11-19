const paths = {
  map: '<path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2zM9 3v16m6-14v16"/>',
  bookmark: '<path d="M6 4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17l-6-4-6 4z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-9v.1"/>',
  pin: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  road: '<path d="m7 3-4 18m14-18 4 18M12 4v3m0 4v3m0 4v3"/>',
  parking:
    '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/>',
  meter:
    '<rect x="6" y="3" width="12" height="14" rx="4"/><path d="M10 7h4m-4 4h1m1 6v4m-3 0h6"/>',
  mobility:
    '<circle cx="12" cy="4" r="1.5"/><path d="m10.5 8 .5 6h6l3 5m-9-9h6M7.6 11.7a5 5 0 1 0 7.7 6.4"/>',
  loading:
    '<path d="M3 6h11v10H3zm11 3h4l3 4v3h-7"/><circle cx="6" cy="17" r="2"/><circle cx="17" cy="17" r="2"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  focus:
    '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
  plus: '<path d="M5 12h14m-7-7v14"/>',
  minus: '<path d="M5 12h14"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  back: '<path d="m12 5-7 7 7 7m-7-7h15"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  link: '<path d="M13 4h7v7m0-7-10 10m-1-9H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
};
export function icon(name) {
  return (
    '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
    paths[name] +
    '</svg>'
  );
}
document
  .querySelectorAll('[data-i]')
  .forEach((el) => (el.outerHTML = icon(el.dataset.i)));
