"""
Servo control via RPi.GPIO software PWM (fallback khi không có PCA9685).
Khuyến nghị dùng servo_pca9685.py cho độ chính xác cao hơn.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except Exception:
    _HAS_GPIO = False
    log.warning("RPi.GPIO không có sẵn → ServoController chạy simulation mode")

# BCM → BOARD pin mapping đầy đủ cho Raspberry Pi 40-pin header
BCM_TO_BOARD = {
    2: 3,   3: 5,   4: 7,   5: 29,  6: 31,  7: 26,  8: 24,  9: 21,
    10: 19, 11: 23, 12: 32, 13: 33, 14: 8,  15: 10, 16: 36, 17: 11,
    18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16, 24: 18, 25: 22,
    26: 37, 27: 13,
}

@dataclass
class ServoConfig:
    pan_pin: int = 17           # BCM
    tilt_pin: int = 27          # BCM
    freq_hz: int = 50
    min_angle: float = 0.0
    max_angle: float = 180.0
    min_duty: float = 2.5       # ~0°
    max_duty: float = 12.5      # ~180°
    initial_pan: float = 90.0
    initial_tilt: float = 90.0
    use_board_mode: bool = True  # True = BOARD mode (đồng bộ laser/motor)

class ServoController:
    """
    Software-PWM servo controller. Hỗ trợ cả BCM và BOARD numbering.
    LƯU Ý: cleanup() CHỈ xoá pin servo, không động đến pins khác.
    """

    def __init__(self, cfg: Optional[ServoConfig] = None):
        self.cfg = cfg or ServoConfig()
        self._pan_pwm = None
        self._tilt_pwm = None
        self._pan_angle = self.cfg.initial_pan
        self._tilt_angle = self.cfg.initial_tilt
        self._pan_pin_actual: int = self.cfg.pan_pin
        self._tilt_pin_actual: int = self.cfg.tilt_pin
        self._sim = not _HAS_GPIO
        self._initialized = False
        self._setup()

    # --------------------------------------------------------------
    def _bcm_to_actual(self, bcm_pin: int) -> int:
        """Convert BCM pin → BOARD nếu use_board_mode, raise nếu pin không hợp lệ."""
        if not self.cfg.use_board_mode:
            return bcm_pin
        if bcm_pin not in BCM_TO_BOARD:
            raise ValueError(
                f"BCM pin {bcm_pin} không có trong bảng map BOARD. "
                f"Pin hợp lệ: {sorted(BCM_TO_BOARD.keys())}"
            )
        return BCM_TO_BOARD[bcm_pin]

    def _setup(self) -> None:
        if self._sim:
            log.info("[SIM] ServoController init pan=%s tilt=%s",
                     self.cfg.pan_pin, self.cfg.tilt_pin)
            self._initialized = True
            return

        try:
            # Determine GPIO mode (tôn trọng mode đã set bởi module khác)
            current_mode = GPIO.getmode()
            if current_mode is None:
                if self.cfg.use_board_mode:
                    GPIO.setmode(GPIO.BOARD)
                else:
                    GPIO.setmode(GPIO.BCM)
            else:
                # Đã có mode → override use_board_mode theo mode hiện tại
                self.cfg.use_board_mode = (current_mode == GPIO.BOARD)
                log.debug("GPIO mode đã set sẵn: %s",
                          "BOARD" if self.cfg.use_board_mode else "BCM")

            GPIO.setwarnings(False)

            self._pan_pin_actual = self._bcm_to_actual(self.cfg.pan_pin)
            self._tilt_pin_actual = self._bcm_to_actual(self.cfg.tilt_pin)

            GPIO.setup(self._pan_pin_actual, GPIO.OUT)
            GPIO.setup(self._tilt_pin_actual, GPIO.OUT)

            self._pan_pwm = GPIO.PWM(self._pan_pin_actual, self.cfg.freq_hz)
            self._tilt_pwm = GPIO.PWM(self._tilt_pin_actual, self.cfg.freq_hz)
            self._pan_pwm.start(self._angle_to_duty(self._pan_angle))
            self._tilt_pwm.start(self._angle_to_duty(self._tilt_angle))
            self._initialized = True
            log.info(
                "ServoController init OK pan(BCM%s→pin%s) tilt(BCM%s→pin%s) freq=%dHz",
                self.cfg.pan_pin, self._pan_pin_actual,
                self.cfg.tilt_pin, self._tilt_pin_actual,
                self.cfg.freq_hz,
            )
        except Exception as e:
            log.error("ServoController init FAIL: %s → fallback SIM", e)
            self._sim = True
            self._initialized = True

    # --------------------------------------------------------------
    def _angle_to_duty(self, angle: float) -> float:
        a = max(self.cfg.min_angle, min(self.cfg.max_angle, angle))
        ratio = (a - self.cfg.min_angle) / (self.cfg.max_angle - self.cfg.min_angle)
        return self.cfg.min_duty + ratio * (self.cfg.max_duty - self.cfg.min_duty)

    def set_angle(self, pan: Optional[float] = None, tilt: Optional[float] = None,
                  settle_sec: float = 0.0) -> None:
        if pan is not None:
            self._pan_angle = max(self.cfg.min_angle, min(self.cfg.max_angle, pan))
            if not self._sim and self._pan_pwm is not None:
                try:
                    self._pan_pwm.ChangeDutyCycle(self._angle_to_duty(self._pan_angle))
                except Exception as e:
                    log.error("set pan FAIL: %s", e)
        if tilt is not None:
            self._tilt_angle = max(self.cfg.min_angle, min(self.cfg.max_angle, tilt))
            if not self._sim and self._tilt_pwm is not None:
                try:
                    self._tilt_pwm.ChangeDutyCycle(self._angle_to_duty(self._tilt_angle))
                except Exception as e:
                    log.error("set tilt FAIL: %s", e)
        if settle_sec > 0:
            time.sleep(settle_sec)

    def get_angles(self) -> tuple[float, float]:
        return self._pan_angle, self._tilt_angle

    def center(self, settle_sec: float = 0.3) -> None:
        self.set_angle(pan=90.0, tilt=90.0, settle_sec=settle_sec)

    def cleanup(self) -> None:
        """Stop PWM và CHỈ cleanup 2 pin servo (không động pin khác)."""
        if self._sim or not self._initialized:
            log.info("[SIM] ServoController cleanup")
            return
        try:
            if self._pan_pwm is not None:
                self._pan_pwm.stop()
            if self._tilt_pwm is not None:
                self._tilt_pwm.stop()
        except Exception as e:
            log.warning("PWM stop error: %s", e)
        try:
            # CHỈ cleanup 2 pin servo, KHÔNG GPIO.cleanup() toàn cục
            GPIO.cleanup([self._pan_pin_actual, self._tilt_pin_actual])
            log.info("ServoController cleanup OK (pins %s, %s)",
                     self._pan_pin_actual, self._tilt_pin_actual)
        except Exception as e:
            log.warning("GPIO cleanup servo pins error: %s", e)
        self._initialized = False
