#!/usr/bin/env python3
"""
parser.py — Floor Plan Image Analyser (fixed)
==============================================
Fixes applied vs previous version:
  - outer wall tolerance now scales with image size (was hardcoded 12px)
  - segment_to_norm correctly normalises all 4 coords independently
  - infer_openings disabled (was mixing pixel/norm spaces → phantom doors)
  - opening cap reduced to 20 (was 70 combined)
  - wall_segments now carry load_bearing / partition classification
"""

import sys
import json
import cv2
import numpy as np

MIN_ROOM_FRACTION        = 0.008
MAX_ROOMS                = 20
SNAP_TOLERANCE_PX        = 10
MIN_OPENING_AREA         = 18
MAX_OPENING_AREA_FRACTION = 0.015


# ─────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────
def normalise(val, ref, scale=100.0):
    return round(float(val) / float(max(ref, 1)) * scale, 2)


def px_to_norm_rect(x, y, w, h, img_w, img_h):
    return {
        "x":      normalise(x,     img_w),
        "y":      normalise(y,     img_h),
        "width":  normalise(w,     img_w),
        "height": normalise(h,     img_h),
        "area":   round(normalise(w, img_w) * normalise(h, img_h), 2),
    }


def segment_to_norm(seg, img_w, img_h):
    """
    Normalise a pixel-space wall segment to 0-100 space.
    Each coordinate is normalised independently — NOT as a delta.
    Length is recomputed in normalised space after conversion.
    """
    nx1 = normalise(seg["x1"], img_w)
    ny1 = normalise(seg["y1"], img_h)
    nx2 = normalise(seg["x2"], img_w)
    ny2 = normalise(seg["y2"], img_h)
    length = round(((nx2 - nx1) ** 2 + (ny2 - ny1) ** 2) ** 0.5, 2)
    return {
        "x1":          nx1,
        "y1":          ny1,
        "x2":          nx2,
        "y2":          ny2,
        "orientation": seg["orientation"],
        "kind":        seg.get("kind", "interior"),
        "wall_type":   seg.get("wall_type", "partition"),
        "length":      length,
    }


def merge_nearby_values(values, tolerance):
    if not values:
        return []
    values = sorted(values)
    groups = [[values[0]]]
    for value in values[1:]:
        if abs(value - np.mean(groups[-1])) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [int(round(float(np.mean(g)))) for g in groups]


def snap_value(value, guides, tolerance):
    if not guides:
        return int(value)
    best = min(guides, key=lambda g: abs(g - value))
    return int(best if abs(best - value) <= tolerance else value)


def merge_ranges(ranges, tolerance=3):
    if not ranges:
        return []
    ranges = sorted((min(a, b), max(a, b)) for a, b in ranges)
    merged = [list(ranges[0])]
    for start, end in ranges[1:]:
        if start <= merged[-1][1] + tolerance:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


# ─────────────────────────────────────────────────────────────────
# Room processing
# ─────────────────────────────────────────────────────────────────
def snap_rooms(rooms, shell_rect, img_w, img_h):
    if not rooms:
        return []

    shell_x, shell_y, shell_w, shell_h = shell_rect
    x_guides = [shell_x, shell_x + shell_w]
    y_guides = [shell_y, shell_y + shell_h]

    for r in rooms:
        x_guides.extend([r["x"], r["x"] + r["width"]])
        y_guides.extend([r["y"], r["y"] + r["height"]])

    x_guides = merge_nearby_values(x_guides, SNAP_TOLERANCE_PX)
    y_guides = merge_nearby_values(y_guides, SNAP_TOLERANCE_PX)

    snapped = []
    seen = set()
    for r in rooms:
        x1 = snap_value(r["x"],             x_guides, SNAP_TOLERANCE_PX)
        y1 = snap_value(r["y"],             y_guides, SNAP_TOLERANCE_PX)
        x2 = snap_value(r["x"] + r["width"],  x_guides, SNAP_TOLERANCE_PX)
        y2 = snap_value(r["y"] + r["height"], y_guides, SNAP_TOLERANCE_PX)

        x1 = max(shell_x, min(x1, shell_x + shell_w))
        y1 = max(shell_y, min(y1, shell_y + shell_h))
        x2 = max(shell_x, min(x2, shell_x + shell_w))
        y2 = max(shell_y, min(y2, shell_y + shell_h))

        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        key = (x1, y1, w, h)
        if key in seen:
            continue
        seen.add(key)
        snapped.append(px_to_norm_rect(x1, y1, w, h, img_w, img_h))

    snapped.sort(key=lambda r: r["area"], reverse=True)
    return snapped[:MAX_ROOMS]


