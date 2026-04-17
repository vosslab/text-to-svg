#!/usr/bin/env python3
"""
Score the validation sweep and emit output_sweep/REPORT.md.

Uses property-based evaluation, not snapshot testing. For each cell:
  - Contract metrics: parse success, fallback flag, wall time.
  - Structural heuristics: leaf count, unique types, fill/stroke ratios.
  - Prompt-specific checks from prompts.yaml in three tiers:
      required (70%) + preferred (30%) - anti_penalty

Usage:
	source source_me.sh && python3 tests/validation/score_sweep.py
"""

# Standard Library
import json
import math
import pathlib
import statistics

# PIP3 modules
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output_sweep"
REPORT_FILE = OUTPUT_ROOT / "REPORT.md"
ADHERENCE_FILE = REPO_ROOT / "tests" / "validation" / "ADHERENCE.md"
PROMPTS_FILE = REPO_ROOT / "tests" / "validation" / "prompts.yaml"

# Weights for the scoring formula: 0.7 required + 0.3 preferred - anti_penalty
REQUIRED_WEIGHT = 0.7
PREFERRED_WEIGHT = 0.3
ANTI_PENALTY_PER_HIT = 0.1
ANTI_PENALTY_CAP = 0.3

WARM_FAMILIES = {"red", "orange", "yellow"}
COOL_FAMILIES = {"blue", "green", "cool", "teal", "cyan"}


# ============================================
# Color utilities
# ============================================
def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
	# accept #rgb and #rrggbb; return None on any other shape
	hex_part = value.strip().lstrip("#")
	if len(hex_part) == 3:
		hex_part = "".join(ch * 2 for ch in hex_part)
	if len(hex_part) != 6:
		return None
	try:
		return int(hex_part[0:2], 16), int(hex_part[2:4], 16), int(hex_part[4:6], 16)
	except ValueError:
		return None


def _hex_to_family(value: str) -> str:
	rgb = _hex_to_rgb(value)
	if rgb is None:
		return "unknown"
	r, g, b = rgb
	# grayscale band
	if abs(r - g) < 14 and abs(g - b) < 14 and abs(r - b) < 14:
		return "mono"
	if r >= g and r >= b and r - max(g, b) > 30:
		if g > b + 30 and g > 120:
			return "orange"
		return "red"
	if g >= r and g >= b and g - max(r, b) > 20:
		return "green"
	if b >= r and b >= g and b - max(r, g) > 20:
		return "blue"
	if r > 200 and g > 180 and b < 140:
		return "yellow"
	return "mixed"


def _brightness(rgb: tuple[int, int, int]) -> float:
	# perceived brightness (ITU-R BT.601)
	r, g, b = rgb
	return 0.299 * r + 0.587 * g + 0.114 * b


# ============================================
# Shape iteration and heuristics
# ============================================
def _iter_leaf_shapes(shapes: list) -> list[dict]:
	out: list[dict] = []
	for shape in shapes:
		if not isinstance(shape, dict):
			continue
		if shape.get("type") == "group":
			out.extend(_iter_leaf_shapes(shape.get("shapes", [])))
		else:
			out.append(shape)
	return out


def _shapes_of_type(cell: dict, shape_type: str) -> list:
	return [s for s in _iter_leaf_shapes(cell["scene"].get("shapes", [])) if s.get("type") == shape_type]


def _shape_center(shape: dict) -> tuple[float, float] | None:
	t = shape.get("type")
	if t in {"circle", "ellipse", "star"}:
		cx, cy = shape.get("cx"), shape.get("cy")
		if isinstance(cx, (int, float)) and isinstance(cy, (int, float)):
			return float(cx), float(cy)
	if t == "rect":
		x, y, w, h = shape.get("x"), shape.get("y"), shape.get("width"), shape.get("height")
		if all(isinstance(v, (int, float)) for v in (x, y, w, h)):
			return float(x) + float(w) / 2, float(y) + float(h) / 2
	if t == "line":
		x1, y1, x2, y2 = shape.get("x1"), shape.get("y1"), shape.get("x2"), shape.get("y2")
		if all(isinstance(v, (int, float)) for v in (x1, y1, x2, y2)):
			return (float(x1) + float(x2)) / 2, (float(y1) + float(y2)) / 2
	if t in {"polygon", "polyline"}:
		pts = shape.get("points") or []
		xs = [p[0] for p in pts if isinstance(p, list) and len(p) >= 2]
		ys = [p[1] for p in pts if isinstance(p, list) and len(p) >= 2]
		if xs and ys:
			return sum(xs) / len(xs), sum(ys) / len(ys)
	return None


