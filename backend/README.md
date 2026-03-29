# 3D Floor Plan Pipeline — Backend

## Overview

```
Index.html  →  POST /api/process  →  parser.py  →  materials.py  →  JSON
```

| File | Role |
|------|------|
| `server.js` | HTTP server (pure Node.js, no npm required) |
| `parser.py` | OpenCV floor plan analyser → structure JSON |
| `materials.py` | Cost vs durability material recommender |
| `setup.sh` | One-time Python dep installer |

---

## Quick Start

### 1. Requirements
- **Node.js** ≥ 16  ([nodejs.org](https://nodejs.org))
- **Python 3** ≥ 3.8 with pip

### 2. Install Python deps (once)
```bash
bash setup.sh
# or manually:
pip3 install opencv-python-headless numpy
```

### 3. Start the server
```bash
node server.js
```
Server listens on **http://localhost:3000**

### 4. Open the frontend
Open `Index.html` in your browser (double-click or use a local server).

---

## API

### `POST /api/process`
- **Body**: `multipart/form-data` with field `file` = floor plan image
- **Accepts**: JPG, PNG, BMP, TIFF, WEBP
- **Returns**:
```json
{
  "structure": {
    "outer_shell": { "x": 0, "y": 0, "width": 100, "height": 80 },
    "rooms": [
      { "x": 5, "y": 5, "width": 40, "height": 35, "area": 1400 }
    ],
    "room_count": 4,
    "total_area": 8000
  },
  "metrics": {
    "outer_wall_perimeter": 360,
    "inner_wall_length": 280,
    "floor_area": 8000,
    "aspect_ratio": 1.25
  },
  "materials": [
    {
      "type": "exterior_wall",
      "material": "Red Burnt Brick",
      "cost_index": 2,
      "durability_index": 5,
      "reason": "..."
    }
  ],
  "explanation": "BUILDING ANALYSIS SUMMARY\n..."
}
```

### `GET /health`
Returns `{ "status": "ok" }` — useful for checking the server is up.

---

## How It Works

### parser.py — Floor Plan Analysis
1. Load image, convert to grayscale
2. **Dual threshold** (Otsu + Adaptive) → binary wall mask
3. **Morphological close** → fills gaps in wall lines
4. Find largest external contour → **outer shell** (building footprint)
5. Invert inside the shell → detect **room blobs** by connected components
6. Filter noise (< 1% of shell area), keep top 12 rooms
7. **Normalise** all coordinates to 0-100 space (Three.js ready)
8. Compute metrics: perimeter, inner wall length, aspect ratio

### materials.py — Material Recommendation
Uses a **cost vs durability trade-off score**:

```
score = (durability_index × 2) − cost_index
```

For each building component (exterior wall, interior wall, floor slab,
roof, foundation, waterproofing), it picks the material with:
- Highest trade-off score
- Tags that match the building profile (small/medium/large, many rooms, etc.)

This prioritises long-term structural integrity while penalising excess cost.

### server.js — HTTP Server
- Pure Node.js stdlib — **no npm packages needed**
- Parses `multipart/form-data` without busboy/multer
- Spawns Python scripts as child processes via `child_process.spawn`
- Cleans up temp files after each request
- Full CORS headers for browser-to-local-server requests

---

## Customising Material Choices

Edit the `MATERIALS` dict in `materials.py`.  
Each material entry has:
| Field | Meaning |
|-------|---------|
| `material` | Display name |
| `cost_index` | 1=low, 2=medium, 3=high |
| `durability_index` | 1 (poor) – 5 (excellent) |
| `tags` | Matching building profiles |
| `blurb` | Human-readable justification |

Add new components (e.g., `"insulation"`, `"glazing"`) by adding new keys.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python3: command not found` | Install Python 3 and ensure it's on PATH |
| `cv2` import error | Run `pip3 install opencv-python-headless` |
| `CORS error` in browser | Make sure `node server.js` is running on port 3000 |
| Only 1 room detected | Input image may be a screenshot; use a clean architectural floor plan PNG |
| Port 3000 in use | `PORT=3001 node server.js` and update `API_URL` in `Index.html` |
