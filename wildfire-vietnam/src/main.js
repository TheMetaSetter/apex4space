import 'maplibre-gl/dist/maplibre-gl.css'
import './style.css'
import { createMap, fireBands } from './map.js'

const byId = (id) => document.getElementById(id)
const number = new Intl.NumberFormat('vi-VN')
const date = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'long', timeZone: 'UTC' })
const responseUrl = `${import.meta.env.BASE_URL}mock/vn-2026-11-14.json`
let map

for (const { color, label } of fireBands) {
  const item = document.createElement('li')
  const swatch = document.createElement('span')
  swatch.className = 'swatch'
  swatch.style.backgroundColor = color
  item.append(swatch, label)
  byId('legend-bands').append(item)
}

function setStatus(message, retry = false) {
  byId('status').textContent = message
  byId('status-card').hidden = !message
  byId('retry').hidden = !retry
}

function showCell(cell) {
  byId('selection-detail').textContent = cell
    ? `${cell.grid_id} · ${number.format(cell.detection_count)} lượt phát hiện${cell.clipped ? ' · Ô cắt theo biên giới' : ''}`
    : 'Bấm vào một ô trên bản đồ để xem chi tiết.'
}

async function loadDashboard() {
  map?.remove()
  map = undefined
  setStatus('Đang tải dữ liệu bản đồ…')
  showCell()

  try {
    const response = await fetch(responseUrl)
    if (!response.ok) throw new Error(`Mock data HTTP ${response.status}`)
    const data = await response.json()
    const { general_statistics, detail_grids_info } = data
    byId('country').textContent = data.country.name
    byId('data-date').dateTime = data.date
    byId('data-date').textContent = date.format(new Date(`${data.date}T00:00:00Z`))
    byId('mock-label').hidden = !data.is_mock
    byId('grid-count').textContent = number.format(general_statistics.affected_grid_count)
    byId('detection-count').textContent = number.format(general_statistics.detection_count)

    const empty = detail_grids_info.features.length === 0
    map = createMap(detail_grids_info, {
      onCell: showCell,
      onReady: () => setStatus(empty ? 'Không có ô ghi nhận phát hiện trong ngày này.' : ''),
      onError: () => setStatus('Không tải được lớp bản đồ. Bạn có thể thử lại.', true),
    })
  } catch (error) {
    console.error(error)
    setStatus('Không tải được dữ liệu hoặc không khởi tạo được bản đồ.', true)
  }
}

byId('retry').addEventListener('click', loadDashboard)
loadDashboard()