def _shape_bbox(shape: dict) -> tuple[float, float, float, float] | None:
	# axis-aligned bbox (xmin, ymin, xmax, ymax), None if indeterminate
	t = shape.get("type")
	if t == "circle":
		cx, cy, r = shape.get("cx"), shape.get("cy"), shape.get("r")
		if all(isinstance(v, (int, float)) for v in (cx, cy, r)):
			return float(cx) - float(r), float(cy) - float(r), float(cx) + float(r), float(cy) + float(r)
	if t == "ellipse":
		cx, cy, rx, ry = shape.get("cx"), shape.get("cy"), shape.get("rx"), shape.get("ry")
		if all(isinstance(v, (int, float)) for v in (cx, cy, rx, ry)):
			return float(cx) - float(rx), float(cy) - float(ry), float(cx) + float(rx), float(cy) + float(ry)
	if t == "rect":
		x, y, w, h = shape.get("x"), shape.get("y"), shape.get("width"), shape.get("height")
		if all(isinstance(v, (int, float)) for v in (x, y, w, h)):
			return float(x), float(y), float(x) + float(w), float(y) + float(h)
	if t == "star":
		cx, cy, rr = shape.get("cx"), shape.get("cy"), shape.get("outerRadius")
		if all(isinstance(v, (int, float)) for v in (cx, cy, rr)):
			return float(cx) - float(rr), float(cy) - float(rr), float(cx) + float(rr), float(cy) + float(rr)
	if t in {"polygon", "polyline"}:
		pts = shape.get("points") or []
		xs = [p[0] for p in pts if isinstance(p, list) and len(p) >= 2]
		ys = [p[1] for p in pts if isinstance(p, list) and len(p) >= 2]
		if xs and ys:
			return min(xs), min(ys), max(xs), max(ys)
	return None


def _is_background_shape(shape: dict, canvas_w: int, canvas_h: int) -> bool:
	# Treat a shape as "background" if it is a large unstroked rect that
	# covers most of the canvas. Such shapes should not dominate color voting
	# since they only set the backdrop, not the subject.
	if shape.get("type") != "rect":
		return False
	if shape.get("stroke") and shape.get("stroke") != "none":
		return False
	w = shape.get("width") or 0
	h = shape.get("height") or 0
	if not (isinstance(w, (int, float)) and isinstance(h, (int, float))):
		return False
	canvas_area = canvas_w * canvas_h
	if canvas_area <= 0:
		return False
	coverage = (float(w) * float(h)) / canvas_area
	return coverage >= 0.7


def compute_heuristics(scene: dict) -> dict:
	leaves = _iter_leaf_shapes(scene.get("shapes", []))
	leaf_count = len(leaves)
	types = [s.get("type") for s in leaves if s.get("type")]
	unique_types = sorted(set(types))
	filled = sum(1 for s in leaves if s.get("fill") and s.get("fill") != "none")
	stroked = sum(1 for s in leaves if s.get("stroke") and s.get("stroke") != "none")
	# collect color families, but skip background-like rects so they don't
	# dilute the dominant hue of the subject
	canvas = scene.get("canvas", {})
	canvas_w = canvas.get("width", 800)
	canvas_h = canvas.get("height", 800)
	hex_colors: list[str] = []
	for s in leaves:
		if _is_background_shape(s, canvas_w, canvas_h):
			continue
		for key in ("fill", "stroke"):
			v = s.get(key)
			if isinstance(v, str) and v.startswith("#"):
				hex_colors.append(v)
	family_counts: dict[str, int] = {}
	for c in hex_colors:
		fam = _hex_to_family(c)
		family_counts[fam] = family_counts.get(fam, 0) + 1
	dominant = max(family_counts, key=family_counts.get) if family_counts else "none"
	# brightness over meaningful (non-transparent) colors
	brightnesses = []
	for c in hex_colors:
		rgb = _hex_to_rgb(c)
		if rgb is not None:
			brightnesses.append(_brightness(rgb))
	mean_brightness = statistics.mean(brightnesses) if brightnesses else 0.0
	heuristics = {
		"leafCount": leaf_count,
		"uniqueTypes": unique_types,
		"distinctTypeCount": len(unique_types),
		"fillRatio": round(filled / leaf_count, 3) if leaf_count else 0.0,
		"strokeRatio": round(stroked / leaf_count, 3) if leaf_count else 0.0,
		"colorFamilies": family_counts,
		"dominantFamily": dominant,
		"distinctColors": len(set(hex_colors)),
		"meanBrightness": round(mean_brightness, 1),
	}
	return heuristics


