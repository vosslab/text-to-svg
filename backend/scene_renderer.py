"""
Deterministic SVG rendering for validated scene data.
"""

from html import escape
from typing import Any

from backend.scene_model import Scene, star_to_points


def _points_attr(points: list[list[float]]) -> str:
	pairs: list[str] = []
	for point in points:
		pairs.append(f"{point[0]:.2f},{point[1]:.2f}")
	return " ".join(pairs)


def _svg_attrs(attrs: dict[str, Any]) -> str:
	parts: list[str] = []
	for key, value in attrs.items():
		if value is None:
			continue
		parts.append(f'{key}="{escape(str(value), quote=True)}"')
	return " ".join(parts)


def _render_shape(shape: dict[str, Any]) -> str:
	shape_type = shape["type"]
	fill = shape.get("fill", "none")
	stroke = shape.get("stroke")
	stroke_width = shape.get("strokeWidth")
	if shape_type == "circle":
		return f"<circle {_svg_attrs({'cx': shape['cx'], 'cy': shape['cy'], 'r': shape['r'], 'fill': fill, 'stroke': stroke, 'stroke-width': stroke_width})}/>"
	if shape_type == "rect":
		return f"<rect {_svg_attrs({'x': shape['x'], 'y': shape['y'], 'width': shape['width'], 'height': shape['height'], 'rx': shape.get('rx'), 'ry': shape.get('ry'), 'fill': fill, 'stroke': stroke, 'stroke-width': stroke_width})}/>"
	if shape_type == "ellipse":
		return f"<ellipse {_svg_attrs({'cx': shape['cx'], 'cy': shape['cy'], 'rx': shape['rx'], 'ry': shape['ry'], 'fill': fill, 'stroke': stroke, 'stroke-width': stroke_width})}/>"
	if shape_type == "line":
		return f"<line {_svg_attrs({'x1': shape['x1'], 'y1': shape['y1'], 'x2': shape['x2'], 'y2': shape['y2'], 'fill': fill, 'stroke': stroke or '#000000', 'stroke-width': stroke_width})}/>"
	if shape_type == "polygon":
		return f"<polygon {_svg_attrs({'points': _points_attr(shape.get('points', [])), 'fill': fill, 'stroke': stroke, 'stroke-width': stroke_width})}/>"
	if shape_type == "polyline":
		return f"<polyline {_svg_attrs({'points': _points_attr(shape.get('points', [])), 'fill': fill, 'stroke': stroke, 'stroke-width': stroke_width})}/>"
	if shape_type == "star":
		points = _points_attr(star_to_points(shape))
		return f"<polygon {_svg_attrs({'points': points, 'fill': fill, 'stroke': stroke, 'stroke-width': stroke_width})}/>"
	if shape_type == "group":
		children = shape.get("shapes", [])
		inner = "".join(_render_shape(child) for child in children)
		transform = shape.get("transform")
		if transform:
			return f"<g transform=\"{escape(str(transform), quote=True)}\">{inner}</g>"
		return f"<g>{inner}</g>"
	return ""


def render_svg(scene: Scene) -> str:
	width = scene.canvas.width
	height = scene.canvas.height
	view_box = " ".join(str(value) for value in scene.canvas.viewBox)
	# No hardcoded background: the scene's own shapes decide the backdrop.
	# Examples demonstrate drawing a background rect first when one is needed.
	body = "".join(_render_shape(shape) for shape in scene.shapes)
	return (
		f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
		f'viewBox="{view_box}">{body}</svg>'
	)
