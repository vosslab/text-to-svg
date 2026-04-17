"""
Shared scene contract and validation helpers.
"""

from dataclasses import dataclass, field
import json
import math
from typing import Any


DEFAULT_CANVAS_WIDTH = 800
DEFAULT_CANVAS_HEIGHT = 800
DEFAULT_VIEWBOX = [0.0, 0.0, 800.0, 800.0]
DEFAULT_STROKE_WIDTH = 2.0
MAX_SHAPES = 40
MIN_POINTS_FOR_STAR = 3


@dataclass(slots=True)
class Canvas:
	width: int = DEFAULT_CANVAS_WIDTH
	height: int = DEFAULT_CANVAS_HEIGHT
	viewBox: list[float] = field(default_factory=lambda: DEFAULT_VIEWBOX.copy())


@dataclass(slots=True)
class StyleEnvelope:
	mood: list[str] = field(default_factory=list)
	symmetry: str = "loose"
	density: str = "medium"
	palette: str = "mixed"
	seed: int = 1


@dataclass(slots=True)
class Shape:
	type: str
	fill: str | None = None
	stroke: str | None = None
	strokeWidth: float | None = None


@dataclass(slots=True)
class Circle(Shape):
	cx: float = 0.0
	cy: float = 0.0
	r: float = 0.0


@dataclass(slots=True)
class Rect(Shape):
	x: float = 0.0
	y: float = 0.0
	width: float = 0.0
	height: float = 0.0
	rx: float | None = None
	ry: float | None = None


@dataclass(slots=True)
class Ellipse(Shape):
	cx: float = 0.0
	cy: float = 0.0
	rx: float = 0.0
	ry: float = 0.0


@dataclass(slots=True)
class Line(Shape):
	x1: float = 0.0
	y1: float = 0.0
	x2: float = 0.0
	y2: float = 0.0


@dataclass(slots=True)
class Polygon(Shape):
	points: list[list[float]] = field(default_factory=list)


@dataclass(slots=True)
class Polyline(Shape):
	points: list[list[float]] = field(default_factory=list)


@dataclass(slots=True)
class Star(Shape):
	cx: float = 0.0
	cy: float = 0.0
	points: int = 5
	outerRadius: float = 0.0
	innerRadius: float = 0.0
	rotation: float = 0.0


@dataclass(slots=True)
class Group(Shape):
	shapes: list[dict[str, Any]] = field(default_factory=list)
	transform: str | None = None


@dataclass(slots=True)
class Scene:
	canvas: Canvas = field(default_factory=Canvas)
	style: StyleEnvelope = field(default_factory=StyleEnvelope)
	shapes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class GenerateSceneRequest:
	prompt: str
	seed: int = 1
	width: int = DEFAULT_CANVAS_WIDTH
	height: int = DEFAULT_CANVAS_HEIGHT
	model: str | None = None


@dataclass(slots=True)
class GenerateSceneResponse:
	scene: Scene
	normalizedFromModel: bool
	warnings: list[str] = field(default_factory=list)
	debug: dict[str, Any] = field(default_factory=dict)


_SHAPE_TYPES = {"circle", "rect", "ellipse", "line", "polygon", "polyline", "star", "group"}


def _coerce_number(value: Any, default: float) -> float:
	if isinstance(value, bool):
		return default
	if isinstance(value, (int, float)):
		return float(value)
	return default


def _clamp(value: float, low: float, high: float) -> float:
	return max(low, min(high, value))


def _normalize_color(value: Any, fallback: str | None) -> str | None:
	if not isinstance(value, str):
		return fallback
	normalized = value.strip()
	if not normalized:
		return fallback
	if normalized.startswith("#"):
		return normalized.lower()
	return normalized


def _normalize_points(value: Any) -> list[list[float]]:
	if not isinstance(value, list):
		return []
	normalized: list[list[float]] = []
	for item in value:
		if isinstance(item, list) and len(item) >= 2:
			x = _coerce_number(item[0], 0.0)
			y = _coerce_number(item[1], 0.0)
			normalized.append([x, y])
	return normalized