# ============================================
# Check handlers
# ============================================
def _check_not_fallback(cell, r):
	return not cell["meta"]["usedFallback"]


def _check_shape_count(cell, r):
	return len(_shapes_of_type(cell, r["type"])) == r["count"]


def _check_min_shape_count(cell, r):
	return cell["heuristics"]["leafCount"] >= r["count"]


def _check_max_shape_count(cell, r):
	return cell["heuristics"]["leafCount"] <= r["count"]


def _check_has_shape_type(cell, r):
	return r["type"] in cell["heuristics"]["uniqueTypes"]


def _check_has_any_shape_type(cell, r):
	return bool(set(r["types"]) & set(cell["heuristics"]["uniqueTypes"]))


def _check_distinct_types(cell, r):
	return cell["heuristics"]["distinctTypeCount"] >= r["count"]


def _check_equal_radius(cell, r):
	shapes = _shapes_of_type(cell, r.get("type", "circle"))
	if len(shapes) < 2:
		return False
	radii = [s.get("r") for s in shapes if isinstance(s.get("r"), (int, float))]
	if len(radii) < 2:
		return False
	mean_r = statistics.mean(radii)
	if mean_r <= 0:
		return False
	tol = r.get("tolerance", 0.1)
	return all(abs(v - mean_r) / mean_r <= tol for v in radii)


def _check_similar_size(cell, r):
	# works for rect (w,h) and polygon/polyline (bbox); width is primary axis
	shapes = _shapes_of_type(cell, r.get("type", "rect"))
	if len(shapes) < 2:
		return False
	widths: list[float] = []
	heights: list[float] = []
	for s in shapes:
		if s.get("type") == "rect":
			if isinstance(s.get("width"), (int, float)) and isinstance(s.get("height"), (int, float)):
				widths.append(float(s["width"]))
				heights.append(float(s["height"]))
		else:
			bb = _shape_bbox(s)
			if bb is not None:
				widths.append(bb[2] - bb[0])
				heights.append(bb[3] - bb[1])
	if len(widths) < 2:
		return False
	tol = r.get("tolerance", 0.15)
	w_mean = statistics.mean(widths)
	h_mean = statistics.mean(heights)
	if w_mean <= 0 or h_mean <= 0:
		return False
	w_ok = all(abs(v - w_mean) / w_mean <= tol for v in widths)
	h_ok = all(abs(v - h_mean) / h_mean <= tol for v in heights)
	return w_ok and h_ok


def _check_distinct_centers(cell, r):
	shapes = _shapes_of_type(cell, r.get("type", "circle"))
	if len(shapes) < 2:
		return False
	centers = [_shape_center(s) for s in shapes]
	centers = [c for c in centers if c is not None]
	if len(centers) < 2:
		return False
	# min distance must exceed min_distance_factor * median size cue
	radii = [s.get("r") for s in shapes if isinstance(s.get("r"), (int, float))]
	unit = statistics.median(radii) if radii else 10.0
	floor = unit * r.get("min_distance_factor", 0.5)
	for i, a in enumerate(centers):
		for b in centers[i + 1:]:
			d = math.hypot(a[0] - b[0], a[1] - b[1])
			if d < floor:
				return False
	return True


def _check_centered_shape(cell, r):
	canvas = cell["scene"].get("canvas", {})
	w, h = canvas.get("width", 800), canvas.get("height", 800)
	shapes = _shapes_of_type(cell, r["type"])
	if not shapes:
		return False
	# if multiple, pick the largest
	def _size(s):
		bb = _shape_bbox(s)
		return (bb[2] - bb[0]) * (bb[3] - bb[1]) if bb else 0
	biggest = max(shapes, key=_size)
	center = _shape_center(biggest)
	if center is None:
		return False
	tol = r.get("tolerance", 0.2)
	dx = abs(center[0] - w / 2) / w
	dy = abs(center[1] - h / 2) / h
	return dx <= tol and dy <= tol


def _check_centered_composition(cell, r):
	# centroid of all leaf shape centers near canvas center
	leaves = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	centers = [_shape_center(s) for s in leaves]
	centers = [c for c in centers if c is not None]
	if not centers:
		return False
	cx = sum(c[0] for c in centers) / len(centers)
	cy = sum(c[1] for c in centers) / len(centers)
	canvas = cell["scene"].get("canvas", {})
	w, h = canvas.get("width", 800), canvas.get("height", 800)
	tol = r.get("tolerance", 0.2)
	return abs(cx - w / 2) / w <= tol and abs(cy - h / 2) / h <= tol


