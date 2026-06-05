"""
Realtime weed detection + laser firing (Pi).
Fixes:
1. Hard cap laser pulse + safety _fire_laser()
2. Signal handlers (SIGTERM/SIGINT) đảm bảo laser off
3. Multi-target re-verify trước khi FIRE
4. finally explicit laser.off() trước cleanup
5. Class-id default = 1 (weed) khớp main.py
6. FIX: API wiring/motor/servo đúng với module hiện tại
7. FIX: sm_cooldown_until được set sau khi FIRE
"""
from __future__ import annotations
import argparse
import logging
import signal
import sys
import time
from collections import deque
from typing import Optional, List, Dict, Any

import cv2

# Hardware modules (auto-sim trên non-Pi)
from hardware.laser_control import LaserController
from hardware.motor_l298n import MotorL298N, MotorConfig
from hardware.servo_pca9685 import ServoControllerPCA9685, ServoKitConfig
from hardware.wiring import WIRING

# Constants
LASER_MAX_PULSE_SEC = 1.0   # HARD CAP: không bao giờ pulse quá 1s
LASER_DEFAULT_PULSE = 0.2

log = logging.getLogger("weed_laser")

# Global refs cho signal handler
_LASER_REF: Optional[LaserController] = None
_MOTOR_REF: Optional[MotorL298N] = None

# ---------------------------------------------------------------- safety
def _safe_exit(signum, frame):
    """Tắt laser + motor NGAY khi nhận SIGTERM/SIGINT."""
    log.warning("Signal %s received → safe shutdown", signum)
    try:
        if _LASER_REF is not None:
            _LASER_REF.off()
    except Exception:
        pass
    try:
        if _MOTOR_REF is not None:
            _MOTOR_REF.stop()
    except Exception:
        pass
    raise KeyboardInterrupt

def _fire_laser(laser: LaserController, pulse_sec: float, debug: bool = False) -> None:
    """Bắn laser với hard cap + try/finally đảm bảo off()."""
    safe_sec = max(0.02, min(pulse_sec if pulse_sec > 0 else LASER_DEFAULT_PULSE,
                              LASER_MAX_PULSE_SEC))
    if pulse_sec > LASER_MAX_PULSE_SEC:
        log.warning("Laser pulse %.2fs > cap %.2fs → clamp",
                    pulse_sec, LASER_MAX_PULSE_SEC)
    if debug:
        log.info("[LASER] ON %dms", int(safe_sec * 1000))
    try:
        if hasattr(laser, "pulse"):
            laser.pulse(safe_sec)
        else:
            laser.on()
            time.sleep(safe_sec)
            laser.off()
    except Exception as e:
        log.error("Laser fire error: %s", e)
    finally:
        try:
            laser.off()
        except Exception:
            pass
        if debug:
            log.info("[LASER] OFF")

# ---------------------------------------------------------------- detection
def _parse_detections(results, target_class_id: int, frame_w: int, frame_h: int,
                      min_area_norm: float, max_area_norm: float,
                      roi_top: float, roi_bottom: float) -> List[Dict[str, Any]]:
    dets: List[Dict[str, Any]] = []
    if results is None or len(results) == 0:
        return dets
    r = results[0]
    if r.boxes is None or len(r.boxes) == 0:
        return dets
    xyxy = r.boxes.xyxy.cpu().numpy()
    conf = r.boxes.conf.cpu().numpy()
    cls = r.boxes.cls.cpu().numpy().astype(int)
    for i, c in enumerate(cls):
        if c != target_class_id:
            continue
        x1, y1, x2, y2 = xyxy[i]
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        bw = max(1.0, x2 - x1)
        bh = max(1.0, y2 - y1)
        area_norm = (bw * bh) / (frame_w * frame_h)
        cy_norm = cy / frame_h
        if not (min_area_norm <= area_norm <= max_area_norm):
            continue
        if not (roi_top <= cy_norm <= roi_bottom):
            continue
        dets.append({
            "cx": cx, "cy": cy, "w": bw, "h": bh,
            "cx_norm": cx / frame_w,
            "cy_norm": cy_norm,
            "area_norm": area_norm,
            "conf": float(conf[i]),
        })
    return dets

def _sort_targets(dets: List[Dict[str, Any]], aim: str) -> List[Dict[str, Any]]:
    if aim == "left":
        return sorted(dets, key=lambda d: d["cx_norm"])
    if aim == "right":
        return sorted(dets, key=lambda d: -d["cx_norm"])
    # center: gần tâm trước
    return sorted(dets, key=lambda d: abs(d["cx_norm"] - 0.5) + abs(d["cy_norm"] - 0.5))

