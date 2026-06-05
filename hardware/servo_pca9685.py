"""
Điều khiển servo pan/tilt qua PCA9685 (Adafruit ServoKit).

PWM servo chuẩn: 50 Hz (ServoKit/PCA9685 mặc định 50 Hz).
Cài đặt trên Raspberry Pi:
  pip install adafruit-circuitpython-servokit

Kết nối: PCA9685 nối I2C với Pi (SDA, SCL, VCC, GND).
Servo pan → channel 14, Servo tilt → channel 15.

Giới hạn góc mặc định: 20–160° để tránh rung ở 0°/180°
(đồng bộ với SERVO_ANGLE_MIN/MAX trong utils/coordinate_convert.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from hardware.wiring import WIRING

try:
    from adafruit_servokit import ServoKit
    _SERVOKIT = ServoKit
except ImportError:
    _SERVOKIT = None  # type: ignore

@dataclass
class ServoKitConfig:
    """Channel PCA9685: values are sourced from `hardware.wiring`."""
    pan_channel: int = WIRING.servo_pan_channel
    tilt_channel: int = WIRING.servo_tilt_channel
    # Đồng bộ với SERVO_ANGLE_MIN/MAX (20-160) tránh rung tại 0°/180°
    min_angle: float = 20.0
    max_angle: float = 160.0

class ServoControllerPCA9685:
    """Servo qua PCA9685, giao diện giống ServoController (set_angle, cleanup)."""

    def __init__(self, cfg: ServoKitConfig | None = None,
                 simulate_if_no_kit: bool = True) -> None:
        self.cfg = cfg or ServoKitConfig()
        self.simulate = _SERVOKIT is None and simulate_if_no_kit
        self._kit = None

        if self.simulate:
            print("[SERVO PCA9685] Running in simulation mode (no adafruit_servokit).")
            return

        self._kit = _SERVOKIT(channels=16)
        # Initial center position (90° luôn nằm trong 20-160)
        self._kit.servo[self.cfg.pan_channel].angle = 90
        self._kit.servo[self.cfg.tilt_channel].angle = 90

    def _clamp(self, angle: float) -> float:
        return max(self.cfg.min_angle, min(self.cfg.max_angle, angle))

    def set_angle(self, pan: float | None = None,
                  tilt: float | None = None) -> None:
        if self.simulate:
            pan_c = self._clamp(pan) if pan is not None else None
            tilt_c = self._clamp(tilt) if tilt is not None else None
            print(f"[SERVO PCA9685] Sim pan={pan_c}, tilt={tilt_c}")
            return

        if pan is not None:
            self._kit.servo[self.cfg.pan_channel].angle = self._clamp(pan)
        if tilt is not None:
            self._kit.servo[self.cfg.tilt_channel].angle = self._clamp(tilt)
        time.sleep(0.02)

    def cleanup(self) -> None:
        if self.simulate:
            return
        try:
            # Set angle = None → release PWM (servo không giữ torque)
            self._kit.servo[self.cfg.pan_channel].angle = None
            self._kit.servo[self.cfg.tilt_channel].angle = None
        except Exception:
            pass

if __name__ == "__main__":
    ctrl = ServoControllerPCA9685()
    try:
        for a in range(60, 121, 10):
            ctrl.set_angle(pan=a, tilt=a)
            time.sleep(0.2)
    finally:
        ctrl.cleanup()