def _check_horizontal_alignment(cell, r):
	# y-centers of target shapes cluster within a single band
	shapes = _shapes_of_type(cell, r.get("type", "rect"))
	if len(shapes) < 2:
		return False
	centers = [_shape_center(s) for s in shapes]
	centers = [c for c in centers if c is not None]
	if len(centers) < 2:
		return False
	ys = [c[1] for c in centers]
	canvas_h = cell["scene"].get("canvas", {}).get("height", 800)
	tol = r.get("tolerance", 0.12)
	return (max(ys) - min(ys)) <= canvas_h * tol


def _check_equal_x_spacing(cell, r):
	shapes = _shapes_of_type(cell, r.get("type", "rect"))
	if len(shapes) < 3:
		return len(shapes) >= 2
	centers = [_shape_center(s) for s in shapes]
	centers = [c for c in centers if c is not None]
	if len(centers) < 3:
		return False
	xs = sorted(c[0] for c in centers)
	gaps = [b - a for a, b in zip(xs, xs[1:])]
	mean_gap = statistics.mean(gaps)
	if mean_gap <= 0:
		return False
	tol = r.get("tolerance", 0.25)
	return all(abs(g - mean_gap) / mean_gap <= tol for g in gaps)


def _check_two_row_layout(cell, r):
	shapes = _shapes_of_type(cell, r.get("type", "circle"))
	if len(shapes) < 3:
		return False
	ys = [c[1] for c in (_shape_center(s) for s in shapes) if c is not None]
	if len(ys) < 3:
		return False
	canvas_h = cell["scene"].get("canvas", {}).get("height", 800)
	band = canvas_h * r.get("tolerance", 0.2)
	ys_sorted = sorted(ys)
	clusters = 1
	for a, b in zip(ys_sorted, ys_sorted[1:]):
		if b - a > band:
			clusters += 1
	return clusters == 2


def _check_bottom_weighted_composition(cell, r):
	canvas_h = cell["scene"].get("canvas", {}).get("height", 800)
	leaves = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	centers = [_shape_center(s) for s in leaves]
	ys = [c[1] for c in centers if c is not None]
	if not ys:
		return False
	in_lower_half = sum(1 for y in ys if y > canvas_h / 2)
	return in_lower_half / len(ys) >= r.get("min_fraction", 0.4)


def _check_canvas_width_usage(cell, r):
	canvas_w = cell["scene"].get("canvas", {}).get("width", 800)
	leaves = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	xs_left: list[float] = []
	xs_right: list[float] = []
	for s in leaves:
		bb = _shape_bbox(s)
		if bb is not None:
			xs_left.append(bb[0])
			xs_right.append(bb[2])
	if not xs_left:
		return False
	span = max(xs_right) - min(xs_left)
	return span / canvas_w >= r.get("min_fraction", 0.5)


def _check_radial_layout_present(cell, r):
	# at least min_count shapes whose centers sit on roughly one circle
	leaves = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	centers = [c for c in (_shape_center(s) for s in leaves) if c is not None]
	min_count = r.get("min_count", 4)
	if len(centers) < min_count:
		return False
	# centroid
	ccx = sum(c[0] for c in centers) / len(centers)
	ccy = sum(c[1] for c in centers) / len(centers)
	dists = [math.hypot(c[0] - ccx, c[1] - ccy) for c in centers]
	mean_d = statistics.mean(dists)
	if mean_d <= 0:
		return False
	# accept if at least min_count shapes are within 30% of the mean radius
	within = sum(1 for d in dists if abs(d - mean_d) / mean_d <= 0.3)
	return within >= min_count


def _check_fill_none_for_all(cell, r):
	shapes = _shapes_of_type(cell, r["type"])
	if not shapes:
		return False
	return all(s.get("fill", "none") == "none" for s in shapes)


def _check_dominant_color_family(cell, r):
	families = cell["heuristics"]["colorFamilies"]
	if not families:
		return False
	wanted = r["color"]
	if wanted == "warm":
		return any(fam in families for fam in WARM_FAMILIES)
	if wanted == "cool":
		return any(fam in families for fam in COOL_FAMILIES)
	return wanted == cell["heuristics"]["dominantFamily"] or wanted in families


def _check_palette_contains(cell, r):
	families = cell["heuristics"]["colorFamilies"]
	wanted = set(r["colors"])
	hits = sum(1 for fam in wanted if fam in families)
	return hits >= r.get("min_matches", 2)