# ─────────────────────────────────────────────────────────────────
# Wall extraction
# ─────────────────────────────────────────────────────────────────
def extract_linear_masks(closed, img_w, img_h):
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, img_w // 18), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, img_h // 18)))
    horiz = cv2.morphologyEx(closed, cv2.MORPH_OPEN, h_kernel)
    vert  = cv2.morphologyEx(closed, cv2.MORPH_OPEN, v_kernel)
    return horiz, vert


def contours_to_segments(mask, orientation, shell_rect, img_w, img_h):
    """
    Convert mask contours to wall segments in PIXEL space.
    Outer tolerance now scales with image size to avoid misclassification.

    FIX: tolerance was hardcoded at 12px — now scales to ~2% of image dimension.
    """
    sx, sy, sw, sh = shell_rect
    shell_right  = sx + sw
    shell_bottom = sy + sh

    # Scale tolerance: ~2% of image dimension, min 10px, max 30px
    h_tol = max(10, min(30, int(img_h * 0.02)))
    v_tol = max(10, min(30, int(img_w * 0.02)))

    segs = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        if orientation == "horizontal":
            if w < 10:
                continue
            y_mid = y + h // 2
            is_outer = abs(y_mid - sy) <= h_tol or abs(y_mid - shell_bottom) <= h_tol
            kind      = "outer" if is_outer else "interior"
            wall_type = "load_bearing" if is_outer else "partition"
            segs.append({
                "x1": x, "y1": y_mid,
                "x2": x + w, "y2": y_mid,
                "orientation": orientation,
                "kind": kind,
                "wall_type": wall_type,
            })
        else:
            if h < 10:
                continue
            x_mid = x + w // 2
            is_outer = abs(x_mid - sx) <= v_tol or abs(x_mid - shell_right) <= v_tol
            kind      = "outer" if is_outer else "interior"
            wall_type = "load_bearing" if is_outer else "partition"
            segs.append({
                "x1": x_mid, "y1": y,
                "x2": x_mid, "y2": y + h,
                "orientation": orientation,
                "kind": kind,
                "wall_type": wall_type,
            })

    return segs


def merge_segments(segments, tolerance=6, gap_tolerance=12):
    if not segments:
        return []
    merged = []
    for orientation in ("horizontal", "vertical"):
        bucket = [s.copy() for s in segments if s["orientation"] == orientation]
        bucket.sort(key=lambda s: (
            s["kind"],
            s["y1"] if orientation == "horizontal" else s["x1"],
            s["x1"] if orientation == "horizontal" else s["y1"],
        ))
        groups = []
        for seg in bucket:
            coord = seg["y1"] if orientation == "horizontal" else seg["x1"]
            placed = False
            for group in groups:
                gcoord = int(round(np.mean([
                    g["y1"] if orientation == "horizontal" else g["x1"]
                    for g in group
                ])))
                if seg["kind"] == group[0]["kind"] and abs(coord - gcoord) <= tolerance:
                    group.append(seg)
                    placed = True
                    break
            if not placed:
                groups.append([seg])

        for group in groups:
            coord = int(round(np.mean([
                g["y1"] if orientation == "horizontal" else g["x1"]
                for g in group
            ])))
            kind      = group[0]["kind"]
            wall_type = group[0]["wall_type"]
            ranges = []
            for g in group:
                if orientation == "horizontal":
                    ranges.append((g["x1"], g["x2"]))
                else:
                    ranges.append((g["y1"], g["y2"]))

            for start, end in merge_ranges(ranges, gap_tolerance):
                if orientation == "horizontal":
                    merged.append({
                        "x1": start, "y1": coord,
                        "x2": end,   "y2": coord,
                        "orientation": orientation,
                        "kind": kind, "wall_type": wall_type,
                    })
                else:
                    merged.append({
                        "x1": coord, "y1": start,
                        "x2": coord, "y2": end,
                        "orientation": orientation,
                        "kind": kind, "wall_type": wall_type,
                    })
    return merged


