"""
Gemini Vision Analysis — phân tích ảnh cây trồng bằng Google Gemini API.

Chức năng:
  - Gửi ảnh cây trồng → Gemini phân tích
  - Trả về: loại cây, giai đoạn, sức khỏe, nhận xét, khuyến nghị
  - Thread-safe, rate-limited, cached

Cấu hình:
  export GEMINI_API_KEY="your-key-here"

Sử dụng:
  from utils.gemini_vision import analyzer
  result = analyzer.analyze_plant("captures/plant_1_latest.jpg")
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("gemini_vision")

# Kết quả mặc định khi không phân tích được
_EMPTY_RESULT: dict[str, str] = {
    "plant_type": "",
    "growth_stage": "",
    "health_status": "",
    "observation": "",
    "recommendation": "",
}

# Prompt gửi cho Gemini (tiếng Việt)
_ANALYSIS_PROMPT = """Bạn là chuyên gia nông nghiệp AI. Hãy phân tích ảnh cây trồng này và trả về JSON (KHÔNG markdown, KHÔNG ```json, CHỈ JSON thuần):

{
  "plant_type": "Tên loại cây (ví dụ: Lettuce, Tomato, Cabbage, Onion, Unknown)",
  "growth_stage": "Giai đoạn phát triển (Seedling / Vegetative / Mature)",
  "health_status": "Tình trạng sức khỏe (Good / Fair / Poor)",
  "observation": "Nhận xét chi tiết về cây (tiếng Việt, 1-2 câu)",
  "recommendation": "Khuyến nghị chăm sóc (tiếng Việt, 1-2 câu)"
}

Phân tích dựa trên: kích thước lá, màu sắc, hình dáng, dấu hiệu sâu bệnh."""


class GeminiVisionAnalyzer:
    """Thread-safe Gemini Vision analyzer với rate limiting và caching."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash",
        rate_limit_sec: float = 5.0,
        cache_ttl_sec: float = 300.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model_name = model_name
        self._rate_limit_sec = rate_limit_sec
        self._cache_ttl_sec = cache_ttl_sec

        self._lock = threading.Lock()
        self._last_call_time = 0.0
        self._cache: dict[str, tuple[float, dict[str, str]]] = {}  # key → (timestamp, result)
        self._client = None
        self._available = False

        self._init_client()

    def _init_client(self) -> None:
        """Khởi tạo Gemini client. Không raise exception nếu thiếu key/module."""
        if not self._api_key:
            log.warning(
                "[GEMINI] Chưa có API key. "
                "Set biến môi trường: export GEMINI_API_KEY='your-key'"
            )
            return

        try:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
            self._available = True
            log.info("[GEMINI] Client khởi tạo OK (model: %s)", self._model_name)
        except ImportError:
            log.warning(
                "[GEMINI] Thư viện google-genai chưa cài. "
                "Chạy: pip install google-genai"
            )
        except Exception as e:
            log.error("[GEMINI] Lỗi khởi tạo client: %s", e)

    @property
    def is_available(self) -> bool:
        """Trả True nếu Gemini client sẵn sàng."""
        try:
            from utils.shared_state import state
            state_key = state.get_settings().get("gemini_api_key", "")
            if state_key and state_key != self._api_key:
                self._api_key = state_key
                self._init_client()
        except Exception:
            pass
        return self._available and self._client is not None

    def _read_image_bytes(self, image_path: str | Path) -> bytes | None:
        """Đọc ảnh từ file path."""
        path = Path(image_path)
        if not path.exists():
            log.warning("[GEMINI] File ảnh không tồn tại: %s", path)
            return None
        try:
            return path.read_bytes()
        except Exception as e:
            log.error("[GEMINI] Lỗi đọc ảnh %s: %s", path, e)
            return None

    def _parse_response(self, text: str) -> dict[str, str]:
        """Parse JSON response từ Gemini, xử lý trường hợp Gemini trả markdown."""
        # Loại bỏ markdown code block nếu có
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
            result = dict(_EMPTY_RESULT)
            for key in _EMPTY_RESULT:
                if key in data and isinstance(data[key], str):
                    result[key] = data[key]
            return result
        except json.JSONDecodeError as e:
            log.warning("[GEMINI] Không parse được JSON: %s — raw: %s", e, text[:200])
            return dict(_EMPTY_RESULT)

    def _rate_limit_wait(self) -> None:
        """Đợi nếu gọi quá nhanh."""
        with self._lock:
            elapsed = time.time() - self._last_call_time
            if elapsed < self._rate_limit_sec:
                wait = self._rate_limit_sec - elapsed
                time.sleep(wait)
            self._last_call_time = time.time()

    def _get_cached(self, cache_key: str) -> dict[str, str] | None:
        """Trả kết quả từ cache nếu còn hạn."""
        with self._lock:
            if cache_key in self._cache:
                ts, result = self._cache[cache_key]
                if time.time() - ts < self._cache_ttl_sec:
                    return result
                del self._cache[cache_key]
        return None

    def _set_cache(self, cache_key: str, result: dict[str, str]) -> None:
        """Lưu kết quả vào cache."""
        with self._lock:
            self._cache[cache_key] = (time.time(), result)
            # Giới hạn cache size
            if len(self._cache) > 100:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]

    def analyze_plant(
        self,
        image_path: str | Path | None = None,
        image_bytes: bytes | None = None,
        plant_id: int | None = None,
        force: bool = False,
    ) -> dict[str, str]:
        """
        Phân tích ảnh cây trồng bằng Gemini Vision.

        Args:
            image_path: Đường dẫn file ảnh.
            image_bytes: Bytes ảnh (thay thế image_path).
            plant_id: ID cây để cache.
            force: True = bỏ qua cache, gọi API mới.

        Returns:
            dict với keys: plant_type, growth_stage, health_status,
                           observation, recommendation.
            Trả dict rỗng nếu lỗi hoặc chưa có API key.
        """
        # Kiểm tra client
        if not self.is_available:
            log.warning("[GEMINI] Client chưa sẵn sàng (thiếu API key hoặc thư viện)")
            return dict(_EMPTY_RESULT)

        # Cache check
        cache_key = f"plant_{plant_id}" if plant_id else str(image_path)
        if not force:
            cached = self._get_cached(cache_key)
            if cached:
                log.info("[GEMINI] Cache hit cho %s", cache_key)
                return cached

        # Đọc ảnh
        if image_bytes is None and image_path is not None:
            image_bytes = self._read_image_bytes(image_path)
        if image_bytes is None:
            log.warning("[GEMINI] Không có dữ liệu ảnh để phân tích")
            return dict(_EMPTY_RESULT)

        # Rate limiting
        self._rate_limit_wait()

        # Gọi Gemini API
        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self._model_name,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(
                                data=image_bytes,
                                mime_type="image/jpeg",
                            ),
                            types.Part.from_text(text=_ANALYSIS_PROMPT),
                        ],
                    ),
                ],
            )

            if response and response.text:
                result = self._parse_response(response.text)
                self._set_cache(cache_key, result)
                log.info(
                    "[GEMINI] Phân tích OK: plant_id=%s type=%s stage=%s",
                    plant_id, result.get("plant_type"), result.get("growth_stage"),
                )
                return result
            else:
                log.warning("[GEMINI] Response rỗng từ API")
                return dict(_EMPTY_RESULT)

        except Exception as e:
            log.error("[GEMINI] Lỗi gọi API: %s", e)
            return dict(_EMPTY_RESULT)

    def clear_cache(self) -> None:
        """Xóa toàn bộ cache."""
        with self._lock:
            self._cache.clear()


# Singleton instance — import và sử dụng trực tiếp
analyzer = GeminiVisionAnalyzer()