def _check_dark_palette_bias(cell, r):
	return cell["heuristics"]["meanBrightness"] <= r.get("max_brightness", 120)


def _check_outline_only_bias(cell, r):
	# stroke dominates fill
	return cell["heuristics"]["strokeRatio"] > cell["heuristics"]["fillRatio"]


def _check_all_strokes_non_null(cell, r):
	# every shape of the requested type must have a real hex stroke, not
	# None/null and not the literal "none". This catches the common failure
	# where a model emits structurally correct shapes with no color binding.
	shapes = _shapes_of_type(cell, r["type"])
	if not shapes:
		return False
	for shape in shapes:
		stroke = shape.get("stroke")
		if not isinstance(stroke, str):
			return False
		if stroke.strip().lower() == "none":
			return False
	return True


def _check_stroke_colors_distinct(cell, r):
	# count the number of distinct stroke color values on a shape type;
	# lets us score prompts like "olympic rings in five different colors"
	shape_type = r.get("type")
	if shape_type:
		shapes = _shapes_of_type(cell, shape_type)
	else:
		shapes = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	colors: set[str] = set()
	for shape in shapes:
		stroke = shape.get("stroke")
		if isinstance(stroke, str) and stroke.startswith("#"):
			colors.add(stroke.strip().lower())
	return len(colors) >= r.get("min", 2)


# ---- anti-checks (return True when the penalty should FIRE) ----
def _anti_text_elements_present(cell, r):
	# the JSON scene has no text type, so this looks at the raw reply as
	# a soft signal for models that tried to embed literal <text> markup
	raw_output = cell.get("raw_text", "")
	return "<text" in raw_output.lower()


def _anti_extra_shapes_over(cell, r):
	return cell["heuristics"]["leafCount"] > r.get("max_allowed", 5)


def _anti_mostly_empty_canvas(cell, r):
	canvas = cell["scene"].get("canvas", {})
	cw, ch = canvas.get("width", 800), canvas.get("height", 800)
	total_area = cw * ch
	if total_area <= 0:
		return True
	leaves = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	covered = 0.0
	for s in leaves:
		bb = _shape_bbox(s)
		if bb is None:
			continue
		covered += max(0, bb[2] - bb[0]) * max(0, bb[3] - bb[1])
	fraction = min(covered / total_area, 1.0)
	return fraction < r.get("max_fraction", 0.08)


def _anti_single_shape_only(cell, r):
	return cell["heuristics"]["leafCount"] <= 1


def _anti_dominant_cool_colors(cell, r):
	families = cell["heuristics"]["colorFamilies"]
	cool = sum(families.get(f, 0) for f in COOL_FAMILIES)
	warm = sum(families.get(f, 0) for f in WARM_FAMILIES)
	return cool > warm and cool > 0


def _anti_has_null_strokes(cell, r):
	# fires when ANY leaf shape has stroke in {None, "none"} — signal that
	# the model emitted geometry without binding colors to it
	leaves = _iter_leaf_shapes(cell["scene"].get("shapes", []))
	for shape in leaves:
		stroke = shape.get("stroke")
		if stroke is None:
			return True
		if isinstance(stroke, str) and stroke.strip().lower() == "none":
			# only count as "null" when the shape has no fill either
			fill = shape.get("fill", "none")
			if isinstance(fill, str) and fill.strip().lower() == "none":
				return True
	return False


RULE_HANDLERS = {
	"not_fallback": _check_not_fallback,
	"shape_count": _check_shape_count,
	"min_shape_count": _check_min_shape_count,
	"max_shape_count": _check_max_shape_count,
	"has_shape_type": _check_has_shape_type,
	"has_any_shape_type": _check_has_any_shape_type,
	"distinct_types": _check_distinct_types,
	"equal_radius": _check_equal_radius,
	"similar_size": _check_similar_size,
	"distinct_centers": _check_distinct_centers,
	"centered_shape": _check_centered_shape,
	"centered_composition": _check_centered_composition,
	"horizontal_alignment": _check_horizontal_alignment,
	"equal_x_spacing": _check_equal_x_spacing,
	"two_row_layout": _check_two_row_layout,
	"bottom_weighted_composition": _check_bottom_weighted_composition,
	"canvas_width_usage": _check_canvas_width_usage,
	"radial_layout_present": _check_radial_layout_present,
	"fill_none_for_all": _check_fill_none_for_all,
	"dominant_color_family": _check_dominant_color_family,
	"palette_contains": _check_palette_contains,
	"dark_palette_bias": _check_dark_palette_bias,
	"outline_only_bias": _check_outline_only_bias,
	"all_strokes_non_null": _check_all_strokes_non_null,
	"stroke_colors_distinct": _check_stroke_colors_distinct,
}

