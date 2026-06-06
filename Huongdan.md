# PLAN PHÁT TRIỂN DỰ ÁN MỚI

## Tên đề tài

AI Weed Detection and Smart Crop Monitoring System Using Raspberry Pi, YOLO and Gemini Vision

---

# 1. Mục tiêu dự án

Xây dựng hệ thống nông nghiệp thông minh có khả năng:

* Phát hiện cỏ dại theo thời gian thực
* Điều khiển laser xử lý cỏ dại
* Tự động di chuyển tìm kiếm khu vực mới
* Nhận diện cây trồng
* Phân tích mức độ tăng trưởng cây
* Đánh giá tình trạng cây bằng AI Vision
* Hiển thị kết quả trên Web Dashboard

---

# 2. Kiến trúc hệ thống

Camera
↓
Raspberry Pi 4B
↓
YOLO Detection

├── Weed Detection
│     ↓
│  Servo Tracking
│     ↓
│    Laser
│
└── Crop Detection
↓
Crop Analysis
↓
Gemini Vision
↓
Web Dashboard

---

# 3. Các module chính

## Module 1 – Weed Detection

Mô hình YOLO phát hiện:

* Weed
* Crop

Kết quả:

* Bounding Box
* Confidence
* Center Point

---

## Module 2 – Servo Tracking

Điều khiển:

* Pan Servo
* Tilt Servo

Chức năng:

* Xoay laser tới vị trí cỏ

---

## Module 3 – Laser Control

Khi phát hiện cỏ:

* Servo hướng tới mục tiêu
* Laser được kích hoạt

---

## Module 4 – Motor Navigation

Không phát hiện cỏ:

* Robot tiếp tục di chuyển

Phát hiện cỏ:

* Robot dừng lại
* Xử lý mục tiêu

---

## Module 5 – Crop Monitoring

Khi phát hiện cây:

Lưu:

* Vị trí
* Kích thước Bounding Box
* Diện tích cây

Tính:

Area = Width × Height

---

## Module 6 – Growth Analysis

Dựa trên diện tích Bounding Box:

Seedling

Growing

Mature

Ví dụ:

Area < 10000

→ Seedling

Area < 25000

→ Growing

Area > 25000

→ Mature

---

## Module 7 – Gemini Vision Analysis

Sau khi phát hiện cây:

Ảnh cây được cắt riêng.

Gemini Vision phân tích:

* Loại cây
* Giai đoạn phát triển
* Tình trạng sức khỏe
* Nhận xét
* Khuyến nghị

Ví dụ:

Plant Type:
Lettuce

Health:
Good

Observation:
Lá phát triển đồng đều.

Recommendation:
Duy trì điều kiện hiện tại.

---

## Module 8 – Data Logging

Lưu:

* Ảnh gốc
* Ảnh detect
* Kết quả Gemini

CSV:

Date
Plant ID
Area
Growth Stage
Health Status

---

## Module 9 – Web Dashboard

Truy cập:

http://IP_RaspberryPi:5000

Ví dụ:

http://192.168.23.106:5000

---

### Dashboard hiển thị

Live Camera

---

Weed Statistics

Crop Statistics

Laser Status

Motor Status

---

Plant Analysis

Plant Type

Growth Stage

Health Status

---

Growth Chart

Biểu đồ tăng trưởng

---

# 4. Đèn LED trợ sáng

Bổ sung LED trắng công suất thấp.

Mục đích:

* Tăng độ sáng
* Giảm nhiễu ảnh
* Tăng độ chính xác của YOLO
* Hỗ trợ hoạt động trong điều kiện thiếu sáng

LED hoạt động:

* Luôn bật khi hệ thống chạy

hoặc

* Tự động bật khi độ sáng thấp

---

# 5. Chức năng hoàn thành trong 2 ngày

Ngày 1

✓ Hoàn thiện Servo

✓ Hoàn thiện Laser

✓ Hoàn thiện Motor

✓ Hoàn thiện Weed Detection

✓ Tích hợp LED trợ sáng

---

Ngày 2

✓ Flask Web Dashboard

✓ Hiển thị Camera

✓ Hiển thị Weed Count

✓ Hiển thị Crop Count

✓ Nút Analyze Plant

✓ Gemini Vision Analysis

✓ Hiển thị kết quả Gemini

---

# 6. Chức năng tương lai

* Nhận diện nhiều loại cây bằng YOLO
* Theo dõi từng cây nhiều ngày
* Phát hiện sâu bệnh
* Tưới nước tự động
* Điều khiển qua Internet
* Cloud Monitoring

---

# 7. Kết quả mong đợi

Hệ thống có khả năng:

✓ Detect Weed

✓ Detect Crop

✓ Servo Tracking

✓ Laser Elimination

✓ Autonomous Navigation

✓ Growth Analysis

✓ Gemini Vision Analysis

✓ Smart Web Dashboard

Đây là một hệ thống giám sát và xử lý cỏ dại thông minh ứng dụng AI trong nông nghiệp chính xác.
