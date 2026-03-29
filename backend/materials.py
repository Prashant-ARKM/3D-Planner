#!/usr/bin/env python3
"""
materials.py — AI Material Recommendation Engine
==================================================
Input:  JSON string (the parsed structure + metrics from parser.py)
Output: JSON to stdout with shape:

{
  "materials": [
    {
      "type": "exterior_wall",
      "material": "Red Burnt Brick",
      "cost_index": 2,        # 1=low, 2=medium, 3=high
      "durability_index": 5,  # 1-5
      "reason": "..."
    },
    ...
  ],
  "explanation": "Full human-readable justification..."
}

Decision logic
--------------
The engine applies a COST vs DURABILITY/STRENGTH trade-off matrix.
It inspects:
  - floor_area          → small / medium / large building
  - aspect_ratio        → compact vs elongated plan
  - outer_wall_perimeter → how much exterior wall exposure
  - inner_wall_length   → density of interior partitions
  - room_count          → complexity

For each building component the engine scores candidate materials
and picks the one with the best trade-off score:
  score = (durability_index * 2) - cost_index

This favours durability while penalising excessive cost.
"""

import sys
import json


# ─────────────────────────────────────────────────────────────────
# MATERIAL DATABASE
# Each entry: cost_index (1=cheap, 3=expensive), durability (1-5)
# ─────────────────────────────────────────────────────────────────
MATERIALS = {

    # ── Exterior walls ──────────────────────────────────────────
    "exterior_wall": [
        {
            "material":        "Red Burnt Brick",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["all"],
            "blurb":           (
                "Classic fired clay brick: 50-100+ year lifespan, "
                "excellent compressive strength (~10 MPa), superior "
                "weather and fire resistance. Mid-range cost."
            )
        },
        {
            "material":        "Fly Ash Brick",
            "cost_index":      1,
            "durability_index": 4,
            "tags":            ["budget", "small"],
            "blurb":           (
                "Made from industrial by-product; ~15% cheaper than "
                "red brick. Compressive strength 7.5-10 MPa, good "
                "thermal mass, eco-friendly."
            )
        },
        {
            "material":        "Reinforced Concrete Frame (RCC)",
            "cost_index":      3,
            "durability_index": 5,
            "tags":            ["large", "multi-storey"],
            "blurb":           (
                "Ideal for larger structures. Steel-reinforced concrete "
                "provides exceptional seismic and load resistance. "
                "Higher upfront cost offset by longevity."
            )
        },
        {
            "material":        "Autoclaved Aerated Concrete (AAC) Block",
            "cost_index":      2,
            "durability_index": 3,
            "tags":            ["medium", "thermal"],
            "blurb":           (
                "Lightweight, excellent thermal insulation (U ~0.15). "
                "Faster to lay than brick; moderate compressive strength "
                "(3-5 MPa). Good for single-storey residential."
            )
        },
    ],

    # ── Interior / partition walls ──────────────────────────────
    "interior_wall": [
        {
            "material":        "AAC Block (100 mm)",
            "cost_index":      2,
            "durability_index": 3,
            "tags":            ["all"],
            "blurb":           (
                "Light (650 kg/m³), easy to cut on site, good acoustic "
                "and thermal separation between rooms."
            )
        },
        {
            "material":        "Hollow Concrete Block",
            "cost_index":      1,
            "durability_index": 4,
            "tags":            ["budget", "large"],
            "blurb":           (
                "Budget-friendly partition option. Hollow core reduces "
                "dead load while maintaining adequate lateral stability."
            )
        },
        {
            "material":        "Gypsum Board (Drywall)",
            "cost_index":      1,
            "durability_index": 2,
            "tags":            ["small", "many_rooms"],
            "blurb":           (
                "Fastest, cheapest partition for non-load-bearing "
                "interior divisions. Fire-rated variants available. "
                "Not suitable for wet areas."
            )
        },
        {
            "material":        "Brick (Half-Brick / 115 mm)",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["durable"],
            "blurb":           (
                "Traditional interior partition with excellent sound "
                "insulation and durability. Heavier than AAC; "
                "recommended where acoustic privacy is critical."
            )
        },
    ],

    # ── Floor slab ──────────────────────────────────────────────
    "floor_slab": [
        {
            "material":        "Reinforced Cement Concrete (RCC) Slab",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["all"],
            "blurb":           (
                "Standard M20-M25 grade RCC; 50-100+ year service life, "
                "supports 1.5-2 kN/m² live load easily. "
                "Monolithic pour gives integral strength."
            )
        },
        {
            "material":        "Precast Hollow-Core Plank",
            "cost_index":      3,
            "durability_index": 5,
            "tags":            ["large", "fast"],
            "blurb":           (
                "Factory-controlled quality, crane-installed in hours. "
                "Reduces self-weight by 30% vs solid slab; ideal for "
                "large-span rooms."
            )
        },
        {
            "material":        "Composite Deck (Steel + Concrete)",
            "cost_index":      3,
            "durability_index": 5,
            "tags":            ["multi-storey"],
            "blurb":           (
                "Profiled steel deck acts as formwork and tensile "
                "reinforcement; very fast construction for upper floors."
            )
        },
    ],

    # ── Roof ────────────────────────────────────────────────────
    "roof": [
        {
            "material":        "RCC Flat Roof (M25)",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["all"],
            "blurb":           (
                "Robust, allows future vertical extension. "
                "Apply waterproof membrane (polyurethane or bitumen) "
                "for leak prevention. 40+ year lifespan."
            )
        },
        {
            "material":        "Clay Roof Tiles on Timber Rafters",
            "cost_index":      2,
            "durability_index": 4,
            "tags":            ["pitched", "residential"],
            "blurb":           (
                "Attractive pitched roof option; natural thermal mass. "
                "50-100 year tile lifespan. Not suitable if future "
                "storey addition is planned."
            )
        },
        {
            "material":        "Metal Deck Roofing (Galvalume)",
            "cost_index":      1,
            "durability_index": 3,
            "tags":            ["budget", "fast"],
            "blurb":           (
                "Lightest, fastest roof option. 25-30 year lifespan "
                "with good anti-corrosion coating. Best for workshops, "
                "garages, or low-cost residential."
            )
        },
    ],

    # ── Foundation ──────────────────────────────────────────────
    "foundation": [
        {
            "material":        "Strip Foundation (M20 PCC + RCC)",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["all"],
            "blurb":           (
                "Standard for load-bearing wall buildings on stable "
                "soil. 600 mm wide × 300 mm deep typically; "
                "economical and proven."
            )
        },
        {
            "material":        "Isolated Footing (Column Footings)",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["large", "frame"],
            "blurb":           (
                "Used with RCC column-frame construction. "
                "Each column gets an independent pad footing; "
                "efficient material usage."
            )
        },
        {
            "material":        "Raft Foundation",
            "cost_index":      3,
            "durability_index": 5,
            "tags":            ["weak_soil", "large"],
            "blurb":           (
                "A single continuous slab distributes load across the "
                "entire footprint. Required on soft/expansive soils "
                "or where differential settlement is a concern."
            )
        },
    ],

    # ── Thermal & waterproofing ──────────────────────────────────
    "waterproofing": [
        {
            "material":        "Polyurethane (PU) Liquid Membrane",
            "cost_index":      2,
            "durability_index": 5,
            "tags":            ["flat_roof", "wet_areas"],
            "blurb":           (
                "Seamless application over any shape; 10-15 year service "
                "life. UV stable. Apply 1.5-2 mm DFT. "
                "Best for flat RCC roofs and wet rooms."
            )
        },
        {
            "material":        "APP Bituminous Membrane (Torch-on)",
            "cost_index":      1,
            "durability_index": 4,
            "tags":            ["budget", "roof"],
            "blurb":           (
                "Two-layer torch-applied bitumen; 4 mm total. "
                "Cost-effective for large roof areas. "
                "Requires qualified applicator."
            )
        },
    ],
}