ANTI_HANDLERS = {
	"text_elements_present": _anti_text_elements_present,
	"extra_shapes_over": _anti_extra_shapes_over,
	"mostly_empty_canvas": _anti_mostly_empty_canvas,
	"single_shape_only": _anti_single_shape_only,
	"dominant_cool_colors": _anti_dominant_cool_colors,
	"has_null_strokes": _anti_has_null_strokes,
}


# ============================================
def _run_checks(cell: dict, rules: list) -> tuple[int, int, list[str]]:
	passed = 0
	total = 0
	failures: list[str] = []
	for rule in rules:
		kind = rule["kind"]
		handler = RULE_HANDLERS.get(kind)
		if handler is None:
			failures.append(f"unknown:{kind}")
			continue
		total += 1
		if handler(cell, rule):
			passed += 1
		else:
			failures.append(kind)
	return passed, total, failures


def _run_anti_checks(cell: dict, rules: list) -> tuple[int, list[str]]:
	fired = 0
	fires: list[str] = []
	for rule in rules:
		kind = rule["kind"]
		handler = ANTI_HANDLERS.get(kind)
		if handler is None:
			continue
		if handler(cell, rule):
			fired += 1
			fires.append(kind)
	return fired, fires


# ============================================
def evaluate_cell(cell: dict, entry: dict) -> dict:
	req_pass, req_total, req_fail = _run_checks(cell, entry.get("required", []))
	pref_pass, pref_total, pref_fail = _run_checks(cell, entry.get("preferred", []))
	anti_fired, anti_fires = _run_anti_checks(cell, entry.get("anti", []))
	req_ratio = (req_pass / req_total) if req_total else 0.0
	pref_ratio = (pref_pass / pref_total) if pref_total else 0.0
	anti_penalty = min(anti_fired * ANTI_PENALTY_PER_HIT, ANTI_PENALTY_CAP)
	final = max(0.0, REQUIRED_WEIGHT * req_ratio + PREFERRED_WEIGHT * pref_ratio - anti_penalty)
	evaluation = {
		"required": {"passed": req_pass, "total": req_total, "ratio": round(req_ratio, 3), "failures": req_fail},
		"preferred": {"passed": pref_pass, "total": pref_total, "ratio": round(pref_ratio, 3), "failures": pref_fail},
		"anti": {"fired": anti_fired, "penalty": round(anti_penalty, 3), "fires": anti_fires},
		"finalScore": round(final, 3),
	}
	return evaluation


# ============================================
def _load_prompt_catalog() -> dict[str, dict]:
	data = yaml.safe_load(PROMPTS_FILE.read_text(encoding="utf-8"))
	prompts = data.get("prompts", [])
	return {entry["prompt"]: entry for entry in prompts}


def _load_adherence_scores() -> dict[tuple[str, str, str], int]:
	scores: dict[tuple[str, str, str], int] = {}
	if not ADHERENCE_FILE.exists():
		return scores
	for line in ADHERENCE_FILE.read_text(encoding="utf-8").splitlines():
		if not line.startswith("|"):
			continue
		cells = [c.strip() for c in line.strip().strip("|").split("|")]
		if len(cells) != 4:
			continue
		pipeline, model, prompt, score_text = cells
		if score_text in ("", "score", "---") or not score_text.isdigit():
			continue
		scores[(pipeline, model, prompt)] = int(score_text)
	return scores


# ============================================
def _walk_cells(catalog: dict) -> list[dict]:
	cells: list[dict] = []
	if not OUTPUT_ROOT.exists():
		return cells
	for meta_path in OUTPUT_ROOT.rglob("meta.json"):
		meta = json.loads(meta_path.read_text(encoding="utf-8"))
		scene_path = meta_path.parent / "scene.json"
		raw_path = meta_path.parent / "raw.txt"
		retry_path = meta_path.parent / "retry.txt"
		scene = json.loads(scene_path.read_text(encoding="utf-8")) if scene_path.exists() else {"shapes": []}
		raw_text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
		retry_text = retry_path.read_text(encoding="utf-8") if retry_path.exists() else ""
		heuristics = compute_heuristics(scene)
		entry = catalog.get(meta["prompt"])
		if entry is None:
			# cell predates the current catalog; skip rather than noise-score it
			continue
		cell = {
			"meta": meta,
			"scene": scene,
			"raw_text": raw_text + "\n" + retry_text,
			"heuristics": heuristics,
			"category": entry.get("category", []),
			"strictness": entry.get("strictness", "medium"),
			"_cell_dir": str(meta_path.parent.relative_to(OUTPUT_ROOT)),
		}
		cell["evaluation"] = evaluate_cell(cell, entry)
		cells.append(cell)
	return cells