def _normalize_shape(item: Any, canvas: Canvas) -> dict[str, Any] | None:
	if not isinstance(item, dict):
		return None
	shape_type = item.get("type")
	if shape_type not in _SHAPE_TYPES:
		return None
	stroke_width = _coerce_number(item.get("strokeWidth"), DEFAULT_STROKE_WIDTH)
	stroke_width = _clamp(stroke_width, 0.0, 64.0)
	fill = _normalize_color(item.get("fill"), "none")
	stroke = _normalize_color(item.get("stroke"), None)
	if shape_type == "circle":
		r = _clamp(_coerce_number(item.get("r"), 0.0), 0.0, max(canvas.width, canvas.height))
		return {
			"type": "circle",
			"cx": _clamp(_coerce_number(item.get("cx"), canvas.width / 2), 0.0, canvas.width),
			"cy": _clamp(_coerce_number(item.get("cy"), canvas.height / 2), 0.0, canvas.height),
			"r": r,
			"fill": fill,
			"stroke": stroke,
			"strokeWidth": stroke_width,
		}
	if shape_type == "rect":
		return {
			"type": "rect",
			"x": _clamp(_coerce_number(item.get("x"), 0.0), -canvas.width, canvas.width),
			"y": _clamp(_coerce_number(item.get("y"), 0.0), -canvas.height, canvas.height),
			"width": _clamp(_coerce_number(item.get("width"), 0.0), 0.0, canvas.width),
			"height": _clamp(_coerce_number(item.get("height"), 0.0), 0.0, canvas.height),
			"rx": _clamp(_coerce_number(item.get("rx"), 0.0), 0.0, canvas.width),
			"ry": _clamp(_coerce_number(item.get("ry"), 0.0), 0.0, canvas.height),
			"fill": fill,
			"stroke": stroke,
			"strokeWidth": stroke_width,
		}
	if shape_type == "ellipse":
		return {
			"type": "ellipse",
			"cx": _clamp(_coerce_number(item.get("cx"), canvas.width / 2), 0.0, canvas.width),
			"cy": _clamp(_coerce_number(item.get("cy"), canvas.height / 2), 0.0, canvas.height),
			"rx": _clamp(_coerce_number(item.get("rx"), 0.0), 0.0, canvas.width),
			"ry": _clamp(_coerce_number(item.get("ry"), 0.0), 0.0, canvas.height),
			"fill": fill,
			"stroke": stroke,
			"strokeWidth": stroke_width,
		}
	if shape_type == "line":
		return {
			"type": "line",
			"x1": _clamp(_coerce_number(item.get("x1"), 0.0), -canvas.width, canvas.width),
			"y1": _clamp(_coerce_number(item.get("y1"), 0.0), -canvas.height, canvas.height),
			"x2": _clamp(_coerce_number(item.get("x2"), 0.0), -canvas.width, canvas.width),
			"y2": _clamp(_coerce_number(item.get("y2"), 0.0), -canvas.height, canvas.height),
			"fill": "none",
			"stroke": stroke or "#000000",
			"strokeWidth": stroke_width,
		}
	if shape_type in {"polygon", "polyline"}:
		return {
			"type": shape_type,
			"points": _normalize_points(item.get("points")),
			"fill": fill,
			"stroke": stroke,
			"strokeWidth": stroke_width,
		}
	if shape_type == "star":
		points = int(_clamp(_coerce_number(item.get("points"), 5), MIN_POINTS_FOR_STAR, 64))
		min_dimension = min(canvas.width, canvas.height)
		default_outer_radius = max(min_dimension * 0.18, 1.0)
		outer_radius = _clamp(
			_coerce_number(item.get("outerRadius"), default_outer_radius),
			1.0,
			max(canvas.width, canvas.height),
		)
		inner_radius = _coerce_number(item.get("innerRadius"), outer_radius / 2.0)
		if inner_radius <= 0.0 or inner_radius >= outer_radius:
			inner_radius = outer_radius * 0.5
		inner_radius = _clamp(inner_radius, 0.5, outer_radius)
		return {
			"type": "star",
			"cx": _clamp(_coerce_number(item.get("cx"), canvas.width / 2), 0.0, canvas.width),
			"cy": _clamp(_coerce_number(item.get("cy"), canvas.height / 2), 0.0, canvas.height),
			"points": points,
			"outerRadius": outer_radius,
			"innerRadius": inner_radius,
			"rotation": _coerce_number(item.get("rotation"), 0.0),
			"fill": fill,
			"stroke": stroke,
			"strokeWidth": stroke_width,
		}
	if shape_type == "group":
		children = item.get("shapes")
		normalized_children: list[dict[str, Any]] = []
		if isinstance(children, list):
			for child in children[:MAX_SHAPES]:
				normalized_child = _normalize_shape(child, canvas)
				if normalized_child is not None:
					normalized_children.append(normalized_child)
		return {
			"type": "group",
			"transform": item.get("transform") if isinstance(item.get("transform"), str) else None,
			"shapes": normalized_children,
		}
	return None