# ─────────────────────────────────────────────────────────────────
# SELECTION LOGIC
# ─────────────────────────────────────────────────────────────────

def trade_off_score(mat: dict) -> float:
    """Higher score = better durability for the cost."""
    return mat["durability_index"] * 2 - mat["cost_index"]


def classify_building(metrics: dict) -> set:
    """Return a set of descriptive tags based on building metrics."""
    tags = {"all"}
    area = metrics.get("floor_area", 50)
    ratio = metrics.get("aspect_ratio", 1.2)
    rooms = metrics.get("room_count", 4)

    if area < 30:
        tags.add("small")
    elif area < 70:
        tags.add("medium")
    else:
        tags.add("large")

    if rooms > 6:
        tags.add("many_rooms")

    if ratio > 1.8:
        tags.add("elongated")

    return tags


def best_material(candidates: list, building_tags: set) -> dict:
    """
    From the candidate list, prefer materials whose tags overlap with
    building_tags.  Break ties by trade_off_score.
    """
    def relevance(mat):
        overlap = len(set(mat.get("tags", [])) & building_tags)
        return (overlap, trade_off_score(mat))

    return max(candidates, key=relevance)


def recommend(parsed: dict) -> dict:
    metrics       = parsed.get("metrics", {})
    structure     = parsed.get("structure", {})
    room_count    = structure.get("room_count", 3)

    # Inject room_count into metrics for classify_building
    metrics["room_count"] = room_count
    building_tags = classify_building(metrics)

    selected = {}
    for component, candidates in MATERIALS.items():
        selected[component] = best_material(candidates, building_tags)

    # ── Build output list ────────────────────────────────────────
    materials_out = []
    for comp_key, mat in selected.items():
        materials_out.append({
            "type":             comp_key,
            "material":         mat["material"],
            "cost_index":       mat["cost_index"],
            "durability_index": mat["durability_index"],
            "reason":           mat["blurb"]
        })

    # ── Human-readable explanation ───────────────────────────────
    area       = metrics.get("floor_area", "N/A")
    perimeter  = metrics.get("outer_wall_perimeter", "N/A")
    inner_len  = metrics.get("inner_wall_length", "N/A")
    ratio      = metrics.get("aspect_ratio", "N/A")

    cost_labels = {1: "Low", 2: "Medium", 3: "High"}
    dur_labels  = {1: "Poor", 2: "Fair", 3: "Good", 4: "Very Good", 5: "Excellent"}

    lines = [
        "BUILDING ANALYSIS SUMMARY",
        "=" * 45,
        f"  Floor area          : {area} normalised units²",
        f"  Outer wall perimeter: {perimeter} normalised units",
        f"  Interior wall length: {inner_len} normalised units",
        f"  Aspect ratio        : {ratio}",
        f"  Detected rooms      : {room_count}",
        f"  Building profile    : {', '.join(sorted(building_tags - {'all'}))}",
        "",
        "MATERIAL RECOMMENDATIONS (Cost vs Durability Trade-off)",
        "=" * 45,
    ]

    for mat_info in materials_out:
        comp = mat_info["type"].replace("_", " ").title()
        name = mat_info["material"]
        cost = cost_labels.get(mat_info["cost_index"], "?")
        dur  = dur_labels.get(mat_info["durability_index"], "?")
        score = mat_info["durability_index"] * 2 - mat_info["cost_index"]
        lines.append(f"\n▸ {comp}: {name}")
        lines.append(f"  Cost: {cost}  |  Durability: {dur}  |  Trade-off score: {score}/9")
        lines.append(f"  {mat_info['reason']}")

    lines += [
        "",
        "SELECTION METHODOLOGY",
        "=" * 45,
        "Materials were scored using:  score = (durability × 2) − cost",
        "This formula prioritises long-term structural integrity while",
        "penalising excessive upfront expense. Materials matching the",
        "detected building profile (size, room density, aspect ratio)",
        "are ranked higher than equally scored generic options.",
    ]

    explanation = "\n".join(lines)

    return {
        "materials":   materials_out,
        "explanation": explanation
    }


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    try:
        parsed = json.loads(raw)
        result = recommend(parsed)
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "materials": [], "explanation": ""}))
        sys.exit(1)
