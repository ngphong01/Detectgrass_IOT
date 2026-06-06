from __future__ import annotations

from dataclasses import dataclass


# Giới hạn góc servo thực tế (tránh rung ở 0°/180°)
SERVO_ANGLE_MIN = 20.0
SERVO_ANGLE_MAX = 160.0


@dataclass
class CameraConfig:
    # Horizontal / vertical field of view of the camera (degrees)
    fov_h: float = 62.2  # Raspberry Pi Camera v2 approx
    fov_v: float = 48.8
    # Servo neutral angles (camera looking straight at center)
    servo_center_pan: float = 90.0
    servo_center_tilt: float = 90.0
    # Servo angle limits (giới hạn 20–160° tránh rung)
    servo_min_pan: float = SERVO_ANGLE_MIN
    servo_max_pan: float = SERVO_ANGLE_MAX
    servo_min_tilt: float = SERVO_ANGLE_MIN
    servo_max_tilt: float = SERVO_ANGLE_MAX
    # Calibration: offset sau khi đổi pixel → góc (laser bắn trúng tâm)
    offset_pan: float = 0.0
    offset_tilt: float = 0.0
    # Physical calibration for static camera
    is_static: bool = True
    cam_height: float = 10.0      # cm (webcam cách mặt đất 10cm)
    servo_height: float = 15.0    # cm (servo ở độ cao 15cm)
    cam_tilt: float = 27.5        # degrees (chếch 25-30 độ hướng xuống)
    invert_pan: bool = False
    invert_tilt: bool = False


def clamp(value: float, vmin: float, vmax: float) -> float:
    return max(vmin, min(vmax, value))


def yolo_bbox_to_pixel_center(
    xyxy: tuple[float, float, float, float],
) -> tuple[float, float]:
    """
    Convert YOLO xyxy bbox to pixel center (still in pixels, caller must know image size).
    xyxy = (x1, y1, x2, y2)
    """
    x1, y1, x2, y2 = xyxy
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return cx, cy


def pixel_to_servo_angles(
    center: tuple[float, float],
    img_size: tuple[int, int],
    cfg: CameraConfig | None = None,
) -> tuple[float, float]:
    """
    Map pixel center in image to pan/tilt servo angles.

    - center: (cx, cy) in pixel coordinates.
    - img_size: (width, height) of the frame.
    - cfg: camera / servo configuration.
    """
    if cfg is None:
        cfg = CameraConfig()

    cx, cy = center
    w, h = img_size

    if cfg.is_static:
        import math
        # Normalize to [-0.5, 0.5] where 0 is center
        nx = (cx / w) - 0.5
        ny = (cy / h) - 0.5  # ny > 0 is lower half (closer), ny < 0 is upper half (further)

        # Pan angle mapping (horizontal)
        pan_factor = -1.0 if not cfg.invert_pan else 1.0
        angle_x = nx * cfg.fov_h * pan_factor
        pan = clamp(cfg.servo_center_pan + angle_x + cfg.offset_pan, cfg.servo_min_pan, cfg.servo_max_pan)

        # Tilt angle mapping (vertical, geometric correction for camera tilt & height offset)
        cam_tilt_rad = math.radians(cfg.cam_tilt)
        angle_y_rad = math.radians(ny * cfg.fov_v)
        
        # Target angle relative to the horizontal plane
        target_tilt_rad = cam_tilt_rad + angle_y_rad
        target_tilt_rad = clamp(target_tilt_rad, math.radians(5.0), math.radians(85.0))
        
        # Ground distance from camera base projection to target
        distance_ground = cfg.cam_height / math.tan(target_tilt_rad)
        
        # Angle from servo to target on ground
        beta_rad = math.atan(cfg.servo_height / max(0.1, distance_ground))
        beta_deg = math.degrees(beta_rad)
        
        # Center calibration factor
        beta_center_rad = math.atan(cfg.servo_height / (cfg.cam_height / math.tan(cam_tilt_rad)))
        beta_center_deg = math.degrees(beta_center_rad)
        
        tilt_diff = beta_deg - beta_center_deg
        tilt_factor = 1.0 if not cfg.invert_tilt else -1.0
        tilt_diff_actual = tilt_diff * tilt_factor
        tilt = clamp(cfg.servo_center_tilt + tilt_diff_actual + cfg.offset_tilt, cfg.servo_min_tilt, cfg.servo_max_tilt)
        
        return pan, tilt
    else:
        # Normalize to [-0.5, 0.5] where 0 is center
        nx = (cx / w) - 0.5
        ny = (cy / h) - 0.5

        # Convert to angles using FOV
        pan_factor = -1.0 if not cfg.invert_pan else 1.0
        tilt_factor = 1.0 if not cfg.invert_tilt else -1.0
        angle_x = nx * cfg.fov_h * pan_factor
        angle_y = ny * cfg.fov_v * tilt_factor

        pan = clamp(cfg.servo_center_pan + angle_x + cfg.offset_pan, cfg.servo_min_pan, cfg.servo_max_pan)
        tilt = clamp(cfg.servo_center_tilt + angle_y + cfg.offset_tilt, cfg.servo_min_tilt, cfg.servo_max_tilt)

        return pan, tilt


def yolo_bbox_to_servo_angles(
    xyxy: tuple[float, float, float, float],
    img_size: tuple[int, int],
    cfg: CameraConfig | None = None,
) -> tuple[float, float]:
    """
    Helper: take YOLO xyxy box and directly output servo angles.
    """
    center = yolo_bbox_to_pixel_center(xyxy)
    return pixel_to_servo_angles(center, img_size, cfg)


def pixel_to_servo_angles_simple(
    x_center: float,
    y_center: float,
    width: float,
    height: float,
    servo_range: float = 180.0,
    servo_min: float = SERVO_ANGLE_MIN,
    servo_max: float = SERVO_ANGLE_MAX,
    offset_pan: float = 0.0,
    offset_tilt: float = 0.0,
) -> tuple[float, float]:
    """
    Công thức đơn giản: servo = (pixel / kích_thước_ảnh) * 180, rồi clamp 20–160°.
    offset_pan/offset_tilt dùng để calibrate camera → servo (laser bắn trúng).
    """
    servo_x = (x_center / width) * servo_range + offset_pan
    servo_y = (y_center / height) * servo_range + offset_tilt
    servo_x = clamp(servo_x, servo_min, servo_max)
    servo_y = clamp(servo_y, servo_min, servo_max)
    return servo_x, servo_y


def yolo_bbox_to_servo_angles_simple(
    xyxy: tuple[float, float, float, float],
    img_size: tuple[int, int],
    servo_range: float = 180.0,
    servo_min: float = SERVO_ANGLE_MIN,
    servo_max: float = SERVO_ANGLE_MAX,
    offset_pan: float = 0.0,
    offset_tilt: float = 0.0,
) -> tuple[float, float]:
    """Lấy tâm bbox YOLO rồi đổi sang góc servo theo công thức đơn giản (có clamp + offset)."""
    cx, cy = yolo_bbox_to_pixel_center(xyxy)
    w, h = img_size
    return pixel_to_servo_angles_simple(
        cx, cy, w, h, servo_range, servo_min, servo_max, offset_pan, offset_tilt
    )

