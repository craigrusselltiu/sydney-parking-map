const assets = new URL('basemap/', import.meta.url).href;
const tiles = assets + 'tiles/';
const glyphs = assets + 'glyphs/';
const bundledGlyphs = new Set([0, 256, 512, 768, 8192, 8448]);

// Day/night swatches for land, water, roads, and text in map-style.json.
const night = {
  '#edece7': '#232c31', '#e9e8e1': '#293238', '#e4e2da': '#30383c',
  '#d3e0cc': '#32473e', '#c7d9c1': '#294237', '#c7d9c0': '#2d4439',
  '#d2e1cb': '#354a3f', '#d6dfcf': '#39473e', '#cbdcc6': '#344d40',
  '#efe5c9': '#514b3c', '#dadad4': '#344048', '#ced0c9': '#404c52',
  '#b4d7e4': '#173c50', '#80b4c8': '#497991', '#e6e6df': '#445258',
  '#c5d0ca': '#58676b', '#eff0e8': '#67767a', '#c7c6c1': '#47555c',
  '#f7f7ec': '#56615d', '#d5d5cc': '#374248', '#fcfbf8': '#535e63',
  '#fffefa': '#606b71', '#aab5ac': '#73807b', '#a35754': '#ef9f91',
  '#5d6666': '#dee0d9', '#656c6b': '#c9d0c9', '#537758': '#aaceb0',
  '#507e93': '#98c8dc', '#776e69': '#d1c5ba', '#62706e': '#e3e7de',
  '#4c5d63': '#e2e8df', '#697572': '#cad3ce', '#c6e1eb': '#173c50',
  '#e4eddc': '#283b31', '#fcfbf5': '#263035', '#f9faf6': '#242d32',
  '#fbfaf6': '#242d32',
};
const paintRules = [];

function nightColour(value) {
  return Array.isArray(value) ? value.map(nightColour) : (night[value] ?? value);
}

export function applyBasemapTheme(map, dark) {
  for (const rule of paintRules) {
    if (map.getLayer(rule.layer)) {
      map.setPaintProperty(rule.layer, rule.property, dark ? rule.dark : rule.light);
    }
  }
}

export async function prepareBasemap(style, dark = false) {
  const response = await fetch(assets + 'snapshot.json');
  if (!response.ok) throw Error('The basemap index could not load.');
  const snapshot = await response.json();
  const localTiles = new Set(snapshot.localTiles);
  style.sources.city.tiles = [tiles + '{z}/{x}/{y}.pbf'];
  style.glyphs = glyphs + '{fontstack}/{range}.pbf';
  paintRules.length = 0;
  for (const layer of style.layers) {
    for (const [property, light] of Object.entries(layer.paint || {})) {
      if (!property.endsWith('-color')) continue;
      const rule = { layer: layer.id, property, light, dark: nightColour(light) };
      paintRules.push(rule);
      if (dark) layer.paint[property] = rule.dark;
    }
  }

  // Discover the current OpenFreeMap build only when leaving the local bundle.
  let remoteBuild;
  function currentBuild() {
    if (!remoteBuild) {
      remoteBuild = fetch('https://tiles.openfreemap.org/planet', {
        signal: AbortSignal.timeout(5000),
      })
        .then(async (response) => {
          if (!response.ok) throw Error('OpenFreeMap metadata unavailable.');
          const metadata = await response.json();
          return metadata.tiles[0];
        })
        .catch(() => {
          setTimeout(() => { remoteBuild = undefined; }, 60_000);
          return snapshot.tiles;
        });
    }
    return remoteBuild;
  }

  return (url) => {
    if (url.startsWith(tiles)) {
      const key = url.slice(tiles.length, -4);
      if (!localTiles.has(key)) {
        const [z, x, y] = key.split('/');
        return currentBuild().then((template) => ({
          url: template.replace('{z}', z).replace('{x}', x).replace('{y}', y),
        }));
      }
    } else if (url.startsWith(glyphs)) {
      const first = parseInt(url.slice(url.lastIndexOf('/') + 1), 10);
      if (!bundledGlyphs.has(first)) {
        return { url: 'https://tiles.openfreemap.org/fonts/' + url.slice(glyphs.length) };
      }
    }
    return { url };
  };
}
