```markdown
# 🌱 AI Weed Detection & Smart Crop Monitoring

<div align="center">

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
<img src="https://img.shields.io/badge/YOLOv8-Ultralytics-00FFFF?style=for-the-badge&logo=yolo"/>
<img src="https://img.shields.io/badge/Raspberry%20Pi-4B-C51A4A?style=for-the-badge&logo=raspberrypi&logoColor=white"/>
<img src="https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white"/>
<img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge"/>
<img src="https://img.shields.io/badge/Status-Active-22c55e?style=for-the-badge"/>

<br/><br/>

> **Real-time AI weed detection & crop monitoring system**  
> running on Raspberry Pi 4B with YOLOv8, servo pan/tilt, laser targeting and live Web Dashboard.

<br/>

[📖 Documentation](#-getting-started) · [🔌 Hardware](#-hardware) · [🌐 Web Dashboard](#-web-dashboard) · [🗺️ Roadmap](#️-roadmap)

</div>

---

## 📌 Overview

**AI Weed Detection** là hệ thống nhúng chạy trên **Raspberry Pi 4B**, sử dụng **YOLOv8** phát hiện cỏ dại và theo dõi cây trồng theo thời gian thực.

Khi phát hiện cỏ dại, hệ thống tự động:
- Điều khiển **servo pan/tilt** (PCA9685) để aim vào mục tiêu
- Khai hoả **laser pulse** tiêu diệt cỏ
- Dừng **motor L298N** trong quá trình xử lý
- Ghi nhận và hiển thị dữ liệu lên **Web Dashboard**

```
Camera ──→ YOLOv8 ──→ error_x / error_y ──→ Servo Pan/Tilt ──→ Laser
                  └──→ Crop Tracking ──→ Web Dashboard (Flask :5000)
```

<details>
<summary>📊 Chi tiết pipeline</summary>

```
┌──────────────────────────────────────────────────────────┐
│                    Raspberry Pi 4B                        │
│                                                          │
│  Camera (USB / CSI)                                      │
│        │                                                 │
│        ▼                                                 │
│  YOLOv8 Inference  (.pt / .onnx)                         │
│        │                                                 │
│        ├── class = weed ──→ State Machine                │
│        │                   FORWARD → STOPPED             │
│        │                   → TRACKING → FIRING           │
│        │                   → COOLDOWN                    │
│        │                        │                        │
│        │                   Servo PCA9685  (pan / tilt)   │
│        │                   Laser pulse   (50ms, cap 1s)  │
│        │                   Motor L298N   (stop / go)     │
│        │                                                 │
│        └── class = crop ──→ Crop Tracker                 │
│                             → Capture image              │
│                             → Classify stage             │
│                             → Growth history             │
│                                  │                       │
│                             Web Dashboard  :5000         │
└──────────────────────────────────────────────────────────┘
```

</details>

---

## ✨ Features

|  | Feature | Description |
|--|---------|-------------|
| 🧠 | **YOLOv8 Realtime** | Hỗ trợ `.pt` và `.onnx`, tự chọn backend tối ưu |
| 🔄 | **State Machine** | `FORWARD → STOPPED → TRACKING → FIRING → COOLDOWN` |
| 🎯 | **Servo Pan/Tilt** | PCA9685 I2C, góc 20–160°, P-controller + offset calibration |
| 🔦 | **Laser Pulse** | Xung 50ms, hard cap 1s, `try/finally` đảm bảo OFF |
| ⚙️ | **Motor L298N** | Tự hành, dừng khi phát hiện cỏ, chống spam GPIO |
| 🌐 | **Web Dashboard** | Flask `:5000` — live stream, KPI cards, crop management |
| 🌿 | **Crop Tracking** | Chụp ảnh, phân loại giai đoạn, lịch sử tăng trưởng |
| 🛡️ | **Safety System** | SIGTERM handler, watchdog 30s, laser failsafe |
| 💻 | **Simulation Mode** | Chạy trên PC không cần GPIO |

---

## 📁 Project Structure

```
detect-iot/
│
├── 📄 main.py                        # Entry point — state machine + web server
├── 📄 run_weed_laser.py              # Multi-target weed + laser runner
├── 📄 requirements.txt               # Python dependencies
│
├── 🔌 hardware/                      # Hardware abstraction layer
│   ├── wiring.py                     #   Central pin mapping
│   ├── laser_control.py              #   Laser pulse + safety cap
│   ├── motor_l298n.py                #   L298N motor driver
│   ├── servo_control.py              #   Servo GPIO PWM (fallback)
│   └── servo_pca9685.py              #   Servo PCA9685 I2C (primary)
│
├── 🧠 models/                        # Trained model weights
│   ├── best.pt                       #   YOLOv8 PyTorch
│   └── best.onnx                     #   ONNX — optimized for Pi
│
├── 🛠️ utils/                         # Utility modules
│   ├── camera_pi.py                  #   USB / CSI camera abstraction
│   ├── coordinate_convert.py         #   Pixel → servo angle
│   ├── rt_tasks.py                   #   Real-time task helpers
│   └── shared_state.py               #   Thread-safe state (Web ↔ detection)
│
├── 🌐 webapp/                        # Web Dashboard
│   ├── app.py                        #   Flask server + REST API
│   ├── templates/index.html          #   Dashboard UI
│   └── static/style.css              #   Stylesheet
│
├── 📜 scripts/                       # Utility scripts
│   ├── selftest_pi_hardware.py       #   Hardware self-test
│   ├── setup_samba_pi.sh             #   Samba file share setup
│   └── deploy.sh                     #   One-command deploy
│
├── ⚙️ config/                        # YOLO dataset config
├── 📷 captures/                      # Crop snapshot storage
└── 📖 docs/
    └── CHUCNANG.md                   # Feature roadmap
