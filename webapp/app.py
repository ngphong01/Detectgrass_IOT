"""
Flask Web Dashboard cho Weed Detection System.

Routes:
  GET  /                          - Dashboard HTML
  GET  /video_feed                - MJPEG stream từ camera + bounding box
  GET  /api/stats                 - JSON thống kê
  GET  /api/plants                - JSON danh sách cây
  GET  /api/plants/<id>           - JSON chi tiết cây (kèm mô tả)
  GET  /api/plants/<id>/image     - Ảnh chụp cây trồng
  GET  /api/plants/<id>/history   - Lịch sử tăng trưởng

Chạy:
  python webapp/app.py
  Hoặc tự động start trong main.py khi có --web
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, send_file

from utils.shared_state import CAPTURE_DIR, state

app = Flask(__name__, template_folder="templates", static_folder="static")

# MJPEG stream rate limit (FPS gửi cho browser)
_MJPEG_FPS = 20
_MJPEG_INTERVAL = 1.0 / _MJPEG_FPS

# JPEG quality cho stream
_STREAM_QUALITY = 70

# ==================== HELPERS ====================

def _placeholder_frame() -> np.ndarray:
    """Placeholder khi chưa có frame từ camera."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, "Waiting for camera...", (120, 250),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return img

def _no_image_placeholder() -> bytes:
    """JPEG bytes cho 'no image' (cây chưa được chụp)."""
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.putText(img, "No image", (40, 110),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""

def _generate_frames():
    """MJPEG stream: encode frame từ SharedState thành JPEG, có rate limit."""
    last_send = 0.0
    try:
        while True:
            now = time.monotonic()
            # Rate limit cho browser
            sleep_left = _MJPEG_INTERVAL - (now - last_send)
            if sleep_left > 0:
                time.sleep(sleep_left)
            last_send = time.monotonic()

            frame = state.get_frame()
            if frame is None:
                frame = _placeholder_frame()

            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _STREAM_QUALITY]
            )
            if not ok:
                continue

            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n"
                   + buf.tobytes() + b"\r\n")
    except GeneratorExit:
        # Client disconnect - bình thường
        pass
    except Exception as e:
        print(f"[WEB] MJPEG stream error: {e}")

# ==================== ROUTES ====================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/video_feed")
def video_feed():
    return Response(
        _generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )

@app.route("/api/stats")
def api_stats():
    resp = jsonify(state.get_stats())
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/api/plants")
def api_plants():
    resp = jsonify(state.get_plants())
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/api/plants/<int:plant_id>")
def api_plant_detail(plant_id: int):
    plant = state.get_plant(plant_id)
    if plant is None:
        return jsonify({"error": "Plant not found"}), 404
    resp = jsonify(plant)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/api/plants/<int:plant_id>/image")
def api_plant_image(plant_id: int):
    """Trả về ảnh chụp mới nhất của cây."""
    path = state.get_plant_image_path(plant_id)
    if path is None or not os.path.exists(path):
        resp = Response(_no_image_placeholder(), mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    resp = send_file(path, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.route("/api/plants/<int:plant_id>/history")
def api_plant_history(plant_id: int):
    """Trả về lịch sử tăng trưởng của cây."""
    resp = jsonify(state.get_plant_history(plant_id))
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/health")
def health():
    """Health check cho monitoring/load balancer."""
    return jsonify({"status": "ok", "uptime_sec": state.get_stats().get("uptime_sec", 0)})

# ==================== MAIN ====================

def start_web(host: str = "0.0.0.0", port: int = 5000,
              debug: bool = False) -> None:
    """Khởi động Flask web server (blocking)."""
    print(f"[WEB] Dashboard at http://<raspberry-pi-ip>:{port}")
    app.run(host=host, port=port, debug=debug,
            threaded=True, use_reloader=False)

if __name__ == "__main__":
    start_web()
