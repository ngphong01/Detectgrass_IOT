from __future__ import annotations

import time
import random
import cv2
import numpy as np

class MockVideoCapture:
    """Mock camera that simulates a camera feed with moving crops and weeds."""
    def __init__(self, w: int = 640, h: int = 480):
        self.w = w
        self.h = h
        self.weed_x = 320.0
        self.weed_y = -100.0  # start off-screen
        self.crop_x = 150.0
        self.crop_y = 200.0
        self.last_time = time.time()
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, np.ndarray]:
        # Fallback default read
        frame, _ = self.read_mock("FORWARD", 90.0, 90.0)
        return True, frame

    def read_mock(self, state_name: str, pan: float, tilt: float) -> tuple[np.ndarray, list[tuple[int, float, float, float, float, float]]]:
        # Background: dark green/brown soil
        frame = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        frame[:] = [18, 32, 24]  # Forest soil color

        now = time.time()
        dt = now - self.last_time
        self.last_time = now
        # Cap dt to avoid large jumps if CPU is slow
        dt = min(dt, 0.1)

        # Update positions if the robot is moving forward
        if state_name == "FORWARD":
            self.weed_y += 80.0 * dt
            self.crop_y += 80.0 * dt
            if self.weed_y > self.h + 60:
                self.weed_y = -150.0
                self.weed_x = random.randint(180, 460)
            if self.crop_y > self.h + 60:
                self.crop_y = -150.0
                self.crop_x = random.randint(100, 540)

        # Draw grid lines to simulate forward movement
        grid_offset = int((time.time() * 40) % 80)
        for y in range(grid_offset, self.h, 80):
            cv2.line(frame, (0, y), (self.w, y), (25, 45, 30), 1)

        # Draw Crop (class 0)
        if -50 <= self.crop_y <= self.h + 50:
            cx, cy = int(self.crop_x), int(self.crop_y)
            cv2.circle(frame, (cx, cy), 32, (40, 160, 60), -1)
            cv2.circle(frame, (cx, cy), 12, (70, 200, 90), -1)
            # Leaf details
            cv2.line(frame, (cx - 25, cy), (cx + 25, cy), (90, 220, 110), 1)
            cv2.line(frame, (cx, cy - 25), (cx, cy + 25), (90, 220, 110), 1)
            cv2.putText(frame, "CROP", (cx - 16, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

        detections = []
        # Add crop detection to output (cls_id, confidence, x1, y1, x2, y2)
        if 0 <= self.crop_x < self.w and 0 <= self.crop_y < self.h:
            detections.append((0, 0.95, self.crop_x - 32, self.crop_y - 32, self.crop_x + 32, self.crop_y + 32))

        # Draw Weed (class 1)
        if -50 <= self.weed_y <= self.h + 50:
            wx, wy = int(self.weed_x), int(self.weed_y)
            # Spiky brown/red weed
            pts = np.array([
                [wx, wy - 18], [wx + 5, wy - 5], [wx + 18, wy - 8], [wx + 5, wy],
                [wx + 12, wy + 12], [wx, wy + 5], [wx - 12, wy + 12], [wx - 5, wy],
                [wx - 18, wy - 8], [wx - 5, wy - 5]
            ], np.int32)
            cv2.fillPoly(frame, [pts], (40, 60, 180)) # red-brown spiky weed
            cv2.circle(frame, (wx, wy), 5, (20, 30, 120), -1)
            cv2.putText(frame, "WEED", (wx - 16, wy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

            detections.append((1, 0.89, self.weed_x - 18, self.weed_y - 18, self.weed_x + 18, self.weed_y + 18))

            # Simulate laser beam aiming & firing
            if state_name == "FIRING":
                # Red glow
                cv2.circle(frame, (wx, wy), 20, (0, 0, 255), 2)
                cv2.circle(frame, (wx, wy), 8, (0, 0, 255), -1)
                cv2.circle(frame, (wx, wy), 3, (255, 255, 255), -1)
                cv2.putText(frame, "LASER ACTIVE", (wx - 35, wy - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        return frame, detections

    def release(self) -> None:
        self._opened = False
