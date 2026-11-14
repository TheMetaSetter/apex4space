# Bản đồ ô cháy rừng Việt Nam

Frontend JavaScript dùng MapLibre GL JS để hiển thị dữ liệu mô phỏng ngày 14/11/2026. Bản đồ tô các ô có phát hiện, hiển thị chú giải theo số lượt phát hiện và hiện chi tiết khi bấm vào ô.

## Chạy demo

Cần Node.js 24 và npm. Từ thư mục chứa README này, chạy:

```powershell
npm.cmd ci
npm.cmd run dev
```

Mở địa chỉ Vite in trong terminal. Chạy `npm.cmd run build` để xuất bản build vào `dist/`. Bản đồ nền OpenStreetMap cần kết nối Internet. Dữ liệu lưới và ranh giới được phục vụ cùng frontend.

## Mock response

File `public/mock/vn-2026-11-14.json` gồm `country`, `date`, `is_mock`, `general_statistics` và `detail_grids_info`. `general_statistics` chứa số ô và tổng lượt phát hiện. `detail_grids_info` là GeoJSON FeatureCollection với một feature mỗi ô. Các trường `grid_id`, `detection_count` và `clipped` mô tả ô. Frontend tải và hiển thị trực tiếp response.

## Sinh lại và kiểm tra dữ liệu

Cần Python 3.14. Chạy từ thư mục dự án:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe scripts/generate_mock.py
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Script tạo ô 10.000 × 10.000 mét trong hệ Lambert Azimuthal Equal Area, cắt ô theo ranh giới Việt Nam và xuất WGS 84. Mỗi ô có một ID ổn định dựa trên hàng và cột. Ô sát biên giới có thể nhỏ hơn 100 km². Số lượt phát hiện là số giả lập từ seed cố định.

Ranh giới quốc gia do geoBoundaries gbOpen cung cấp dưới giấy phép CC BY 4.0, với năm biểu diễn 2016. Metadata, liên kết bản tải cố định và SHA-256 nằm trong `data/boundary-source.json`. Điều kiện bao phủ của mọi ô được kiểm tra theo chính tệp ranh giới này. [Nguồn ranh giới](https://www.geoboundaries.org/api/current/gbOpen/VNM/ADM0/) · [Giấy phép](https://creativecommons.org/licenses/by/4.0/)