```

---

## 🔌 Hardware

### Bill of Materials

| Component | Model | Interface | Notes |
|-----------|-------|-----------|-------|
| MCU | Raspberry Pi 4B 2GB+ | — | 64-bit OS required |
| Camera | USB Webcam / Pi Camera v2/v3 | USB / CSI | |
| Servo Driver | PCA9685 16-ch | I2C | |
| Servo Pan | Standard Servo | PCA9685 Ch.14 | 20–160° |
| Servo Tilt | Standard Servo | PCA9685 Ch.15 | 20–160° |
| Laser | Diode + NPN Transistor | BOARD 16 | |
| Motor Driver | L298N | BOARD 32, 33 | |

### Wiring Diagram

```
Raspberry Pi 4B
│
├── I2C ──────────────────→ PCA9685
│                               ├── Ch.14 ──→ Servo Pan
│                               └── Ch.15 ──→ Servo Tilt
│
├── BOARD 16 ─→ Transistor ──→ Laser (+)
│
├── BOARD 32 ─────────────→ L298N IN3
└── BOARD 33 ─────────────→ L298N IN4
```

> 💡 Toàn bộ pin mapping tập trung tại `hardware/wiring.py`

---

## 🚀 Getting Started

### Prerequisites

- Raspberry Pi 4B — Raspberry Pi OS **64-bit** (Bullseye / Bookworm)
- Python **3.9+**
- I2C & Camera interface enabled

### 1 — Clone the repository

```bash
git clone https://github.com/your-username/ai-weed-detection.git
cd ai-weed-detection
```

### 2 — Install dependencies

**Option A: One-command deploy (recommended)**

```bash
sudo bash scripts/deploy.sh
```

**Option B: Manual install**

```bash
# System packages
sudo apt update && sudo apt install -y python3-pip python3-picamera2 i2c-tools

# Enable I2C & Camera
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_camera 0

# Python packages
pip install -r requirements.txt
pip install adafruit-circuitpython-servokit flask

# Setup directories
mkdir -p logs captures models

# Copy trained model
scp best.pt pi@<pi-ip>:/home/pi/ai-weed-detection/models/
```

### 3 — Run

```bash
# ✅ Production — Web Dashboard enabled
python main.py --picam2 --web --fps 8

# 🔍 Debug — with preview window
python main.py --camera 0 --show

# 🔫 Multi-target weed + laser
python run_weed_laser.py --pca9685 --show --state-debug-log

