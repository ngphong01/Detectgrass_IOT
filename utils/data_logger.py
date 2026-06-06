"""
Data Logger — CSV logging + lưu ảnh detection.

Chức năng:
  - CSVLogger: ghi dữ liệu cây trồng vào CSV tự động
  - save_detection_frame(): lưu ảnh gốc + ảnh có bounding box
  - Thread-safe, auto-create directories

File CSV: logs/plant_history.csv
Ảnh: captures/original/, captures/detected/
"""
from __future__ import annotations

import csv
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("data_logger")

# Thư mục mặc định
_BASE_DIR = Path(__file__).resolve().parent.parent
_LOG_DIR = _BASE_DIR / "logs"
_CAPTURE_DIR = _BASE_DIR / "captures"
_ORIGINAL_DIR = _CAPTURE_DIR / "original"
_DETECTED_DIR = _CAPTURE_DIR / "detected"

# CSV header
_CSV_HEADER = [
    "Date", "PlantID", "Type", "Area", "Height", "Width",
    "Stage", "Health", "GeminiAnalysis",
]


class CSVLogger:
    """Thread-safe CSV logger cho dữ liệu cây trồng."""

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self._path = Path(csv_path) if csv_path else _LOG_DIR / "plant_history.csv"
        self._lock = threading.Lock()
        self._initialized = False
        self._init_file()

    def _init_file(self) -> None:
        """Tạo thư mục và file CSV với header nếu chưa có."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                with open(self._path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(_CSV_HEADER)
                log.info("[CSV] Tạo file mới: %s", self._path)
            self._initialized = True
        except Exception as e:
            log.error("[CSV] Lỗi tạo file: %s", e)

    def log_plant(
        self,
        plant_id: int,
        plant_type: str,
        area: float,
        height: float,
        width: float,
        stage: str,
        health: str,
        gemini_analysis: str = "",
    ) -> None:
        """Ghi một dòng dữ liệu cây vào CSV."""
        if not self._initialized:
            return
        with self._lock:
            try:
                with open(self._path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                        plant_id,
                        plant_type,
                        int(area),
                        int(height),
                        int(width),
                        stage,
                        health,
                        gemini_analysis,
                    ])
            except Exception as e:
                log.error("[CSV] Lỗi ghi: %s", e)

    def log_plants_batch(self, plants: list[dict[str, Any]]) -> None:
        """Ghi nhiều cây cùng lúc."""
        if not self._initialized:
            return
        with self._lock:
            try:
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                with open(self._path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for p in plants:
                        writer.writerow([
                            now,
                            p.get("plant_id", 0),
                            p.get("plant_type", ""),
                            int(p.get("area", 0)),
                            int(p.get("height", 0)),
                            int(p.get("width", 0)),
                            p.get("stage", ""),
                            p.get("health", ""),
                            p.get("gemini", ""),
                        ])
            except Exception as e:
                log.error("[CSV] Lỗi ghi batch: %s", e)


class DetectionFrameSaver:
    """Lưu ảnh gốc và ảnh detection (có bounding box)."""

    def __init__(
        self,
        original_dir: str | Path | None = None,
        detected_dir: str | Path | None = None,
        max_files: int = 500,
    ) -> None:
        self._original_dir = Path(original_dir) if original_dir else _ORIGINAL_DIR
        self._detected_dir = Path(detected_dir) if detected_dir else _DETECTED_DIR
        self._max_files = max_files
        self._counter = 0
        self._lock = threading.Lock()

        self._original_dir.mkdir(parents=True, exist_ok=True)
        self._detected_dir.mkdir(parents=True, exist_ok=True)
        log.info("[SAVER] Dirs: original=%s, detected=%s",
                 self._original_dir, self._detected_dir)

    def save(
        self,
        original_frame: Any,
        detected_frame: Any | None = None,
        prefix: str = "frame",
    ) -> tuple[str, str]:
        """
        Lưu ảnh gốc và ảnh detect.

        Returns:
            (original_path, detected_path)
        """
        import cv2

        with self._lock:
            self._counter += 1
            idx = self._counter

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        name = f"{prefix}_{timestamp}_{idx:04d}.jpg"

        orig_path = str(self._original_dir / name)
        det_path = str(self._detected_dir / name)

        try:
            cv2.imwrite(orig_path, original_frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
        except Exception as e:
            log.error("[SAVER] Lỗi lưu ảnh gốc: %s", e)
            orig_path = ""

        if detected_frame is not None:
            try:
                cv2.imwrite(det_path, detected_frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 85])
            except Exception as e:
                log.error("[SAVER] Lỗi lưu ảnh detect: %s", e)
                det_path = ""
        else:
            det_path = ""

        # Cleanup cũ nếu quá nhiều
        self._cleanup_old_files()

        return orig_path, det_path

    def _cleanup_old_files(self) -> None:
        """Xóa file cũ nhất nếu quá max_files."""
        try:
            for d in [self._original_dir, self._detected_dir]:
                files = sorted(d.glob("*.jpg"), key=lambda f: f.stat().st_mtime)
                while len(files) > self._max_files:
                    files[0].unlink()
                    files.pop(0)
        except Exception:
            pass
