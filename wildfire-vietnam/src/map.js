import { Map, NavigationControl, ScaleControl, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

setWorkerUrl(workerUrl)

export const fireBands = [
  { min: 1, label: '1–4', color: '#ffd17b' },
  { min: 5, label: '5–9', color: '#f79045' },
  { min: 10, label: '10–19', color: '#e04e30' },
  { min: 20, label: '20 trở lên', color: '#a7272d' },
]

const boundaryUrl = `${import.meta.env.BASE_URL}data/vietnam-boundary.geojson`
const vietnamBounds = [[101.8, 8.3], [109.7, 23.45]]

export function createMap(grids, { onCell, onReady, onError }) {
  const map = new Map({
    container: 'map',
    bounds: vietnamBounds,
    fitBoundsOptions: { padding: 34, duration: 0 },
    maxZoom: 16,
    renderWorldCopies: false,
    dragRotate: false,
    pitchWithRotate: false,
    style: {
      version: 8,
      sources: {
        basemap: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          maxzoom: 19,
          tileSize: 256,
          attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        },
        vietnam: {
          type: 'geojson',
          data: boundaryUrl,
          attribution: '<a href="https://www.geoboundaries.org/api/current/gbOpen/VNM/ADM0/">geoBoundaries</a> · CC BY 4.0',
        },
        fires: { type: 'geojson', data: grids },
      },
      layers: [
        { id: 'background', type: 'background', paint: { 'background-color': '#dce9ee' } },
        { id: 'basemap', type: 'raster', source: 'basemap', paint: { 'raster-saturation': -0.62 } },
        { id: 'country-fill', type: 'fill', source: 'vietnam', paint: {
          'fill-color': '#f4f0df', 'fill-opacity': 0.27,
        } },
        { id: 'country-edge', type: 'line', source: 'vietnam', paint: {
          'line-color': '#496658', 'line-opacity': 0.85, 'line-width': 1.2,
        } },
        { id: 'fire-fill', type: 'fill', source: 'fires', paint: {
          'fill-color': ['step', ['get', 'detection_count'], fireBands[0].color,
            ...fireBands.slice(1).flatMap(({ min, color }) => [min, color])],
          'fill-opacity': 0.84,
        } },
        { id: 'fire-edge', type: 'line', source: 'fires', paint: {
          'line-color': '#7b362a', 'line-opacity': 0.53, 'line-width': 0.7,
        } },
        { id: 'selected-edge', type: 'line', source: 'fires', filter: ['==', ['id'], ''], paint: {
          'line-color': '#3e1613', 'line-width': 2.5,
        } },
      ],
    },
  })
  map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
  map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
  map.getCanvas().setAttribute('aria-label', 'Bản đồ ô lưới cháy rừng Việt Nam')

  let tilesUnavailable = false
  map.on('error', (event) => {
    if (event.sourceId === 'basemap') {
      if (!tilesUnavailable) {
        tilesUnavailable = true
        map.setLayoutProperty('basemap', 'visibility', 'none')
        map.setPaintProperty('country-fill', 'fill-opacity', 0.92)
      }
      return
    }
    console.error(event.error)
    onError()
  })
  map.once('load', onReady)
  map.on('mouseenter', 'fire-fill', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mouseleave', 'fire-fill', () => { map.getCanvas().style.cursor = '' })
  map.on('click', (event) => {
    if (!map.getLayer('fire-fill')) return
    const [feature] = map.queryRenderedFeatures(event.point, { layers: ['fire-fill'] })
    map.setFilter('selected-edge', ['==', ['id'], feature?.id ?? ''])
    onCell(feature?.properties)
  })

  return map
}