# 🔧 Hardware self-test
python scripts/selftest_pi_hardware.py

# 🌐 Web Dashboard standalone
python webapp/app.py
```

---

## ⚙️ CLI Reference

```bash
python main.py [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--model PATH` | `models/best.pt` | Model path — `.pt` or `.onnx` |
| `--camera INT` | `0` | USB camera device index |
| `--picam2` | `False` | Use Pi Camera Module (CSI) |
| `--conf FLOAT` | `0.2` | Detection confidence threshold |
| `--fps INT` | `10` | Target inference FPS |
| `--imgsz INT` | `320` | Inference input size (px) |
| `--show` | `False` | Show debug preview window |
| `--web` | `False` | Enable Web Dashboard |
| `--web-port INT` | `5000` | Web Dashboard port |
| `--pan-gain FLOAT` | `0.06` | P-gain — pan servo |
| `--tilt-gain FLOAT` | `0.06` | P-gain — tilt servo |
| `--offset-pan FLOAT` | `0` | Laser-camera pan offset (°) |
| `--offset-tilt FLOAT` | `0` | Laser-camera tilt offset (°) |
| `--laser-pulse-ms INT` | `50` | Laser pulse duration (ms) |
| `--max-shots INT` | `3` | Max shots per weed target |
| `--state-timeout-sec INT` | `30` | Watchdog reset timeout (s) |

---

## 🔄 State Machine

```mermaid
stateDiagram-v2
    [*] --> FORWARD

    FORWARD --> STOPPED : Weed detected
    STOPPED --> TRACKING : Begin tracking
    TRACKING --> FIRING : Target in deadband
    FIRING --> COOLDOWN : Shot fired
    COOLDOWN --> TRACKING : More weeds remain
    COOLDOWN --> FORWARD : No weeds
    TRACKING --> FORWARD : Target lost
    FORWARD --> FORWARD : Watchdog timeout (30s)
```

---

## 🌐 Web Dashboard

Truy cập **`http://<pi-ip>:5000`** khi chạy với `--web`

### Pages

| Page | Description |
|------|-------------|
| **Overview** | Camera live stream · 4 KPI cards · Activity chart |
| **Crop List** | Bảng danh sách · Search · Filter · Click → detail |
| **Crop Detail** | Ảnh chụp · Kích thước · Giai đoạn · Lịch sử tăng trưởng |

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard HTML |
| `GET` | `/video_feed` | MJPEG live stream — 20 FPS |
| `GET` | `/api/stats` | Detection statistics |
| `GET` | `/api/plants` | Plant list |
| `GET` | `/api/plants/<id>` | Plant detail |
| `GET` | `/api/plants/<id>/image` | Plant snapshot |
| `GET` | `/api/plants/<id>/history` | Growth history |
| `GET` | `/health` | Health check |

---

## 🛡️ Safety System

| Mechanism | Description |
|-----------|-------------|
| **Laser hard cap** | Max 1 000ms/pulse — `try/finally` guarantees OFF |
| **SIGTERM handler** | `systemctl stop` → laser OFF trong < 100ms |
| **Watchdog** | State kẹt > 30s → force `FORWARD` |
| **Max shots** | 3 phát/mục tiêu → tiếp tục di chuyển |
| **Failsafe finally** | Laser OFF trước mọi cleanup |
| **GPIO isolation** | Mỗi module tự cleanup pin riêng |

> [!WARNING]
> Luôn đeo **kính bảo hộ laser** đúng bước sóng trước khi bật laser > 5mW.  
> Laser công suất cao chiếu vào mắt = **mù vĩnh viễn**.

---

## 🎯 Laser Calibration Guide

> **Công thức để bắn TRÚNG:** Code đúng + Offset calibrate + Gain phù hợp + Laser đủ công suất + Model nhận diện tốt

### Step 1 — Calibrate laser-camera offset

```bash
# Bắt đầu offset = 0, bắn vào giấy A4
python main.py --picam2 --show --offset-pan 0 --offset-tilt 0

# Đo laser lệch khỏi tâm bbox → điều chỉnh
python main.py --picam2 --show --offset-pan -3 --offset-tilt 2

# Lặp đến khi laser trúng tâm
```

### Step 2 — Tune servo gain

| Gain Value | Behavior |
|------------|----------|
| `> 0.10` | ❌ Servo rung, không settle |
| `0.04 – 0.07` | ✅ Smooth, settle nhanh |
| `< 0.02` | ❌ Quá chậm, không kịp aim |

### Step 3 — Laser power selection

| Power | Target | Pulse Duration |
|-------|--------|----------------|
| 5mW | Test / calibration only | — |
| 500mW – 1W | Young / soft weeds | 200–500ms |
| > 2W | Mature / thick weeds | 100–300ms |

```bash
# Sau khi calibrate xong, tăng pulse
python main.py --picam2 --laser-pulse-ms 300
```

---

## ✅ Pre-flight Checklist

```
☐  1.  selftest_pi_hardware.py → ALL PASS
☐  2.  YOLO predict test image → detection correct
☐  3.  Run --show → bounding boxes đúng vị trí
☐  4.  Rút dây laser → servo aim đúng hướng
☐  5.  Cắm laser 5mW → bắn giấy A4 → đo offset
☐  6.  Calibrate --offset-pan & --offset-tilt → laser trúng tâm
☐  7.  Tăng --laser-pulse-ms lên 200–500ms
☐  8.  Đổi sang laser công suất cao (> 500mW)
☐  9.  ⚠️  ĐEO KÍNH BẢO HỘ LASER trước khi bật laser mạnh
☐  10. Test ngoài thực tế
```

---

## 🔧 Systemd Service

```bash
# Install & enable
sudo cp scripts/weed-detect.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weed-detect

# Manage
sudo systemctl status weed-detect        # Status
sudo systemctl stop weed-detect          # Stop
sudo systemctl restart weed-detect       # Restart
sudo journalctl -u weed-detect -f        # Live logs
```

---

## 🗺️ Roadmap

### ✅ v1.0 — Completed

- [x] YOLOv8 realtime inference — `.pt` & `.onnx`
- [x] 5-state machine — `FORWARD / STOPPED / TRACKING / FIRING / COOLDOWN`
- [x] Servo pan/tilt — PCA9685 + P-controller + offset calibration
- [x] Laser pulse — safety hard cap + `try/finally` failsafe
- [x] Motor L298N — auto-stop on weed detection
- [x] Web Dashboard — Flask, MJPEG stream, REST API
- [x] Crop tracking — capture, stage classification, growth history
- [x] SIGTERM / SIGINT graceful shutdown
- [x] Simulation mode — no GPIO required on PC

### 🚧 v1.1 — In Progress

- [ ] Multi-class crop detection — Lettuce, Tomato, Cabbage...
- [ ] Per-species plant count
- [ ] Auto CSV history export
- [ ] Growth trend chart on dashboard
- [ ] Abnormal growth alert / notification

### 📋 v2.0 — Planned

- [ ] **Cloud sync** — push telemetry & images to remote server
- [ ] **Mobile app** — real-time dashboard on Android / iOS
- [ ] **Multi-Pi mesh** — multiple robots, unified dashboard
- [ ] **Advanced AI** — disease classification, yield prediction
- [ ] **Auto-calibration** — automatic laser-camera alignment
- [ ] **Solar power** — Li-Po + solar panel for field deployment
- [ ] **GPS mapping** — geo-referenced plant map
- [ ] **Weather API** — correlate growth data with weather
- [ ] **OTA update** — remote model & firmware update

---

## 📋 Notes

- Model classes: `0 = crop` · `1 = weed`
- PC without GPIO → auto **Simulation Mode**
- Pin mapping tập trung tại `hardware/wiring.py`
- Dashboard standalone: `python webapp/app.py`

---

## 📄 License

Distributed under the **MIT License** — see [`LICENSE`](LICENSE) for details.

---

<div align="center">

**Made with ❤️ by Đào Văn Phong**

<br/>

*Raspberry Pi 4B · YOLOv8 · Flask · PCA9685 · L298N · Python*

<br/>

⭐ Star this repo if you find it useful!

</div>
```
