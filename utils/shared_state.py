"""
Thread-safe shared state giữa main.py (detection loop) và webapp (Flask).

- Frame mới nhất (có bounding box overlay) cho MJPEG stream
- Stats (weed_count, crop_count, laser_fired, system_status)
- Plants list + snapshot ảnh + lịch sử tăng trưởng + mô tả tiếng Việt
"""
from __future__ import annotations

import os
import threading
import time
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.json")

import cv2

# Thư mục lưu ảnh chụp cây trồng
CAPTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")

# Phân loại giai đoạn theo diện tích (px²)
STAGE_THRESHOLDS = {"Seedling": 5000, "Vegetative": 25000}


def classify_stage(area_px: float) -> str:
    if area_px < STAGE_THRESHOLDS["Seedling"]:
        return "Seedling"
    elif area_px < STAGE_THRESHOLDS["Vegetative"]:
        return "Vegetative"
    return "Mature"


def classify_health(area_px: float, prev_area: float | None) -> str:
    if prev_area is None:
        return "Growing"
    change = (area_px - prev_area) / max(prev_area, 1) * 100
    if change < -20:
        return "Abnormal"
    elif change > 20:
        return "Growing"
    return "Normal"


def generate_description(plant_type: str, plant_id: int, stage: str,
                         area_px: float, health: str, prev_area: float | None) -> str:
    """Tạo mô tả tiếng Việt về tình trạng cây."""
    stage_vn = {"Seedling": "Cây con 🌱", "Vegetative": "Phát triển 🌿", "Mature": "Trưởng thành 🥬"}
    health_vn = {"Normal": "bình thường", "Abnormal": "bất thường ⚠️", "Growing": "đang phát triển tốt 🌱"}

    desc = f"{stage_vn.get(stage, stage)}. Diện tích tán lá: {int(area_px):,} px². "

    if prev_area is not None and prev_area > 0:
        change_pct = (area_px - prev_area) / prev_area * 100
        direction = "tăng" if change_pct >= 0 else "giảm"
        desc += f"So với lần đo trước: {direction} {abs(change_pct):.1f}%. "

    desc += f"Tình trạng: {health_vn.get(health, health)}."

    if stage == "Seedling":
        desc += " Cần tưới nước đều đặn, tránh cỏ dại cạnh tranh."
    elif stage == "Vegetative":
        desc += " Đang phát triển mạnh, cần bổ sung dinh dưỡng."
    elif stage == "Mature":
        desc += " Có thể thu hoạch trong thời gian tới."

    if health == "Abnormal":
        desc += " ⚠️ Kiểm tra sâu bệnh hoặc thiếu dinh dưỡng!"

    return desc


@dataclass
class PlantInfo:
    plant_id: int
    plant_type: str
    area_px: float
    height_px: float
    width_px: float
    stage: str
    health: str
    last_seen: float
    image_path: str = ""
    description: str = ""
    gemini_result: dict | None = None


