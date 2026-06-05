from __future__ import annotations

"""
Pi-only realtime weed detection:
Camera -> YOLO -> error_x/error_y -> servo + laser + motor.

Features:
  - State machine: FORWARD -> STOPPED -> TRACKING -> FIRING -> COOLDOWN
  - Laser pulse mode (on -> sleep -> off, safety capped)
  - Failsafe try/except/finally with laser OFF first
  - Watchdog timeout, max shots per weed
  - Servo recenter with actual set_angle()
  - Web Dashboard (Flask) + Crop tracking
  - Motor command tracking (no spam)
"""

import argparse
import logging
import signal
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
from ultralytics import YOLO

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None  # type: ignore

from hardware.laser_control import LaserController
from hardware.motor_l298n import MotorL298N
from hardware.servo_pca9685 import ServoControllerPCA9685, ServoKitConfig
from hardware.wiring import WIRING
from utils.coordinate_convert import CameraConfig, SERVO_ANGLE_MIN, SERVO_ANGLE_MAX
from utils.shared_state import (
    PlantInfo, classify_health, classify_stage, generate_description, state,
)


def setup_logging(log_file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("weed_system")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def load_model(model_path: str | Path = "models/best.pt") -> YOLO:
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path.resolve()}")
    return YOLO(str(path))


class MotorCommander:
    """Wrapper cho MotorL298N để tránh gọi GPIO write mỗi frame.
    Chỉ gọi forward()/stop() khi command thay đổi."""

    def __init__(self, motor: MotorL298N, log: logging.Logger) -> None:
        self.motor = motor
        self.log = log
        self._cmd: Optional[str] = None

    def forward(self) -> None:
        if self._cmd != "forward":
            self.motor.forward()
            self._cmd = "forward"
            self.log.debug("Motor: forward")

    def stop(self) -> None:
        if self._cmd != "stop":
            self.motor.stop()
            self._cmd = "stop"
            self.log.debug("Motor: stop")