def normalize_scene(raw_scene: dict[str, Any], *, seed: int, width: int, height: int) -> tuple[Scene, list[str]]:
	warnings: list[str] = []
	canvas_data = raw_scene.get("canvas") if isinstance(raw_scene.get("canvas"), dict) else {}
	canvas = Canvas(
		width=int(_clamp(_coerce_number(canvas_data.get("width"), width), 1.0, 4096.0)),
		height=int(_clamp(_coerce_number(canvas_data.get("height"), height), 1.0, 4096.0)),
		viewBox=[
			_coerce_number((canvas_data.get("viewBox") or [0, 0, width, height])[0], 0.0),
			_coerce_number((canvas_data.get("viewBox") or [0, 0, width, height])[1], 0.0),
			_coerce_number((canvas_data.get("viewBox") or [0, 0, width, height])[2], float(width)),
			_coerce_number((canvas_data.get("viewBox") or [0, 0, width, height])[3], float(height)),
		],
	)
	style_data = raw_scene.get("style") if isinstance(raw_scene.get("style"), dict) else {}
	style = StyleEnvelope(
		mood=[str(item) for item in style_data.get("mood", []) if isinstance(item, str)],
		symmetry=str(style_data.get("symmetry", "loose")),
		density=str(style_data.get("density", "medium")),
		palette=str(style_data.get("palette", "mixed")),
		seed=int(style_data.get("seed", seed)),
	)
	shapes_data = raw_scene.get("shapes")
	shapes: list[dict[str, Any]] = []
	if isinstance(shapes_data, list):
		for item in shapes_data[:MAX_SHAPES]:
			normalized = _normalize_shape(item, canvas)
			if normalized is not None:
				shapes.append(normalized)
	else:
		warnings.append("Missing shapes array; generated empty scene.")
	scene = Scene(canvas=canvas, style=style, shapes=shapes)
	return scene, warnings


def parse_scene_json(text: str) -> dict[str, Any]:
	data = json.loads(text)
	if not isinstance(data, dict):
		raise ValueError("Scene JSON must decode to an object.")
	return data


def star_to_points(star: dict[str, Any]) -> list[list[float]]:
	cx = _coerce_number(star.get("cx"), 0.0)
	cy = _coerce_number(star.get("cy"), 0.0)
	points = int(_clamp(_coerce_number(star.get("points"), 5), MIN_POINTS_FOR_STAR, 64))
	outer_radius = _coerce_number(star.get("outerRadius"), 0.0)
	inner_radius = _coerce_number(star.get("innerRadius"), outer_radius / 2.0)
	rotation = math.radians(_coerce_number(star.get("rotation"), 0.0))
	vertices: list[list[float]] = []
	total = points * 2
	for index in range(total):
		angle = rotation + (math.pi * index / points)
		radius = outer_radius if index % 2 == 0 else inner_radius
		x = cx + math.cos(angle) * radius
		y = cy + math.sin(angle) * radius
		vertices.append([x, y])
	return vertices