# ============================================
def _group_by_model_pipeline(cells: list[dict]) -> dict[tuple[str, str], list[dict]]:
	groups: dict[tuple[str, str], list[dict]] = {}
	for cell in cells:
		key = (cell["meta"]["pipeline"], cell["meta"]["model"])
		groups.setdefault(key, []).append(cell)
	return groups


def _summary_row(pipeline: str, model: str, rows: list[dict], human: dict) -> dict:
	total = len(rows)
	fallbacks = sum(1 for r in rows if r["meta"]["usedFallback"])
	parse_ok = total - fallbacks
	shape_counts = [r["heuristics"]["leafCount"] for r in rows]
	wall_times = [r["meta"]["wallSeconds"] for r in rows]
	final_scores = [r["evaluation"]["finalScore"] for r in rows]
	required_ratios = [r["evaluation"]["required"]["ratio"] for r in rows]
	preferred_ratios = [r["evaluation"]["preferred"]["ratio"] for r in rows]
	anti_penalties = [r["evaluation"]["anti"]["penalty"] for r in rows]
	scored_human = [human.get((pipeline, model, r["meta"]["prompt"])) for r in rows]
	scored_human = [s for s in scored_human if s is not None]
	summary = {
		"pipeline": pipeline,
		"model": model,
		"cells": total,
		"parse_rate": round(parse_ok / total, 3) if total else 0.0,
		"fallback_rate": round(fallbacks / total, 3) if total else 0.0,
		"mean_shape_count": round(statistics.mean(shape_counts), 2) if shape_counts else 0.0,
		"mean_wall_seconds": round(statistics.mean(wall_times), 2) if wall_times else 0.0,
		"mean_required": round(statistics.mean(required_ratios), 3) if required_ratios else 0.0,
		"mean_preferred": round(statistics.mean(preferred_ratios), 3) if preferred_ratios else 0.0,
		"mean_anti_penalty": round(statistics.mean(anti_penalties), 3) if anti_penalties else 0.0,
		"mean_final": round(statistics.mean(final_scores), 3) if final_scores else 0.0,
		"human_cells": len(scored_human),
		"mean_human": round(statistics.mean(scored_human), 2) if scored_human else None,
	}
	return summary


# ============================================
def _render_summary_table(summaries: list[dict]) -> str:
	header = "| pipeline | model | cells | parse | fallback | req | pref | anti | final | shapes | sec | human |\n"
	sep = "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n"
	body = ""
	for s in sorted(summaries, key=lambda s: (s["model"], s["pipeline"])):
		human = f"{s['mean_human']}" if s["mean_human"] is not None else "-"
		body += (
			f"| {s['pipeline']} | {s['model']} | {s['cells']} | "
			f"{s['parse_rate']:.2f} | {s['fallback_rate']:.2f} | "
			f"{s['mean_required']:.2f} | {s['mean_preferred']:.2f} | {s['mean_anti_penalty']:.2f} | "
			f"**{s['mean_final']:.2f}** | {s['mean_shape_count']:.1f} | {s['mean_wall_seconds']:.1f} | {human} |\n"
		)
	return header + sep + body


def _primary_category(cell: dict) -> str:
	# first tag is the family; empty list falls back to "uncategorized"
	cats = cell.get("category") or []
	return cats[0] if cats else "uncategorized"


def _render_family_summary(cells: list[dict]) -> str:
	# aggregate final scores by (family, pipeline); shows where the product
	# actually wins or loses without one aggregate mean hiding the signal
	buckets: dict[tuple[str, str], list[dict]] = {}
	for cell in cells:
		key = (_primary_category(cell), cell["meta"]["pipeline"])
		buckets.setdefault(key, []).append(cell)
	header = "| family | pipeline | cells | req | pref | anti | final |\n"
	sep = "| --- | --- | ---: | ---: | ---: | ---: | ---: |\n"
	body = ""
	families = sorted({k[0] for k in buckets.keys()})
	for family in families:
		for pipeline in ("old", "new"):
			rows = buckets.get((family, pipeline), [])
			if not rows:
				continue
			req = statistics.mean(r["evaluation"]["required"]["ratio"] for r in rows)
			pref = statistics.mean(r["evaluation"]["preferred"]["ratio"] for r in rows)
			anti = statistics.mean(r["evaluation"]["anti"]["penalty"] for r in rows)
			final = statistics.mean(r["evaluation"]["finalScore"] for r in rows)
			body += (
				f"| {family} | {pipeline} | {len(rows)} | "
				f"{req:.2f} | {pref:.2f} | {anti:.2f} | **{final:.2f}** |\n"
			)
	return header + sep + body


