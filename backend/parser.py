#!/usr/bin/env python3
"""
parser.py — Floor Plan Image Analyser
======================================
Input:  path to a floor plan image (JPG/PNG/etc.)
Output: JSON printed to stdout with shape:

{
  "structure": {
    "outer_shell": { "x": 0, "y": 0, "width": 100, "height": 100 },
    "rooms": [
      { "x": 5, "y": 5, "width": 40, "height": 45, "area": 1800 },
      ...
    ],
    "room_count": 4,
    "total_area": 9500
  },
  "metrics": {
    "outer_wall_perimeter": 400,
    "inner_wall_length":    260,
    "floor_area":           9500,
    "aspect_ratio":         1.3
  }
}

All coordinates are NORMALISED to 0-100 so the Three.js frontend
can use them directly regardless of the original image resolution.

Algorithm
---------
1. Load & convert to grayscale
2. Adaptive threshold  →  binary image
3. Morphological close  →  fill small gaps in walls
4. Find the OUTER CONTOUR (largest by area)
5. Find ROOM CONTOURS (significant filled regions inside the shell)
6. Normalise everything to 0-100 coordinate space
7. Emit JSON
"""

import sys
import json
import math
import cv2
import numpy as np


# ── Tuneable parameters ────────────────────────────────────────────
MIN_ROOM_FRACTION = 0.01   # room must be ≥ 1% of shell area to count
MAX_ROOMS         = 12     # cap to keep JSON small
# ──────────────────────────────────────────────────────────────────


def normalise(val, ref, scale=100.0):
    """Map a pixel value into the 0-100 normalised coordinate space."""
    return round(float(val) / float(ref) * scale, 2)


def rect_normalised(x, y, w, h, img_w, img_h):
    return {
        "x":      normalise(x, img_w),
        "y":      normalise(y, img_h),
        "width":  normalise(w, img_w),
        "height": normalise(h, img_h),
        "area":   round(normalise(w, img_w) * normalise(h, img_h), 2)
    }


def analyse(image_path: str) -> dict:
    # ── 1. Load ───────────────────────────────────────────────────
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot open image: {image_path}")

    img_h, img_w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── 2. Threshold  ─────────────────────────────────────────────
    # Gaussian blur removes JPEG noise before thresholding
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Otsu's method for clean digital plans; fall back to adaptive
    _, binary_otsu = cv2.threshold(blurred, 0, 255,
                                   cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Adaptive threshold catches plans with uneven lighting
    binary_adapt = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=15, C=4
    )

    # Combine: a pixel is "wall" if EITHER method says so
    binary = cv2.bitwise_or(binary_otsu, binary_adapt)

    # ── 3. Morphological close  ───────────────────────────────────
    # Closes small gaps/breaks in wall lines
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(3, img_w // 150), max(3, img_h // 150))
    )
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

    # ── 4. Outer shell  ───────────────────────────────────────────
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("No contours found — is this a floor plan image?")

    # Largest external contour = building footprint
    outer_cnt = max(contours, key=cv2.contourArea)
    ox, oy, ow, oh = cv2.boundingRect(outer_cnt)

    outer_shell = rect_normalised(ox, oy, ow, oh, img_w, img_h)

    # ── 5. Room detection  ────────────────────────────────────────
    #
    # Strategy: inside the building footprint, the rooms are the
    # LIGHT (white/empty) regions surrounded by dark walls.
    #
    # We crop to the bounding rect of the outer contour, then find
    # connected components of the NON-wall pixels (i.e. the rooms).

    roi = closed[oy:oy+oh, ox:ox+ow]

    # Invert so rooms are white, walls are black
    room_mask = cv2.bitwise_not(roi)

    # Small open to remove door-swing arcs and tiny noise blobs
    small_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(2, img_w // 200), max(2, img_h // 200))
    )
    room_mask = cv2.morphologyEx(room_mask, cv2.MORPH_OPEN,
                                 small_kernel, iterations=1)

    room_contours, _ = cv2.findContours(room_mask, cv2.RETR_EXTERNAL,
                                         cv2.CHAIN_APPROX_SIMPLE)

    shell_area_px = ow * oh
    min_area_px   = shell_area_px * MIN_ROOM_FRACTION

    rooms = []
    for cnt in room_contours:
        area_px = cv2.contourArea(cnt)
        if area_px < min_area_px:
            continue
        rx, ry, rw, rh = cv2.boundingRect(cnt)

        # Translate back to full-image coords, then normalise
        room = rect_normalised(
            ox + rx, oy + ry, rw, rh, img_w, img_h
        )
        rooms.append(room)

    # Sort by area descending; keep top N
    rooms.sort(key=lambda r: r["area"], reverse=True)
    rooms = rooms[:MAX_ROOMS]

    # ── 6. Metrics  ───────────────────────────────────────────────
    # All values below are in normalised units (0-100 space)
    shell_w  = outer_shell["width"]
    shell_h  = outer_shell["height"]
    floor_area = round(shell_w * shell_h, 2)

    outer_perimeter = round(2 * (shell_w + shell_h), 2)

    # Approximate inner wall length: sum of room boundary perimeters / 2
    # (each shared wall is counted once per room)
    inner_wall_len = round(
        sum(2 * (r["width"] + r["height"]) for r in rooms) / 2, 2
    )

    aspect = round(max(shell_w, shell_h) / max(min(shell_w, shell_h), 0.001), 2)

    return {
        "structure": {
            "outer_shell":  outer_shell,
            "rooms":        rooms,
            "room_count":   len(rooms),
            "total_area":   floor_area
        },
        "metrics": {
            "outer_wall_perimeter": outer_perimeter,
            "inner_wall_length":    inner_wall_len,
            "floor_area":           floor_area,
            "aspect_ratio":         aspect,
            "image_width_px":       img_w,
            "image_height_px":      img_h
        }
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: parser.py <image_path>"}))
        sys.exit(1)

    try:
        result = analyse(sys.argv[1])
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