class SharedState:
    """Thread-safe singleton chia sẻ dữ liệu giữa detection loop và Flask."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Any = None
        self._stats: dict[str, Any] = {
            "weed_detected": 0,
            "crop_detected": 0,
            "laser_fired": 0,
            "system_status": "STARTING",
            "state": "FORWARD",
            "fps": 0.0,
            "uptime_sec": 0.0,
        }
        self._plants: OrderedDict[int, PlantInfo] = OrderedDict()
        self._plant_history: dict[int, list[dict[str, Any]]] = {}
        self._start_time = time.time()
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        
        # Cấu hình cài đặt động
        self._settings: dict[str, Any] = {
            "conf": 0.2,
            "laser_pulse_ms": 50,
            "max_shots": 3,
            "static_cam": True,
            "cam_height": 10.0,
            "servo_height": 15.0,
            "cam_tilt": 27.5,
            "offset_pan": 0.0,
            "offset_tilt": 0.0,
            "gemini_api_key": "",
        }
        self._load_settings()

    def _load_settings(self) -> None:
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._settings.update(data)
        except Exception as e:
            print(f"[SETTINGS] Lỗi tải cấu hình: {e}")

    def _save_settings(self) -> None:
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=4)
        except Exception as e:
            print(f"[SETTINGS] Lỗi lưu cấu hình: {e}")

    # ---- Settings ----
    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    def update_settings(self, **kwargs: Any) -> None:
        with self._lock:
            self._settings.update(kwargs)
            self._save_settings()

    # ---- Frame ----
    def update_frame(self, frame: Any) -> None:
        with self._lock:
            self._frame = frame.copy() if frame is not None else None

    def get_frame(self) -> Any | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    # ---- Stats ----
    def update_stats(self, **kwargs: Any) -> None:
        with self._lock:
            self._stats.update(kwargs)
            self._stats["uptime_sec"] = round(time.time() - self._start_time, 1)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)

    # ---- Plants ----
    def upsert_plant(self, plant: PlantInfo) -> None:
        with self._lock:
            self._plants[plant.plant_id] = plant

    def get_plants(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": p.plant_id,
                    "type": p.plant_type,
                    "area_px": int(p.area_px),
                    "height_px": int(p.height_px),
                    "width_px": int(p.width_px),
                    "stage": p.stage,
                    "health": p.health,
                    "has_image": bool(p.image_path and os.path.exists(p.image_path)),
                }
                for p in self._plants.values()
            ]

    def get_plant(self, plant_id: int) -> dict[str, Any] | None:
        with self._lock:
            p = self._plants.get(plant_id)
            if p is None:
                return None
            return {
                "id": p.plant_id,
                "type": p.plant_type,
                "area_px": int(p.area_px),
                "height_px": int(p.height_px),
                "width_px": int(p.width_px),
                "stage": p.stage,
                "health": p.health,
                "last_seen": p.last_seen,
                "has_image": bool(p.image_path and os.path.exists(p.image_path)),
                "description": p.description,
                "gemini_result": p.gemini_result or {},
            }

    def set_gemini_result(self, plant_id: int, result: dict[str, str]) -> None:
        with self._lock:
            p = self._plants.get(plant_id)
            if p is not None:
                p.gemini_result = result

    def update_plant_from_gemini(self, plant_id: int, result: dict[str, str]) -> None:
        with self._lock:
            p = self._plants.get(plant_id)
            if p is not None:
                if result.get("plant_type"):
                    p.plant_type = result["plant_type"]
                if result.get("growth_stage"):
                    p.stage = result["growth_stage"]
                if result.get("health_status"):
                    p.health = result["health_status"]
                obs = result.get("observation", "")
                rec = result.get("recommendation", "")
                p.description = f"**Nhận định AI:** {obs}\n\n**Khuyến nghị:** {rec}"

    def get_gemini_result(self, plant_id: int) -> dict[str, str] | None:
        with self._lock:
            p = self._plants.get(plant_id)
            if p is not None:
                return p.gemini_result
            return None

    # ---- Plant images ----
    def save_plant_image(self, plant_id: int, crop_image: Any) -> str:
        path = os.path.join(CAPTURE_DIR, f"plant_{plant_id}_latest.jpg")
        cv2.imwrite(path, crop_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path

    def get_plant_image_path(self, plant_id: int) -> str | None:
        path = os.path.join(CAPTURE_DIR, f"plant_{plant_id}_latest.jpg")
        return path if os.path.exists(path) else None

    # ---- Growth history ----
    def add_growth_record(self, plant_id: int, area_px: float, stage: str) -> None:
        with self._lock:
            self._plant_history.setdefault(plant_id, []).append({
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": time.time(),
                "area_px": int(area_px),
                "stage": stage,
            })
            if len(self._plant_history[plant_id]) > 100:
                self._plant_history[plant_id] = self._plant_history[plant_id][-100:]

    def get_plant_history(self, plant_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._plant_history.get(plant_id, []))

    def get_previous_area(self, plant_id: int) -> float | None:
        history = self._plant_history.get(plant_id, [])
        if len(history) >= 2:
            return float(history[-2]["area_px"])
        return None


# Singleton instance
state = SharedState()