# ─────────────────────────────────────────────────────────────────
# Opening detection  (pixel space only — no inferred openings)
# ─────────────────────────────────────────────────────────────────
# Standard real-world opening dimensions (metres)
STD_DOOR_W_M   = 0.90
STD_DOOR_H_M   = 2.10
STD_WINDOW_W_M = 1.20
STD_WINDOW_H_M = 1.20

def classify_opening(x, y, w, h, shell_rect):
    """
    Classify an opening as window/door and identify which wall it's on.
    Windows: near outer shell boundary.
    Doors:   on interior walls.
    Returns: (opening_type, orientation, wall_side)
    """
    sx, sy, sw, sh = shell_rect
    shell_right  = sx + sw
    shell_bottom = sy + sh
    cx = x + w / 2
    cy = y + h / 2

    h_tol = max(12, int(sh * 0.04))
    v_tol = max(12, int(sw * 0.04))

    on_top    = abs(cy - sy)           <= h_tol
    on_bottom = abs(cy - shell_bottom) <= h_tol
    on_left   = abs(cx - sx)           <= v_tol
    on_right  = abs(cx - shell_right)  <= v_tol

    near_outer = on_top or on_bottom or on_left or on_right

    if on_top:       wall_side = "top"
    elif on_bottom:  wall_side = "bottom"
    elif on_left:    wall_side = "left"
    elif on_right:   wall_side = "right"
    else:            wall_side = "interior"

    opening_type = "window" if near_outer else "door"
    orientation  = "horizontal" if w >= h else "vertical"
    return opening_type, orientation, wall_side


