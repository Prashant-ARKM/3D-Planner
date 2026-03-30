#!/usr/bin/env python3
"""
materials.py  —  Gemini-Powered Material Recommendation Engine
===============================================================
"""

import sys
import json
import os
import warnings

# Suppress the Google SDK deprecation warning to keep your terminal clean
warnings.filterwarnings("ignore", category=FutureWarning)

# ─────────────────────────────────────────────────────────────────
# 1. LOAD .env
# ─────────────────────────────────────────────────────────────────
def load_dotenv(env_path: str) -> dict:
    env = {}
    if not os.path.exists(env_path):
        return env

    with open(env_path, "rb") as f:
        raw = f.read()

    lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8").split("\n")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw_val = line.partition("=")
        env[key.strip()] = raw_val.strip().strip('"').strip("'").strip()

    return env

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH   = os.path.join(SCRIPT_DIR, ".env")
env_vars   = load_dotenv(ENV_PATH)

GEMINI_API_KEY = env_vars.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")

# 🚀 FIX: Hardcoded back to gemini-2.5-flash (which we know works on your key!)
GEMINI_MODEL   = "gemini-2.5-flash"

# ─────────────────────────────────────────────────────────────────
# 2. BUILD THE PROMPT
# ─────────────────────────────────────────────────────────────────
def build_prompt(parsed: dict) -> str:
    structure = parsed.get("structure", {})
    metrics   = parsed.get("metrics",   {})

    room_count    = structure.get("room_count",           "unknown")
    total_area    = structure.get("total_area",           "unknown")
    floor_area    = metrics.get("floor_area",             "unknown")
    perimeter     = metrics.get("outer_wall_perimeter",   "unknown")
    inner_len     = metrics.get("inner_wall_length",      "unknown")
    aspect_ratio  = metrics.get("aspect_ratio",           "unknown")

    rooms = structure.get("rooms", [])
    room_lines = ""
    if rooms:
        room_lines = "\n".join(
            f"  - Room {i+1}: {r.get('width', '?'):.1f} × {r.get('height', '?'):.1f} "
            f"(area {r.get('area', '?'):.1f} norm units)"
            for i, r in enumerate(rooms[:8])
        )
    else:
        room_lines = "  (no individual rooms detected)"

    opening_summary = structure.get("opening_summary", {})
    door_count    = opening_summary.get("door_count",            0)
    window_count  = opening_summary.get("window_count",          0)
    gross_wall_m2 = opening_summary.get("gross_wall_area_m2",    "unknown")
    net_wall_m2   = opening_summary.get("net_wall_area_m2",      "unknown")
    deduction_m2  = opening_summary.get("opening_deduction_m2",  "unknown")
    door_area_m2  = opening_summary.get("total_door_area_m2",    "unknown")
    win_area_m2   = opening_summary.get("total_window_area_m2",  "unknown")

    prompt = f"""
You are an expert structural engineer and construction material consultant.

A 2D floor plan has been analysed by computer vision software.
Below are the extracted building metrics. Your task is to recommend
the optimal construction material for each building component,
clearly explaining the cost vs durability/strength trade-off for every decision.

════════════════════════════════════════
BUILDING PROFILE (all coordinates 0-100 normalised scale)
════════════════════════════════════════
  Room count            : {room_count}
  Total floor area      : {total_area} sq normalised units
  Floor area (shell)    : {floor_area} sq normalised units
  Outer wall perimeter  : {perimeter} normalised units
  Interior wall length  : {inner_len} normalised units
  Aspect ratio (W/H)    : {aspect_ratio}

Detected rooms:
{room_lines}

════════════════════════════════════════
OPENINGS DETECTED (doors & windows)
════════════════════════════════════════
  Doors detected        : {door_count}  (standard 0.9 m × 2.1 m each = {door_area_m2} m² total)
  Windows detected      : {window_count}  (standard 1.2 m × 1.2 m each = {win_area_m2} m² total)
  Total opening area    : {deduction_m2} m²  ← DEDUCT from wall material quantities
  Gross wall area       : {gross_wall_m2} m²  (before deductions)
  Net wall area         : {net_wall_m2} m²   (after deducting all openings)

IMPORTANT: All brick, mortar, plaster, and render quantities must be
calculated on the NET wall area ({net_wall_m2} m²), NOT the gross area.

════════════════════════════════════════
INSTRUCTIONS
════════════════════════════════════════
For each of these 6 building components, recommend ONE specific material:
  1. exterior_wall
  2. interior_wall
  3. floor_slab
  4. roof
  5. foundation
  6. waterproofing

For each component:
  - Consider the building size, room count, and aspect ratio
  - Weigh COST (1=low, 2=medium, 3=high) vs DURABILITY (1-5 scale)
  - Use the trade-off logic: prefer durability unless cost is prohibitive
  - Give a concrete, specific justification (mention MPa strength, lifespan,
    cost savings in %, or specific suitability for this building size)
  - Cost and durability must be integers in the given ranges

════════════════════════════════════════
REQUIRED OUTPUT FORMAT
════════════════════════════════════════
Respond with ONLY a valid JSON object — no markdown, no code fences,
no explanation outside the JSON. The structure must be exactly:

{{
  "materials": [
    {{
      "type":             "exterior_wall",
      "material":         "<specific material name>",
      "cost_index":       <integer 1-3>,
      "durability_index": <integer 1-5>,
      "reason":           "<2-3 sentences explaining cost vs durability trade-off for this building>"
    }},
    {{
      "type":             "interior_wall",
      "material":         "...",
      "cost_index":       <1-3>,
      "durability_index": <1-5>,
      "reason":           "..."
    }},
    {{
      "type":             "floor_slab",
      "material":         "...",
      "cost_index":       <1-3>,
      "durability_index": <1-5>,
      "reason":           "..."
    }},
    {{
      "type":             "roof",
      "material":         "...",
      "cost_index":       <1-3>,
      "durability_index": <1-5>,
      "reason":           "..."
    }},
    {{
      "type":             "foundation",
      "material":         "...",
      "cost_index":       <1-3>,
      "durability_index": <1-5>,
      "reason":           "..."
    }},
    {{
      "type":             "waterproofing",
      "material":         "...",
      "cost_index":       <1-3>,
      "durability_index": <1-5>,
      "reason":           "..."
    }}
  ],
  "explanation": "<A full 200-300 word building analysis report.>"
}}
""".strip()

    return prompt