# ---------------------------------------------------------------- main
def run_system(args) -> int:
    global _LASER_REF, _MOTOR_REF

    # YOLO
    from ultralytics import YOLO
    log.info("Loading model: %s", args.model)
    model = YOLO(args.model)

    # Camera
    if args.picam2:
        from utils.camera_pi import open_camera as open_pi_camera
        cap = open_pi_camera(width=args.width, height=args.height)
    else:
        cap = cv2.VideoCapture(args.camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if cap is None or (hasattr(cap, "isOpened") and not cap.isOpened()):
        log.error("Camera open FAIL")
        return 2

    # Hardware — dùng WIRING instance
    laser = LaserController(pin=WIRING.laser_pin)
    motor = None
    if not args.no_motor:
        motor = MotorL298N(MotorConfig(
            in3=WIRING.motor_in3_pin,
            in4=WIRING.motor_in4_pin,
        ))
    servo = None
    if args.pca9685:
        servo = ServoControllerPCA9685(ServoKitConfig(
            pan_channel=WIRING.servo_pan_channel,
            tilt_channel=WIRING.servo_tilt_channel,
        ))
        servo.set_angle(pan=90.0, tilt=90.0)

    _LASER_REF = laser
    _MOTOR_REF = motor

    # Signal handlers (đặt SAU khi laser/motor đã init)
    signal.signal(signal.SIGTERM, _safe_exit)
    signal.signal(signal.SIGINT, _safe_exit)

    # State machine vars
    sm_state = "SCAN"
    sm_target: Optional[Dict[str, Any]] = None
    sm_queue: deque = deque()
    sm_settle_until = 0.0
    sm_cooldown_until = 0.0
    last_fire_ts = 0.0
    pan_angle = tilt_angle = 90.0
    vote_hits: deque = deque(maxlen=args.vote_window)
    shot_targets: List[tuple] = []
    SHOT_TOL = 0.06

    # Motor command tracking để tránh spam GPIO
    _motor_cmd: Optional[str] = None

    def _motor_set(cmd: str) -> None:
        nonlocal _motor_cmd
        if motor is None or _motor_cmd == cmd:
            return
        if cmd == "forward":
            motor.forward()
        elif cmd == "stop":
            motor.stop()
        _motor_cmd = cmd

    frame_id = 0
    delay = 1.0 / max(1.0, args.fps)

    try:
        while True:
            now_ts = time.monotonic()
            ok, frame = (cap.read() if hasattr(cap, "read") else (True, cap.capture()))
            if not ok or frame is None:
                log.warning("Frame grab fail")
                time.sleep(0.05)
                continue
            frame_id += 1
            h, w = frame.shape[:2]

            # Frame-skip: vẫn chạy SM cooldown nhưng skip inference
            run_inference = (frame_id % max(1, args.frame_skip) == 0)
            if run_inference:
                results = model.predict(
                    frame, imgsz=args.imgsz, conf=args.conf, verbose=False
                )
                dets = _parse_detections(
                    results, args.class_id, w, h,
                    args.min_area, args.max_area,
                    args.roi_top, args.roi_bottom,
                )
            else:
                dets = []

            # Lọc target đã bắn
            def _is_shot(d):
                return any(
                    abs(d["cx_norm"] - sx) < SHOT_TOL and
                    abs(d["cy_norm"] - sy) < SHOT_TOL
                    for sx, sy in shot_targets
                )

            unshot = [d for d in dets if not _is_shot(d)]

            # Vote filtering
            vote_hits.append(1 if len(unshot) > 0 else 0)
            vote_ready = (len(vote_hits) >= args.min_hits
                          and sum(vote_hits) >= args.min_hits)

            # -------------------- STATE MACHINE
            if sm_state == "SCAN":
                _motor_set("forward")
                if vote_ready and unshot and run_inference:
                    sm_queue = deque(_sort_targets(unshot, args.aim)[:args.max_targets])
                    _motor_set("stop")
                    sm_state = "AIM"
                    if args.state_debug_log:
                        log.info("[SM] SCAN→AIM (%d targets)", len(sm_queue))

            elif sm_state == "AIM":
                _motor_set("stop")
                if not sm_queue:
                    sm_state = "SCAN"
                else:
                    sm_target = sm_queue.popleft()
                    err_x = sm_target["cx_norm"] - 0.5
                    err_y = sm_target["cy_norm"] - 0.5
                    pan_angle = max(20.0, min(160.0,
                        90.0 - err_x * args.pan_gain * 180.0 + args.offset_pan))
                    tilt_angle = max(20.0, min(160.0,
                        90.0 + err_y * args.tilt_gain * 180.0 + args.offset_tilt))
                    if servo is not None:
                        servo.set_angle(pan=pan_angle, tilt=tilt_angle)
                    sm_settle_until = now_ts + args.settle
                    sm_state = "SETTLE"
                    if args.state_debug_log:
                        log.info("[SM] AIM→SETTLE pan=%.1f tilt=%.1f",
                                 pan_angle, tilt_angle)

            elif sm_state == "SETTLE":
                _motor_set("stop")
                if now_ts >= sm_settle_until:
                    sm_state = "FIRE"

            elif sm_state == "FIRE":
                _motor_set("stop")
                if sm_target is None:
                    sm_state = "SCAN"
                elif now_ts >= sm_cooldown_until and (now_ts - last_fire_ts) >= args.cooldown:
                    # Re-verify target còn trong frame
                    still_there = False
                    if run_inference:
                        for d in dets:
                            if (abs(d["cx_norm"] - sm_target["cx_norm"]) < 0.08 and
                                    abs(d["cy_norm"] - sm_target["cy_norm"]) < 0.08):
                                still_there = True
                                break
                    else:
                        still_there = True  # skip re-verify on frame-skip
                    if still_there:
                        _fire_laser(laser, args.pulse, args.state_debug_log)
                        last_fire_ts = now_ts
                        sm_cooldown_until = now_ts + args.cooldown
                        shot_targets.append((sm_target["cx_norm"], sm_target["cy_norm"]))
                        if len(shot_targets) > 50:
                            shot_targets.pop(0)
                        sm_target = None
                        sm_state = "COOLDOWN"
                        if args.state_debug_log:
                            log.info("[SM] FIRE→COOLDOWN (total shot=%d)",
                                     len(shot_targets))
                    else:
                        if args.state_debug_log:
                            log.info("[SM] FIRE aborted: target lost")
                        sm_target = None
                        sm_state = "AIM" if sm_queue else "SCAN"

            elif sm_state == "COOLDOWN":
                _motor_set("stop")
                if now_ts >= sm_cooldown_until:
                    sm_state = "AIM" if sm_queue else "SCAN"
                    if args.state_debug_log:
                        log.info("[SM] COOLDOWN→%s", sm_state)

            # Reset shot_targets nếu hết unshot quá lâu
            if not unshot and shot_targets and (now_ts - last_fire_ts) > args.resume_delay:
                log.info("Batch done (%d shots), reset", len(shot_targets))
                shot_targets.clear()

            # Display
            if args.show:
                for d in dets:
                    color = (0, 0, 255) if _is_shot(d) else (0, 255, 0)
                    cv2.rectangle(frame,
                        (int(d["cx"] - d["w"]/2), int(d["cy"] - d["h"]/2)),
                        (int(d["cx"] + d["w"]/2), int(d["cy"] + d["h"]/2)),
                        color, 2)
                cv2.putText(frame, f"State:{sm_state} Shot:{len(shot_targets)}",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.imshow("weed_laser", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                time.sleep(delay)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.exception("Main loop error: %s", e)
    finally:
        # CRITICAL: laser off TRƯỚC mọi cleanup khác
        try: laser.off()
        except Exception: pass
        try:
            if motor is not None: motor.stop()
        except Exception: pass
        try:
            if hasattr(cap, "release"): cap.release()
        except Exception: pass
        try: cv2.destroyAllWindows()
        except Exception: pass
        try:
            if servo is not None: servo.cleanup()
        except Exception as e: log.warning("servo cleanup: %s", e)
        try: laser.cleanup()
        except Exception as e: log.warning("laser cleanup: %s", e)
        try:
            if motor is not None: motor.cleanup()
        except Exception as e: log.warning("motor cleanup: %s", e)
        log.info("Shutdown complete")
    return 0

# ---------------------------------------------------------------- CLI
def parse_args():
    p = argparse.ArgumentParser("Weed detection + laser")
    p.add_argument("--model", default="models/best.pt")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--picam2", action="store_true")
    p.add_argument("--pca9685", action="store_true")
    p.add_argument("--no-motor", action="store_true")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--imgsz", type=int, default=320)
    p.add_argument("--conf", type=float, default=0.4)
    p.add_argument("--class-id", type=int, default=1,
                   help="0=crop, 1=weed (default weed)")
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--frame-skip", type=int, default=1)
    p.add_argument("--show", action="store_true")
    p.add_argument("--state-debug-log", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--log-file", default="")
    # Stability / aim
    p.add_argument("--vote-window", type=int, default=5)
    p.add_argument("--min-hits", type=int, default=3)
    p.add_argument("--confirm", type=int, default=3)
    p.add_argument("--max-targets", type=int, default=3)
    p.add_argument("--aim", choices=["center", "left", "right"], default="center")
    # Servo
    p.add_argument("--pan-gain", type=float, default=0.6)
    p.add_argument("--tilt-gain", type=float, default=0.6)
    p.add_argument("--offset-pan", type=float, default=0.0)
    p.add_argument("--offset-tilt", type=float, default=0.0)
    # Timing
    p.add_argument("--settle", type=float, default=0.3)
    p.add_argument("--cooldown", type=float, default=0.4)
    p.add_argument("--pulse", type=float, default=LASER_DEFAULT_PULSE,
                   help=f"Laser pulse sec (HARD CAP {LASER_MAX_PULSE_SEC}s)")
    p.add_argument("--resume-delay", type=float, default=1.5)
    # Detection filter
    p.add_argument("--min-area", type=float, default=0.0003)
    p.add_argument("--max-area", type=float, default=0.5)
    p.add_argument("--roi-top", type=float, default=0.3)
    p.add_argument("--roi-bottom", type=float, default=1.0)
    return p.parse_args()

def setup_logging(args):
    level = logging.DEBUG if args.verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

def main():
    args = parse_args()
    setup_logging(args)
    if args.pulse > LASER_MAX_PULSE_SEC:
        log.warning("--pulse %.2fs > cap, sẽ clamp về %.2fs",
                    args.pulse, LASER_MAX_PULSE_SEC)
    return run_system(args)

if __name__ == "__main__":
    sys.exit(main())
