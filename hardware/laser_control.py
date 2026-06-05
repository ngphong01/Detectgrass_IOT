from __future__ import annotations

import threading
import time

from hardware.wiring import WIRING

try:
    import RPi.GPIO as GPIO
except ImportError:  # Running on PC
    GPIO = None  # type: ignore


class LaserController:
    def __init__(self, pin: int = WIRING.laser_pin, active_high: bool = True, simulate_if_no_gpio: bool = True) -> None:
        self.pin = pin
        self.active_high = active_high
        self.simulate = GPIO is None and simulate_if_no_gpio
        self._io_lock = threading.Lock()
        self._pulse_thread: threading.Thread | None = None
        self._pulse_start_lock = threading.Lock()

        if self.simulate:
            print("[LASER] Running in simulation mode (no RPi.GPIO).")
            return

        GPIO.setwarnings(False)
        current_mode = GPIO.getmode()
        if current_mode is None:
            GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.pin, GPIO.OUT)
        self.off()

    def _gpio_on(self) -> None:
        if self.simulate:
            print("[LASER] ON")
            return
        GPIO.output(self.pin, GPIO.HIGH if self.active_high else GPIO.LOW)

    def _gpio_off(self) -> None:
        if self.simulate:
            print("[LASER] OFF")
            return
        GPIO.output(self.pin, GPIO.LOW if self.active_high else GPIO.HIGH)

    def on(self) -> None:
        with self._io_lock:
            self._gpio_on()

    def off(self) -> None:
        with self._io_lock:
            self._gpio_off()

    def pulse(self, duration_sec: float = 0.3) -> None:
        """Fire laser pulse (blocking). Safety capped, always off in finally."""
        duration_sec = max(0.01, min(duration_sec, 1.0))
        try:
            self.on()
            time.sleep(duration_sec)
        finally:
            self.off()

    def pulse_async(self, duration_sec: float = 0.3) -> bool:
        """
        Pulse in a background thread so the main loop is not blocked.
        Returns False if a previous async pulse thread is still running.
        """
        def worker() -> None:
            try:
                self.on()
                time.sleep(duration_sec)
            finally:
                self.off()

        with self._pulse_start_lock:
            if self._pulse_thread is not None and self._pulse_thread.is_alive():
                return False
            t = threading.Thread(target=worker, daemon=True, name="laser-pulse")
            self._pulse_thread = t
            t.start()
            return True

    def cleanup(self) -> None:
        # CRITICAL: off FIRST before waiting for pulse thread
        try:
            self.off()
        except Exception:
            pass

        t = self._pulse_thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

        if self.simulate:
            return
        try:
            GPIO.cleanup(self.pin)
        except Exception:
            pass


if __name__ == "__main__":
    laser = LaserController()
    try:
        laser.on()
        input("Laser ON. Press Enter to turn OFF...")
    finally:
        laser.off()
        laser.cleanup()

