import argparse
import os
from datetime import date, timedelta
from typing import Dict, List

from utils import (
    ensure_dir,
    format_distance,
    format_duration,
    format_elevation,
    load_config,
    read_json,
    utc_now,
    write_json,
)

AGG_PATH = os.path.join("data", "daily_aggregates.json")
README_PATH = "README.md"
SITE_DATA_PATH = os.path.join("site", "data.json")

CELL = 12
GAP = 2
PADDING = 16
LABEL_LEFT = 36
LABEL_TOP = 20

DEFAULT_COLORS = ["#1f2937", "#334155", "#475569", "#64748b", "#94a3b8"]
TYPE_COLORS = {
    "Run": ["#1f2937", "#334155", "#38bdf8", "#0ea5e9", "#01cdfe"],
    "Ride": ["#1f2937", "#334155", "#34d399", "#10b981", "#05ffa1"],
    "WeightTraining": ["#1f2937", "#334155", "#f472b6", "#ec4899", "#ff71ce"],
}

LABEL_COLOR = "#cbd5e1"
TEXT_COLOR = "#e5e7eb"
BG_COLOR = "#0f172a"
STROKE_COLOR = "#0f172a"


# ──────────────────────────── helpers ────────────────────────────

def _year_range_from_config(config: Dict) -> List[int]:
    sync_cfg = config.get("sync", {})
    current_year = utc_now().year
    start_date = sync_cfg.get("start_date")
    if start_date:
        try:
            start_year = int(start_date.split("-")[0])
        except (ValueError, IndexError):
            start_year = current_year
    else:
        lookback_years = int(sync_cfg.get("lookback_years", 5))
        start_year = current_year - lookback_years + 1
    return list(range(start_year, current_year + 1))


def _monday_on_or_before(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _sunday_on_or_after(d: date) -> date:
    return d + timedelta(days=(6 - d.weekday()))


def _daily_speed(entry: Dict) -> float:
    distance = float(entry.get("distance", 0.0))
    moving_time = float(entry.get("moving_time", 0.0))
    if distance <= 0 or moving_time <= 0:
        return 0.0
    return distance / (moving_time / 3600.0)


def _percentiles(values: List[float]) -> List[float]:
    if not values:
        return [0, 0, 0, 0]
    values = sorted(values)
    n = len(values)
    return [
        values[int(n * 0.2)],
        values[int(n * 0.4)],
        values[int(n * 0.6)],
        values[int(n * 0.8)],
    ]


def _speed_level(speed: float, cuts: List[float]) -> int:
    if speed <= 0:
        return 0
    for i, c in enumerate(cuts):
        if speed < c:
            return i
    return 4


def _build_title(date_str: str, entry: Dict, units: Dict[str, str]) -> str:
    count = entry.get("count", 0)
    distance = format_distance(entry.get("distance", 0.0), units["distance"])
    duration = format_duration(entry.get("moving_time", 0.0))
    elevation = format_elevation(entry.get("elevation_gain", 0.0), units["elevation"])
    speed = _daily_speed(entry)

    return (
        f"{date_str}\n"
        f"{count} workout{'s' if count != 1 else ''}\n"
        f"Distance: {distance}\n"
        f"Duration: {duration}\n"
        f"Avg speed: {speed:.1f} {units['distance']}/h\n"
        f"Elevation: {elevation}"
    )


# ──────────────────────────── SVG ────────────────────────────

def _svg_for_year(
    activity_type: str,
    year: int,
    entries: Dict[str, Dict],
    units: Dict[str, str],
) -> str:
    start = _monday_on_or_before(date(year, 1, 1))
    end = _sunday_on_or_after(date(year, 12, 31))

    weeks = ((end - start).days // 7) + 1
    width = weeks * (CELL + GAP) + PADDING * 2 + LABEL_LEFT
    height = 7 * (CELL + GAP) + PADDING * 2 + LABEL_TOP

    grid_x = PADDING + LABEL_LEFT
    grid_y = PADDING + LABEL_TOP

    colors = TYPE_COLORS.get(activity_type, DEFAULT_COLORS)

    # compute yearly speed distribution
    speeds = [
        _daily_speed(e)
        for e in entries.values()
        if _daily_speed(e) > 0
    ]
    cuts = _percentiles(speeds)

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    )
    lines.append(f'<rect width="{width}" height="{height}" fill="{BG_COLOR}"/>')
    lines.append(
        f'<text x="{PADDING}" y="{PADDING + 12}" font-size="12" fill="{TEXT_COLOR}" font-family="Arial, sans-serif">{year}</text>'
    )

    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for month in range(1, 13):
        first_day = date(year, month, 1)
        week_index = (first_day - start).days // 7
        x = grid_x + week_index * (CELL + GAP)
        lines.append(
            f'<text x="{x}" y="{PADDING + 12}" font-size="10" fill="{LABEL_COLOR}" font-family="Arial, sans-serif">{month_labels[month-1]}</text>'
        )

    day_labels = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    for row, label in enumerate(day_labels):
        y = grid_y + row * (CELL + GAP) + CELL - 2
        x = PADDING + LABEL_LEFT - 6
        lines.append(
            f'<text x="{x}" y="{y}" font-size="9" fill="{LABEL_COLOR}" font-family="Arial, sans-serif" text-anchor="end">{label}</text>'
        )

    lines.append(f'<g transform="translate({grid_x},{grid_y})">')

    current = start
    while current <= end:
        week_index = (current - start).days // 7
        row = current.weekday()
        x = week_index * (CELL + GAP)
        y = row * (CELL + GAP)

        date_str = current.isoformat()
        entry = entries.get(date_str)
        if current.year == year and entry:
            speed = _daily_speed(entry)
            level = _speed_level(speed, cuts)
            color = colors[level]
            title = _build_title(date_str, entry, units)
        else:
            color = BG_COLOR
            title = None

        rect = (
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" '
            f'fill="{color}" stroke="{STROKE_COLOR}" stroke-width="1"/>'
        )
        if title:
            rect = rect[:-2] + f'><title>{title}</title></rect>'

        lines.append(rect)
        current += timedelta(days=1)

    lines.append("</g></svg>")
    return "\n".join(lines) + "\n"


# ──────────────────────────── orchestration ────────────────────────────

def generate():
    config = load_config()
    types = config.get("activities", {}).get("types", []) or []

    units_cfg = config.get("units", {})
    units = {
        "distance": units_cfg.get("distance", "mi"),
        "elevation": units_cfg.get("elevation", "ft"),
    }

    aggregates = read_json(AGG_PATH)
    years = _year_range_from_config(config)

    for activity_type in types:
        out_dir = os.path.join("heatmaps", activity_type)
        ensure_dir(out_dir)
        for year in years:
            entries = (
                aggregates.get("years", {})
                .get(str(year), {})
                .get(activity_type, {})
            )
            svg = _svg_for_year(activity_type, year, entries, units)
            with open(os.path.join(out_dir, f"{year}.svg"), "w", encoding="utf-8") as f:
                f.write(svg)

    write_json(
        SITE_DATA_PATH,
        {
            "generated_at": utc_now().isoformat(),
            "years": years,
            "types": types,
            "aggregates": aggregates.get("years", {}),
            "units": units,
        },
    )


def main() -> int:
    generate()
    print("Generated heatmaps with percentile-based intensity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
