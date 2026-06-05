# Tổng kết chức năng dự án AI Weed Detection & Smart Crop Monitoring

> **Roadmap phát triển** — đánh dấu `[x]` khi hoàn thành.

---

## 1. Chức năng hiện tại ✅

### 1.1 Phát hiện cỏ dại bằng AI

```
Camera → YOLO → Weed Detection
```

- [x] Camera thu hình ảnh liên tục
- [x] YOLO nhận diện cỏ dại theo thời gian thực
- [x] Hiển thị bounding box
- [x] Hiển thị độ tin cậy (confidence)
- [x] Xác định tọa độ tâm của cỏ

### 1.2 Tracking mục tiêu

```
Tọa độ cỏ → Servo Pan/Tilt → Di chuyển laser
```

- [x] Servo xoay theo vị trí cỏ
- [x] Tự động hướng laser tới vùng phát hiện
- [x] Tracking theo thời gian thực

### 1.3 Tiêu diệt cỏ bằng laser

```
Detect weed → Aim target → Laser ON
```

- [x] Khi phát hiện cỏ: bật laser, chiếu vào vị trí mục tiêu
- [x] State machine: FORWARD → STOPPED → TRACKING → FIRING → COOLDOWN
- [x] Offset calibration camera-laser (`--offset-pan`, `--offset-tilt`)

### 1.4 Robot tự hành tìm kiếm

```
Không phát hiện cỏ → Motor chạy
Phát hiện cỏ → Motor dừng
```

- [x] Xe tự di chuyển
- [x] Khi gặp cỏ: dừng lại, xử lý mục tiêu
- [x] Sau đó tiếp tục tìm kiếm

---

## 2. Chức năng giám sát cây trồng (nâng cấp) 🔜

### 2.1 Nhận diện cây trồng

```
Crop: Lettuce, Tomato, Cabbage, Onion
Weed
```

- [ ] Hệ thống phân biệt Crop / Weed
- [ ] Nhận diện nhiều loại cây trồng (Lettuce, Tomato, Cabbage, Onion...)
- [ ] Train model multi-class

### 2.2 Đếm số lượng cây

```
Tomato: 25
Lettuce: 18
Weed: 7
```

- [ ] Đếm số lượng từng loại cây
- [ ] Đếm số cỏ dại đã phát hiện
- [ ] Thống kê theo thời gian thực

### 2.3 Đánh giá tăng trưởng

```
Chiều cao | Chiều rộng | Diện tích tán lá
```

- [ ] Tính chiều cao, chiều rộng từ bounding box
- [ ] Tính diện tích tán lá (px²)
- [ ] Lưu lịch sử tăng trưởng

### 2.4 Phân loại giai đoạn phát triển

```
Seedling → Vegetative → Mature
```

- [ ] Phân loại theo kích thước / diện tích lá
- [ ] Hiển thị giai đoạn cho từng cây

### 2.5 Phát hiện cây phát triển bất thường

```
Average Height = 30cm
Plant #12 = 18cm → Warning: Abnormal Growth
```

- [ ] Tính trung bình chiều cao / diện tích
- [ ] Cảnh báo cây phát triển bất thường

---

## 3. Web Dashboard Local 🔜

```
http://192.168.x.x:5000
```

### 3.1 Camera realtime

- [ ] Video trực tiếp
- [ ] Bounding box overlay
- [ ] Nhãn đối tượng

### 3.2 Thống kê

```
Weed Detected : 12
Crop Detected : 54
Laser Fired   : 8
System Status : RUNNING
```

- [ ] API `/api/stats` trả về JSON
- [ ] Hiển thị dashboard thống kê

### 3.3 Danh sách cây

| ID  | Loại cây | Diện tích | Trạng thái |
| --- | -------- | --------- | ---------- |
| 1   | Lettuce  | 25000     | Normal     |
| 2   | Tomato   | 18000     | Growing    |
| 3   | Lettuce  | 32000     | Mature     |

- [ ] API `/api/plants` trả về danh sách
- [ ] Bảng HTML hiển thị

### 3.4 Phân tích chi tiết

- [ ] API `/api/plants/<id>` trả về chi tiết
- [ ] Hiển thị: chiều cao, diện tích lá, tăng trưởng, sức khỏe

### 3.5 Biểu đồ tăng trưởng

```
Ngày 1 → Ngày 2 → Ngày 3 → ...
```

- [ ] Biểu đồ chiều cao cây
- [ ] Biểu đồ diện tích lá
- [ ] Biểu đồ tốc độ phát triển

---

## 4. Chức năng quản lý dữ liệu 🔜

### Lưu ảnh

```
capture/
```

- [ ] Lưu ảnh gốc
- [ ] Lưu ảnh detect (có bounding box)

### Lưu lịch sử

```csv
Date,PlantID,Type,Height,Area,Stage
2026-05-15,1,Lettuce,20,15000,Seedling
2026-05-20,1,Lettuce,28,26000,Vegetative
```

- [ ] CSV writer tự động
- [ ] Đọc và hiển thị lịch sử

---

## 5. Kiến trúc hệ thống

```
                CAMERA
                   │
                   ▼
        ┌─────────────────┐
        │ Raspberry Pi 4B │
        │     YOLO AI     │
        └─────────────────┘
             │       │
             ▼       ▼

      Weed Detection   Crop Analysis
             │              │
             │              ├─ Nhận diện cây
             │              ├─ Đếm cây
             │              ├─ Đánh giá tăng trưởng
             │              └─ Lưu dữ liệu

             ▼
      Servo Tracking
             ▼
          Laser

             ▼
       Motor Control

             ▼
       Web Dashboard
```

---

## Lộ trình phát triển

| Giai đoạn | Nội dung                                    | File dự kiến             |
| --------- | ------------------------------------------- | ------------------------ |
| **1**     | Web Dashboard cơ bản (Flask + video stream) | `webapp/`                |
| **2**     | Crop Analysis (đếm cây, phân loại)          | `utils/crop_analysis.py` |
| **3**     | Lưu ảnh + CSV history                       | `utils/data_logger.py`   |
| **4**     | Biểu đồ + phân tích chi tiết                | `webapp/static/`         |
| **5**     | Cảnh báo bất thường                         | `utils/anomaly.py`       |