def extract_openings(binary, closed, shell_mask, shell_rect, img_w, img_h):
    base_gaps = cv2.subtract(closed, binary)

    horiz_base = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(6, img_w // 35), 1)))
    vert_base  = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(6, img_h // 35))))

    horiz_closed = cv2.morphologyEx(horiz_base, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, img_w // 22), 1)))
    vert_closed  = cv2.morphologyEx(vert_base, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, img_h // 22))))

    directional_gaps = cv2.bitwise_or(
        cv2.subtract(horiz_closed, horiz_base),
        cv2.subtract(vert_closed,  vert_base)
    )

    filled_gaps = cv2.bitwise_or(base_gaps, directional_gaps)
    filled_gaps = cv2.bitwise_and(filled_gaps, shell_mask)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    filled_gaps = cv2.morphologyEx(filled_gaps, cv2.MORPH_OPEN,  kernel, iterations=1)
    filled_gaps = cv2.dilate(filled_gaps, kernel, iterations=1)

    contours, _ = cv2.findContours(filled_gaps, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    sx, sy, sw, sh = shell_rect
    max_area = sw * sh * MAX_OPENING_AREA_FRACTION
    openings = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < MIN_OPENING_AREA or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 3 or h < 3:
            continue
        opening_type, orientation, wall_side = classify_opening(x, y, w, h, shell_rect)
        real_w_m = STD_WINDOW_W_M if opening_type == "window" else STD_DOOR_W_M
        real_h_m = STD_WINDOW_H_M if opening_type == "window" else STD_DOOR_H_M
        entry = px_to_norm_rect(x, y, w, h, img_w, img_h)
        entry.update({
            "type":            opening_type,
            "orientation":     orientation,
            "wall_side":       wall_side,
            "real_width_m":    real_w_m,
            "real_height_m":   real_h_m,
            "opening_area_m2": round(real_w_m * real_h_m, 3),
        })
        openings.append(entry)

    # Deduplicate
    openings.sort(key=lambda o: o["area"], reverse=True)
    deduped = []
    for item in openings:
        if any(
            abs(item["x"] - o["x"]) < 1.5 and
            abs(item["y"] - o["y"]) < 1.5
            for o in deduped
        ):
            continue
        deduped.append(item)

    # Quality filter: reject small/sliver interior gaps that are wall artefacts
    # Real doors: norm area > 8.0 and aspect ratio < 8:1
    # Windows: keep all (frame-lines are intentionally small)
    MIN_DOOR_AREA_NORM = 8.0
    MAX_DOOR_ASPECT    = 8.0
    filtered = []
    for o in deduped:
        if o["type"] == "window":
            filtered.append(o)
        else:
            w, h = o["width"], o["height"]
            aspect = max(w, h) / max(min(w, h), 0.01)
            if o["area"] >= MIN_DOOR_AREA_NORM and aspect <= MAX_DOOR_ASPECT:
                filtered.append(o)

    return filtered[:20]


# ─────────────────────────────────────────────────────────────────
# Opening summary + wall area deduction
# ─────────────────────────────────────────────────────────────────
def compute_opening_summary(openings, outer_perimeter_norm,
                             inner_wall_len_norm,
                             wall_height_m=3.0,
                             norm_to_m_scale=0.1):
    """
    Count openings and compute NET wall area after deducting doors/windows.

    WHY THIS MATTERS:
      Brick, mortar, and plaster quantities must use NET wall area.
      Ignoring openings typically over-orders materials by 10-20%.

    Returns a dict with counts, areas, and gross/net wall area in m².
    """
    doors   = [o for o in openings if o["type"] == "door"]
    windows = [o for o in openings if o["type"] == "window"]

    door_area_m2   = round(sum(o["opening_area_m2"] for o in doors),   2)
    window_area_m2 = round(sum(o["opening_area_m2"] for o in windows), 2)
    total_open_m2  = round(door_area_m2 + window_area_m2, 2)

    # Total wall length in metres
    total_wall_len_m   = round((outer_perimeter_norm + inner_wall_len_norm) * norm_to_m_scale, 2)
    gross_wall_area_m2 = round(total_wall_len_m * wall_height_m, 2)
    net_wall_area_m2   = round(max(0, gross_wall_area_m2 - total_open_m2), 2)
    deduction_m2       = round(gross_wall_area_m2 - net_wall_area_m2, 2)

    return {
        "door_count":             len(doors),
        "window_count":           len(windows),
        "total_door_area_m2":     door_area_m2,
        "total_window_area_m2":   window_area_m2,
        "total_opening_area_m2":  total_open_m2,
        "gross_wall_area_m2":     gross_wall_area_m2,
        "net_wall_area_m2":       net_wall_area_m2,
        "opening_deduction_m2":   deduction_m2,
        "wall_height_m":          wall_height_m,
        "total_wall_length_m":    total_wall_len_m,
    }


# ─────────────────────────────────────────────────────────────────
# Main analysis
# ─────────────────────────────────────────────────────────────────
def analyse(image_path: str) -> dict:
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot open image: {image_path}")

    img_h, img_w = img.shape[:2]
    gray    = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    _, binary_otsu = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    binary_adapt = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        15, 4,
    )
    binary = cv2.bitwise_or(binary_otsu, binary_adapt)

    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(3, img_w // 150), max(3, img_h // 150))
    )
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("No contours found — is this a floor plan image?")

    outer_cnt = max(contours, key=cv2.contourArea)
    ox, oy, ow, oh = cv2.boundingRect(outer_cnt)
    shell_rect = (ox, oy, ow, oh)
    outer_shell = px_to_norm_rect(ox, oy, ow, oh, img_w, img_h)

    shell_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    cv2.drawContours(shell_mask, [outer_cnt], -1, 255, thickness=cv2.FILLED)

    # ── Rooms ──
    inverted    = cv2.bitwise_not(closed)
    inside_empty = cv2.bitwise_and(inverted, shell_mask)

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(
        inside_empty, connectivity=8
    )
    min_room_px = max(1, ow * oh) * MIN_ROOM_FRACTION
    rooms_px = []
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < min_room_px:
            continue
        rooms_px.append({"x": x, "y": y, "width": w, "height": h, "area_px": area})

    rooms_px.sort(key=lambda r: r["area_px"], reverse=True)
    rooms = snap_rooms(rooms_px[:MAX_ROOMS], shell_rect, img_w, img_h)

    # ── Wall segments ──
    horiz_mask, vert_mask = extract_linear_masks(closed, img_w, img_h)
    raw_segments = (
        contours_to_segments(horiz_mask, "horizontal", shell_rect, img_w, img_h) +
        contours_to_segments(vert_mask,  "vertical",   shell_rect, img_w, img_h)
    )
    merged_px    = merge_segments(raw_segments)
    wall_segments = [segment_to_norm(seg, img_w, img_h) for seg in merged_px]

    # ── Openings (pixel-detected only — no inferred) ──
    openings = extract_openings(binary, closed, shell_mask, shell_rect, img_w, img_h)

    # ── Metrics ──
    shell_w = outer_shell["width"]
    shell_h = outer_shell["height"]
    floor_area      = round(shell_w * shell_h, 2)
    outer_perimeter = round(2 * (shell_w + shell_h), 2)
    inner_wall_len  = round(
        sum(s["length"] for s in wall_segments if s["kind"] == "interior"), 2
    )
    aspect = round(max(shell_w, shell_h) / max(min(shell_w, shell_h), 0.001), 2)

    lb_count = sum(1 for s in wall_segments if s["wall_type"] == "load_bearing")
    pt_count = sum(1 for s in wall_segments if s["wall_type"] == "partition")

    max_span = 0.0
    if rooms:
        max_span = round(max(max(r["width"], r["height"]) for r in rooms), 2)

    # Compute opening summary and wall area deductions
    opening_summary = compute_opening_summary(
        openings,
        outer_perimeter_norm  = outer_perimeter,
        inner_wall_len_norm   = inner_wall_len,
    )

    return {
        "structure": {
            "outer_shell":              outer_shell,
            "rooms":                    rooms,
            "room_count":               len(rooms),
            "total_area":               floor_area,
            "wall_segments":            wall_segments,
            "openings":                 openings,
            "opening_summary":          opening_summary,
            "load_bearing_wall_count":  lb_count,
            "partition_wall_count":     pt_count,
        },
        "metrics": {
            "outer_wall_perimeter":  outer_perimeter,
            "inner_wall_length":     inner_wall_len,
            "floor_area":            floor_area,
            "aspect_ratio":          aspect,
            "max_span":              max_span,
            "image_width_px":        img_w,
            "image_height_px":       img_h,
            "wall_segment_count":    len(wall_segments),
            "opening_count":         len(openings),
            # Material-relevant deduction metrics
            "gross_wall_area_m2":    opening_summary["gross_wall_area_m2"],
            "net_wall_area_m2":      opening_summary["net_wall_area_m2"],
            "opening_deduction_m2":  opening_summary["opening_deduction_m2"],
            "door_count":            opening_summary["door_count"],
            "window_count":          opening_summary["window_count"],
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: parser.py <image_path>"}))
        sys.exit(1)

    try:
        print(json.dumps(analyse(sys.argv[1])))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)