def _render_prompt_rows(rows: list[dict]) -> str:
	out = "| pipeline | model | shapes | fallback | req | pref | anti | final | req fails | svg |\n"
	out += "| --- | --- | ---: | :---: | ---: | ---: | ---: | ---: | --- | --- |\n"
	for r in sorted(rows, key=lambda c: (c["meta"]["model"], c["meta"]["pipeline"])):
		svg_path = f"{r['_cell_dir']}/scene.svg"
		fb = "YES" if r["meta"]["usedFallback"] else "no"
		req_fail = ", ".join(r["evaluation"]["required"]["failures"][:3]) or "-"
		out += (
			f"| {r['meta']['pipeline']} | {r['meta']['model']} | "
			f"{r['heuristics']['leafCount']} | {fb} | "
			f"{r['evaluation']['required']['ratio']:.2f} | "
			f"{r['evaluation']['preferred']['ratio']:.2f} | "
			f"{r['evaluation']['anti']['penalty']:.2f} | "
			f"**{r['evaluation']['finalScore']:.2f}** | {req_fail} | [svg]({svg_path}) |\n"
		)
	return out


def _render_cell_gallery(cells: list[dict]) -> str:
	# group prompts by family, then render each prompt's cells
	by_family_prompt: dict[str, dict[str, list[dict]]] = {}
	for c in cells:
		family = _primary_category(c)
		by_family_prompt.setdefault(family, {}).setdefault(c["meta"]["prompt"], []).append(c)
	out = ""
	for family in sorted(by_family_prompt.keys()):
		out += f"\n## Family: {family}\n"
		for prompt in sorted(by_family_prompt[family].keys()):
			out += f"\n### {prompt}\n\n"
			out += _render_prompt_rows(by_family_prompt[family][prompt])
	return out


def _write_adherence_template(cells: list[dict]) -> None:
	if ADHERENCE_FILE.exists():
		return
	ADHERENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
	lines = [
		"# Human adherence scoring",
		"",
		"Score each cell 1-5 for how well the SVG matches the prompt.",
		"",
		"| pipeline | model | prompt | score |",
		"| --- | --- | --- | ---: |",
	]
	for c in sorted(cells, key=lambda c: (c["meta"]["prompt"], c["meta"]["model"], c["meta"]["pipeline"])):
		lines.append(f"| {c['meta']['pipeline']} | {c['meta']['model']} | {c['meta']['prompt']} |  |")
	ADHERENCE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================
def main() -> None:
	catalog = _load_prompt_catalog()
	cells = _walk_cells(catalog)
	if not cells:
		raise SystemExit(f"No cells found under {OUTPUT_ROOT}; run run_sweep.py first.")
	_write_adherence_template(cells)
	human = _load_adherence_scores()
	groups = _group_by_model_pipeline(cells)
	summaries = [_summary_row(p, m, rows, human) for (p, m), rows in groups.items()]
	table = _render_summary_table(summaries)
	gallery = _render_cell_gallery(cells)
	report = "# Validation sweep report\n\n"
	report += f"Cells scored: {len(cells)}; prompts in catalog: {len(catalog)}.\n\n"
	report += "Scoring: `final = 0.7 * required + 0.3 * preferred - anti_penalty` "
	report += "(anti cap 0.3). Required checks are must-haves; preferred are nice-to-haves; anti are penalties.\n\n"
	report += "## Per (pipeline, model)\n\n"
	report += table
	report += "\n## Per family (pipeline × family means)\n\n"
	report += "Family means separate minimal vs counted-repetition vs symbolic vs layout prompts "
	report += "so one aggregate score does not hide where the product actually wins.\n\n"
	report += _render_family_summary(cells)
	report += "\n## Per prompt (grouped by family)\n"
	report += gallery
	report += "\n"
	OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
	REPORT_FILE.write_text(report, encoding="utf-8")
	print(f"wrote {REPORT_FILE}")
	print(f"{len(cells)} cells across {len(groups)} (pipeline, model) groups")
	if not human:
		print(f"(no human scores yet; fill {ADHERENCE_FILE} to populate the human column)")


if __name__ == "__main__":
	main()