def _update_plant_tracker(
    detections: list, plant_tracker: dict, plant_counter: int,
    frame, w: int, h: int, now: float,
) -> int:
    """Track crop plants for web dashboard. Returns updated plant_counter."""
    current_crops = []
    for cls_id, _score, x1, y1, x2, y2 in detections:
        if cls_id == 0:
            current_crops.append({
                "cx": (x1 + x2) / 2.0, "cy": (y1 + y2) / 2.0,
                "area": (x2 - x1) * (y2 - y1),
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            })

    matched_ids: set[int] = set()
    for crop in current_crops:
        best_id = None
        best_dist = 100.0
        for pid, pinfo in plant_tracker.items():
            if pid in matched_ids:
                continue
            dist = ((crop["cx"] - pinfo["cx"]) ** 2 +
                    (crop["cy"] - pinfo["cy"]) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_id = pid
        if best_id is not None:
            matched_ids.add(best_id)
            plant_tracker[best_id].update({
                "cx": crop["cx"], "cy": crop["cy"], "area": crop["area"],
                "x1": crop["x1"], "y1": crop["y1"],
                "x2": crop["x2"], "y2": crop["y2"],
                "last_seen": now,
            })
        else:
            plant_counter += 1
            pid = plant_counter
            plant_tracker[pid] = {
                "cx": crop["cx"], "cy": crop["cy"], "area": crop["area"],
                "x1": crop["x1"], "y1": crop["y1"],
                "x2": crop["x2"], "y2": crop["y2"],
                "first_seen": now, "last_seen": now,
                "image_captured": False,
            }

    stale = [pid for pid, p in plant_tracker.items() if now - p["last_seen"] > 5.0]
    for pid in stale:
        del plant_tracker[pid]

    for pid, pinfo in plant_tracker.items():
        if now - pinfo.get("_last_state_update", 0) < 1.0:
            continue
        pinfo["_last_state_update"] = now
        area = pinfo["area"]
        h_px = pinfo["y2"] - pinfo["y1"]
        w_px = pinfo["x2"] - pinfo["x1"]
        stage = classify_stage(area)
        prev_area = state.get_previous_area(pid)
        health = classify_health(area, prev_area)
        desc = generate_description("Crop", pid, stage, area, health, prev_area)
        image_path = ""
        if not pinfo.get("image_captured"):
            x1i, y1i = max(0, int(pinfo["x1"])), max(0, int(pinfo["y1"]))
            x2i, y2i = min(w, int(pinfo["x2"])), min(h, int(pinfo["y2"]))
            if x2i > x1i and y2i > y1i:
                crop_img = frame[y1i:y2i, x1i:x2i]
                image_path = state.save_plant_image(pid, crop_img)
            pinfo["image_captured"] = True
        state.upsert_plant(PlantInfo(
            plant_id=pid, plant_type="Crop",
            area_px=area, height_px=h_px, width_px=w_px,
            stage=stage, health=health, last_seen=now,
            image_path=image_path, description=desc,
        ))
        state.add_growth_record(pid, area, stage)
    return plant_counter


def run_system(
    model_path: str | Path = "models/best.pt",
    camera_index: int = 0,
    conf: float = 0.2,
    target_class_id: int = 1,
    target_fps: float = 10.0,
    show_window: bool = False,
    imgsz: int = 320,
    use_picam2: bool = False,
    pan_gain: float = 0.06,
    tilt_gain: float = 0.06,
    laser_deadband_x: float = 25.0,
    laser_deadband_y: float = 25.0,
    stable_frames_required: int = 3,
    offset_pan: float = 0.0,
    offset_tilt: float = 0.0,
    enable_web: bool = False,
    web_port: int = 5000,
    laser_pulse_ms: int = 50,
    max_shots_per_weed: int = 3,
    state_timeout_sec: float = 30.0,
    cooldown_sec: float = 0.5,
    settle_sec: float = 0.3,
    resume_delay_sec: float = 1.5,
    log_file: str | None = "logs/weed_system.log",
    dry_run: bool = False,
) -> None:
    log = setup_logging(log_file)
    log.info("=" * 60)
    log.info("Weed Detection System starting...")
    log.info(f"Model: {model_path} | fps: {target_fps} | pulse: {laser_pulse_ms}ms")
    if dry_run:
        log.info("🔍 DRY-RUN MODE: laser sẽ KHÔNG bắn thật, chỉ vẽ aim point")

    model = load_model(model_path)

    # Camera
    try:
        from utils.camera_pi import open_camera
        log.info(f"Opening camera (picam2={use_picam2}, index={camera_index}) ...")
        cap = open_camera(camera_index=camera_index, use_picam2=use_picam2)
    except Exception:
        log.info(f"Opening camera index {camera_index} (OpenCV) ...")
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {camera_index}")

    # GPIO
    if GPIO is not None and GPIO.getmode() is None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)

    servo = ServoControllerPCA9685(ServoKitConfig())
    laser = LaserController()
    motor_raw = MotorL298N()
    motor = MotorCommander(motor_raw, log)   # ← wrapper chống spam

    # Signal handlers — laser OFF khi SIGTERM/SIGINT

    def _safe_exit(signum, _frame):
        log.warning(f"Signal {signum} → safe shutdown")
        try:
            laser.off()
        except Exception:
            pass
        try:
            motor_raw.stop()
        except Exception:
            pass
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _safe_exit)
    signal.signal(signal.SIGINT, _safe_exit)

    pan_angle = 90.0
    tilt_angle = 90.0
    servo.set_angle(pan=pan_angle, tilt=tilt_angle)
    motor.forward()

    log.info(f"Offset: pan={offset_pan} tilt={offset_tilt} "
             f"| Servo: {SERVO_ANGLE_MIN}-{SERVO_ANGLE_MAX}")

    # Web dashboard
    if enable_web:
        try:
            from webapp.app import start_web
            threading.Thread(
                target=start_web, kwargs={"port": web_port, "debug": False},
                daemon=True,
            ).start()
            log.info(f"Web Dashboard on port {web_port}")
        except Exception as e:
            log.error(f"Web dashboard failed: {e}")

    delay_sec = 1.0 / max(target_fps, 1.0)
    delay_ms = int(1000 * delay_sec)

    sm_state = "FORWARD"
    prev_state = sm_state
    state_entered_at = time.time()
    stable_hits = 0
    last_detection_time = 0.0
    cooldown_until = 0.0
    settle_until = 0.0
    shots_for_current_weed = 0
    last_servo_reset = 0.0

    laser_fired_count = 0
    weed_detected_total = 0
    frame_count = 0
    fps_update_time = time.time()
    current_fps = 0.0
    plant_counter = 0
    plant_tracker: dict[int, dict] = {}

    log.info("System ready. Press ESC to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                log.warning("Failed to read frame, retrying...")
                time.sleep(0.1)
                continue

            h, w = frame.shape[:2]
            center_x = w / 2.0
            center_y = h / 2.0

            results_list = model.predict(source=frame, conf=conf,
                                         verbose=False, imgsz=imgsz)

            detections = []
            if results_list:
                boxes = results_list[0].boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        score = float(box.conf[0].item())
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        detections.append((cls_id, score, x1, y1, x2, y2))

            weed_det = None
            best_weed_dist = float("inf")
            crop_count = 0

            for cls_id, score, x1, y1, x2, y2 in detections:
                if cls_id == 0:
                    crop_count += 1
                    if show_window:
                        cv2.rectangle(frame, (int(x1), int(y1)),
                                      (int(x2), int(y2)), (255, 180, 0), 2)
                        cv2.putText(frame, f"crop {score:.2f}",
                                    (int(x1), max(20, int(y1) - 10)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (255, 180, 0), 1)
                elif cls_id == target_class_id:
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    dist = (cx - center_x) ** 2 + (cy - center_y) ** 2
                    if dist < best_weed_dist:
                        best_weed_dist = dist
                        weed_det = (x1, y1, x2, y2, score)

            now = time.time()

            # State tracking
            if sm_state != prev_state:
                log.info(f"STATE: {prev_state} -> {sm_state}")
                prev_state = sm_state
                state_entered_at = now

            # Watchdog
            if sm_state != "FORWARD" and now - state_entered_at > state_timeout_sec:
                log.warning(f"State {sm_state} stuck {state_timeout_sec:.0f}s, "
                            f"force FORWARD")
                laser.off()
                motor.forward()
                sm_state = "FORWARD"
                stable_hits = 0
                shots_for_current_weed = 0

            # FPS
            frame_count += 1
            if now - fps_update_time >= 1.0:
                current_fps = frame_count / (now - fps_update_time)
                frame_count = 0
                fps_update_time = now

            # Web dashboard update
            if enable_web:
                plant_counter = _update_plant_tracker(
                    detections, plant_tracker, plant_counter, frame, w, h, now,
                )
                state.update_stats(
                    weed_detected=weed_detected_total,
                    crop_detected=len(plant_tracker),
                    laser_fired=laser_fired_count,
                    system_status="RUNNING",
                    state=sm_state,
                    fps=current_fps,
                )
                web_frame = frame.copy()
                if weed_det is not None:
                    x1, y1, x2, y2, _ = weed_det
                    cv2.rectangle(web_frame, (int(x1), int(y1)),
                                  (int(x2), int(y2)), (0, 255, 0), 2)
                cv2.putText(web_frame, f"{sm_state}", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                state.update_frame(web_frame)

            # ========== STATE MACHINE ==========
            if sm_state == "FORWARD":
                motor.forward()                # ← no-op nếu đã forward
                if weed_det is not None:
                    motor.stop()
                    last_detection_time = now
                    weed_detected_total += 1
                    shots_for_current_weed = 0
                    sm_state = "STOPPED"

            elif sm_state == "STOPPED":
                motor.stop()                   # ← no-op nếu đã stop
                if weed_det is not None:
                    last_detection_time = now
                    stable_hits = 0
                    settle_until = now + settle_sec
                    sm_state = "TRACKING"
                elif now - last_detection_time > resume_delay_sec:
                    sm_state = "FORWARD"

            elif sm_state == "TRACKING":
                motor.stop()
                if weed_det is not None:
                    last_detection_time = now
                    x1, y1, x2, y2, weed_conf = weed_det
                    weed_x = (x1 + x2) / 2.0
                    weed_y = (y1 + y2) / 2.0
                    error_x = weed_x - center_x
                    error_y = weed_y - center_y

                    new_pan = max(SERVO_ANGLE_MIN, min(SERVO_ANGLE_MAX,
                        pan_angle + error_x * pan_gain + offset_pan))
                    new_tilt = max(SERVO_ANGLE_MIN, min(SERVO_ANGLE_MAX,
                        tilt_angle + error_y * tilt_gain + offset_tilt))

                    angle_change = abs(new_pan - pan_angle) + abs(new_tilt - tilt_angle)
                    if angle_change > 5.0:
                        settle_until = max(settle_until,
                                           now + 0.1 + angle_change * 0.005)

                    pan_angle, tilt_angle = new_pan, new_tilt
                    servo.set_angle(pan=pan_angle, tilt=tilt_angle)

                    aligned = (abs(error_x) < laser_deadband_x and
                               abs(error_y) < laser_deadband_y)
                    stable_hits = stable_hits + 1 if aligned else 0

                    if stable_hits >= stable_frames_required and now >= settle_until:
                        sm_state = "FIRING"

                    if show_window:
                        cv2.rectangle(frame, (int(x1), int(y1)),
                                      (int(x2), int(y2)), (0, 255, 0), 2)
                        cv2.circle(frame, (int(weed_x), int(weed_y)), 4,
                                   (0, 0, 255), -1)
                        cv2.circle(frame, (int(center_x), int(center_y)), 4,
                                   (255, 0, 0), -1)
                        cv2.putText(frame,
                            f"weed {weed_conf:.2f} ex={error_x:.0f} "
                            f"ey={error_y:.0f} s={stable_hits}",
                            (int(x1), max(20, int(y1) - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                else:
                    stable_hits = 0
                    if now - last_detection_time > resume_delay_sec:
                        shots_for_current_weed = 0
                        sm_state = "FORWARD"

            elif sm_state == "FIRING":
                motor.stop()
                if dry_run:
                    # Dry-run: vẽ aim point + log, không bắn thật
                    log.info(
                        f"🔍 DRY-RUN: lẽ ra bắn tại "
                        f"pan={pan_angle:.1f}° tilt={tilt_angle:.1f}° "
                        f"(phát #{shots_for_current_weed + 1})"
                    )
                else:
                    laser.on()
                    time.sleep(laser_pulse_ms / 1000.0)
                    laser.off()
                laser_fired_count += 1
                shots_for_current_weed += 1
                if not dry_run:
                    log.info(f"🎯 BẮN THÀNH CÔNG cỏ dại — pulse {laser_pulse_ms}ms "
                             f"(phát #{shots_for_current_weed}, tổng {laser_fired_count})")
                cooldown_until = now + cooldown_sec
                last_detection_time = now
                stable_hits = 0
                sm_state = "COOLDOWN"

            elif sm_state == "COOLDOWN":
                motor.stop()
                laser.off()
                if weed_det is not None:
                    last_detection_time = now
                if now >= cooldown_until:
                    if shots_for_current_weed >= max_shots_per_weed:
                        log.info(f"Max shots ({max_shots_per_weed}) reached")
                        shots_for_current_weed = 0
                        sm_state = "FORWARD"
                    elif weed_det is not None:
                        stable_hits = 0
                        settle_until = now + settle_sec
                        sm_state = "TRACKING"
                    else:
                        shots_for_current_weed = 0
                        sm_state = "FORWARD"

            # Servo recenter
            if (sm_state == "FORWARD" and weed_det is None
                    and now - last_detection_time > 2.0
                    and now - last_servo_reset > 5.0):
                if abs(pan_angle - 90.0) > 5.0 or abs(tilt_angle - 90.0) > 5.0:
                    pan_angle, tilt_angle = 90.0, 90.0
                    servo.set_angle(pan=pan_angle, tilt=tilt_angle)
                    last_servo_reset = now

            # Display
            if show_window:
                cv2.putText(frame,
                    f"state={sm_state} fps={current_fps:.1f} "
                    f"shots={shots_for_current_weed}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
                cv2.putText(frame, f"pan={pan_angle:.0f} tilt={tilt_angle:.0f}",
                            (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (200, 200, 200), 1)
                cv2.imshow("Weed Detection System", frame)
                key = cv2.waitKey(delay_ms) & 0xFF
                if key == 27:
                    log.info("ESC pressed, exiting...")
                    break
                elif key == ord("r"):
                    pan_angle, tilt_angle = 90.0, 90.0
                    servo.set_angle(pan=pan_angle, tilt=tilt_angle)
            else:
                time.sleep(delay_sec)

    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received")
    except Exception as e:
        log.error(f"Loop error: {e}", exc_info=True)

    finally:
        log.info("Shutting down...")
        try:
            laser.off()
            log.info("Laser OFF")
        except Exception:
            pass
        try:
            motor.stop()
        except Exception:
            pass
        try:
            cap.release()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        try:
            motor_raw.cleanup()
        except Exception:
            pass
        try:
            servo.cleanup()
        except Exception:
            pass
        try:
            laser.cleanup()
        except Exception:
            pass
        # KHÔNG gọi GPIO.cleanup() toàn cục - mỗi module đã tự cleanup pin riêng
        log.info("Shutdown complete")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pi weed detection system")
    p.add_argument("--model", default="models/best.pt")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--conf", type=float, default=0.2)
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--imgsz", type=int, default=320)
    p.add_argument("--show", action="store_true")
    p.add_argument("--picam2", action="store_true")
    p.add_argument("--class-id", type=int, default=1, dest="target_class_id")
    p.add_argument("--pan-gain", type=float, default=0.06)
    p.add_argument("--tilt-gain", type=float, default=0.06)
    p.add_argument("--laser-deadband-x", type=float, default=25.0)
    p.add_argument("--laser-deadband-y", type=float, default=25.0)
    p.add_argument("--stable-frames", type=int, default=3)
    p.add_argument("--offset-pan", type=float, default=0.0)
    p.add_argument("--offset-tilt", type=float, default=0.0)
    p.add_argument("--web", action="store_true")
    p.add_argument("--web-port", type=int, default=5000)
    p.add_argument("--laser-pulse-ms", type=int, default=50)
    p.add_argument("--max-shots", type=int, default=3)
    p.add_argument("--state-timeout-sec", type=float, default=30.0)
    p.add_argument("--cooldown-sec", type=float, default=0.5)
    p.add_argument("--settle-sec", type=float, default=0.3)
    p.add_argument("--resume-delay-sec", type=float, default=1.5)
    p.add_argument("--log-file", default="logs/weed_system.log")
    p.add_argument("--dry-run", action="store_true",
                   help="Kiểm tra aim: vẽ aim point, KHÔNG bắn laser thật")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_system(
        model_path=args.model,
        camera_index=args.camera,
        conf=args.conf,
        target_class_id=args.target_class_id,
        target_fps=args.fps,
        show_window=args.show,
        imgsz=args.imgsz,
        use_picam2=args.picam2,
        pan_gain=args.pan_gain,
        tilt_gain=args.tilt_gain,
        laser_deadband_x=args.laser_deadband_x,
        laser_deadband_y=args.laser_deadband_y,
        stable_frames_required=args.stable_frames,
        offset_pan=args.offset_pan,
        offset_tilt=args.offset_tilt,
        enable_web=args.web,
        web_port=args.web_port,
        laser_pulse_ms=args.laser_pulse_ms,
        max_shots_per_weed=args.max_shots,
        state_timeout_sec=args.state_timeout_sec,
        cooldown_sec=args.cooldown_sec,
        settle_sec=args.settle_sec,
        resume_delay_sec=args.resume_delay_sec,
        log_file=args.log_file or None,
        dry_run=args.dry_run,
    )
