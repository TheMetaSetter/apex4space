/* Area name → saved API results → OpenLayers cells and daily bars. */
const $ = (id) => document.getElementById(id);
const format = new ol.format.GeoJSON();
const numbers = new Intl.NumberFormat('en');
let config, currentBoundary, controller;
proj4.defs('EPSG:6933', '+proj=cea +lat_ts=30 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs');
ol.proj.proj4.register(proj4);
const projection = ol.proj.get('EPSG:6933');
projection.setExtent([-17367530.45, -7324184.56, 17367530.45, 7324184.56]);
projection.setWorldExtent([-180, -86, 180, 86]);
const cells = new ol.source.Vector({wrapX: false});
const boundary = new ol.source.Vector({wrapX: false});
const world = new ol.layer.Vector({
  source: new ol.source.Vector({url: 'world.geojson', format, wrapX: false,
    attributions: 'Made with Natural Earth'}),
  style: new ol.style.Style({fill: new ol.style.Fill({color: '#d4dfce'}),
    stroke: new ol.style.Stroke({color: '#bccbb8', width: 0.6})})
});
const map = new ol.Map({target: 'map', layers: [world,
  new ol.layer.Vector({source: boundary, style: new ol.style.Style({
    stroke: new ol.style.Stroke({color: '#327355', width: 1.4}),
    fill: new ol.style.Fill({color: 'rgba(255,255,255,0.06)'})})}),
  new ol.layer.Vector({source: cells, style: new ol.style.Style({
    fill: new ol.style.Fill({color: 'rgba(232,116,54,0.7)'}),
    stroke: new ol.style.Stroke({color: '#bd592d', width: 0.7})})})],
  view: new ol.View({projection, center: [0, 0], zoom: 1, minZoom: 0, maxZoom: 16,
    extent: projection.getExtent(), showFullExtent: true})
});
const readFeatures = (data) => format.readFeatures(data, {dataProjection: 'EPSG:4326', featureProjection: projection});
function fitArea() {
  if (currentBoundary) map.getView().fit(currentBoundary.getGeometry().getExtent(), {
    padding: [35, 35, 35, 35], duration: 250, maxZoom: 7});
}
function nextDay(day) {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}
async function post(path, fields, signal) {
  const response = await fetch(path, {method: 'POST', signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({release_id: config.release_id, ...fields})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'The request failed. Please try again.');
  return data;
}
async function loadCells(area, date, signal) {
  let cursor = null, first = true;
  do {
    const data = await post('/v2/hotspots/query', {area_name: area, date, page_size: 1000, cursor}, signal);
    if (signal.aborted) return;
    if (first) {
      $('count').textContent = numbers.format(data.active_cell_count);
      $('result-area').textContent = data.area_name;
      currentBoundary = readFeatures(config.boundaries).find((item) => item.get('area_id') === data.area_id);
      boundary.clear();
      if (currentBoundary) boundary.addFeature(currentBoundary);
      fitArea();
      first = false;
    }
    cells.addFeatures(readFeatures(data));
    $('progress').textContent = data.active_cell_count === 0
      ? 'No matching cells in the supplied files for this date.'
      : `${numbers.format(cells.getFeatures().length)} of ${numbers.format(data.active_cell_count)} cells loaded`;
    cursor = data.next_cursor;
  } while (cursor);
}
function renderDays(days, date, area) {
  $('bars').replaceChildren();
  const maximum = Math.max(1, ...days.map((day) => day.active_cell_count));
  for (const day of days) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'day'; button.dataset.date = day.date;
    button.setAttribute('aria-pressed', String(day.date === date));
    button.setAttribute('aria-label', `${day.date}: ${numbers.format(day.active_cell_count)} active cells, coverage unknown`);
    button.title = `${day.date} · ${numbers.format(day.active_cell_count)} cells`;
    const bar = document.createElement('span');
    bar.style.setProperty('--height', `${day.active_cell_count / maximum * 100}%`);
    button.append(bar);
    button.onclick = () => { $('area').value = area; $('date').value = day.date; load(false); };
    $('bars').append(button);
  }
  $('first-day').textContent = days[0]?.date.slice(8) || '—';
  $('last-day').textContent = days.at(-1)?.date.slice(8) || '—';
}
async function loadDays(area, date, signal) {
  const first = `${date.slice(0, 7)}-01`;
  const following = new Date(`${first}T00:00:00Z`);
  following.setUTCMonth(following.getUTCMonth() + 1);
  const start = first < config.start_date ? config.start_date : first;
  const next = following.toISOString().slice(0, 10);
  const end = next > nextDay(config.end_date) ? nextDay(config.end_date) : next;
  const data = await post('/v2/hotspots/summaries/query', {area_name: area, start_date: start, end_date: end}, signal);
  if (signal.aborted) return;
  $('month').textContent = new Date(`${date}T00:00:00Z`).toLocaleDateString('en', {month: 'long', year: 'numeric', timeZone: 'UTC'});
  renderDays(data.days, date, data.area_name);
}
async function load(withDays = true) {
  if (!$('query').reportValidity()) return;
  controller?.abort();
  controller = new AbortController();
  const signal = controller.signal;
  const area = $('area').value.trim(), date = $('date').value;
  cells.clear(); boundary.clear(); currentBoundary = null; $('cell').hidden = true;
  $('result-area').textContent = area;
  $('count').textContent = '—'; $('progress').textContent = 'Loading saved hotspot cells…';
  $('error').hidden = true; $('show').disabled = true;
  if (withDays) { $('bars').replaceChildren(); $('month').textContent = 'Loading daily counts…'; }
  else document.querySelectorAll('.day').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.date === date)));
  try {
    await loadCells(area, date, signal);
    if (withDays) await loadDays(area, date, signal);
  } catch (error) {
    if (signal.aborted) return;
    controller.abort(); cells.clear(); boundary.clear(); currentBoundary = null;
    $('count').textContent = '—'; $('progress').textContent = 'Could not load this selection.';
    $('bars').replaceChildren(); $('month').textContent = 'Daily counts unavailable';
    $('error').textContent = error.message; $('error').hidden = false;
  } finally {
    if (controller.signal === signal) $('show').disabled = false;
  }
}
$('query').onsubmit = (event) => { event.preventDefault(); load(); };
$('fit').onclick = fitArea;
map.on('singleclick', (event) => {
  const feature = map.forEachFeatureAtPixel(event.pixel, (item) => item.get('cell_id') ? item : undefined);
  $('cell').hidden = !feature;
  if (feature) $('cell').textContent = `Cell ${feature.get('cell_id')} · ${$('date').value} UTC`;
});
async function start() {
  try {
    const response = await fetch('/app/config');
    if (!response.ok) throw new Error('The local database is unavailable.');
    config = await response.json();
    $('date').min = config.start_date; $('date').max = config.end_date; $('date').value = config.end_date;
    $('range').textContent = `Available dates: ${config.start_date} to ${config.end_date}.`;
    await load();
  } catch (error) {
    $('error').textContent = error.message; $('error').hidden = false;
    $('progress').textContent = 'Connection failed.';
  }
}
start();

$('open-about').onclick = () => $('about').showModal();
$('close-about').onclick = () => $('about').close();