# ─────────────────────────────────────────────────────────────────
# 3. CALL GEMINI API (VIA OFFICIAL SDK)
# ─────────────────────────────────────────────────────────────────
def call_gemini(prompt: str) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not found in .env")

    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("Missing SDK. Please run: pip install google-generativeai")

    genai.configure(api_key=GEMINI_API_KEY)

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction="You are a structural engineering expert. You ALWAYS respond with valid JSON only."
        )
        
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=8192,
                response_mime_type="application/json"
            )
        )
        
        # The official SDK natively handles text extraction and limits
        return json.loads(response.text)
        
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg:
            raise RuntimeError(f"QUOTA EXCEEDED for {GEMINI_MODEL}. {error_msg[:200]}")
        raise RuntimeError(f"Gemini SDK Error: {error_msg}")

# ─────────────────────────────────────────────────────────────────
# 4. FALLBACK
# ─────────────────────────────────────────────────────────────────
def hardcoded_fallback(parsed: dict) -> dict:
    metrics    = parsed.get("metrics",   {})
    structure  = parsed.get("structure", {})
    room_count = structure.get("room_count", 3)
    floor_area = metrics.get("floor_area", 50)

    size = "small" if floor_area < 30 else ("large" if floor_area > 70 else "medium")

    materials_out = [
        {
            "type":             "exterior_wall",
            "material":         "Red Burnt Brick" if size != "large" else "Reinforced Concrete Frame",
            "cost_index":       2,
            "durability_index": 5,
            "reason":           "Red Burnt Brick offers 50-100+ year lifespan with ~10 MPa compressive strength at medium cost."
        },
        {
            "type":             "interior_wall",
            "material":         "AAC Block (100 mm)",
            "cost_index":       2,
            "durability_index": 3,
            "reason":           f"For {room_count} interior partitions, AAC Block reduces dead load by 40% vs brick."
        },
        {
            "type":             "floor_slab",
            "material":         "Reinforced Cement Concrete (RCC) Slab",
            "cost_index":       2,
            "durability_index": 5,
            "reason":           "M20-grade RCC slab supports 1.5-2 kN/m² live load with 50+ year service life."
        },
        {
            "type":             "roof",
            "material":         "RCC Flat Roof (M25)",
            "cost_index":       2,
            "durability_index": 5,
            "reason":           "Flat RCC roof allows future vertical extension (additional floors)."
        },
        {
            "type":             "foundation",
            "material":         "Strip Foundation (M20 PCC + RCC)",
            "cost_index":       2,
            "durability_index": 5,
            "reason":           "Standard strip footing is proven and economical for load-bearing wall construction."
        },
        {
            "type":             "waterproofing",
            "material":         "Polyurethane (PU) Liquid Membrane",
            "cost_index":       2,
            "durability_index": 5,
            "reason":           "Seamless PU membrane at 1.5-2 mm DFT; UV stable, 10-15 year service life."
        },
    ]

    explanation = (
        "BUILDING ANALYSIS SUMMARY\n"
        "(Fallback Mode — Gemini API unavailable)\n\n"
        f"Rooms detected : {room_count}\n"
        f"Building size  : {size}\n"
        f"Floor area     : {floor_area} normalised units\n\n"
        "Materials selected using rule-based cost/durability trade-off.\n"
        "All recommendations target a 30+ year structural lifespan\n"
        "at medium cost, suitable for standard residential construction."
    )

    return {"materials": materials_out, "explanation": explanation}

# ─────────────────────────────────────────────────────────────────
# 5. MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────
def main():
    raw_input = sys.stdin.read().strip()

    if not raw_input:
        print(json.dumps({"error": "No input received on stdin", "materials": [], "explanation": ""}))
        sys.exit(1)

    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON from parser: {e}", "materials": [], "explanation": ""}))
        sys.exit(1)

    try:
        prompt = build_prompt(parsed)
        # The SDK returns the pre-parsed dictionary directly
        result = call_gemini(prompt)

        if "materials" not in result or "explanation" not in result:
            raise ValueError("Gemini response missing 'materials' or 'explanation' keys")

        for mat in result["materials"]:
            mat["trade_off_score"] = mat.get("durability_index", 3) * 2 - mat.get("cost_index", 2)

        result["source"] = "gemini"
        print(json.dumps(result))

    except Exception as gemini_error:
        print(f"[materials.py] Gemini error: {gemini_error}", file=sys.stderr)
        
        try:
            result = hardcoded_fallback(parsed)
            result["source"]  = "fallback"
            result["warning"] = f"Gemini unavailable: {str(gemini_error)[:120]}"
            result["explanation"] += f"\n\n🚨 API ERROR DETAILS:\n{str(gemini_error)}"
            
            print(json.dumps(result))
        except Exception as fallback_error:
            print(json.dumps({"error": f"Both Gemini and fallback failed", "materials": [], "explanation": "", "source": "error"}))
            sys.exit(1)

if __name__ == "__main__":
    main()