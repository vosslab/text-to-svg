import json

import backend.scene_generator as scene_generator
from backend.prompt_loader import load_scene_prompt
from backend.scene_model import normalize_scene, parse_scene_json, star_to_points
from backend.scene_renderer import render_svg


def test_parse_scene_json_requires_object() -> None:
	data = parse_scene_json('{"canvas": {"width": 100, "height": 100}, "shapes": []}')
	assert data["canvas"]["width"] == 100


def test_normalize_scene_accepts_minimal_input() -> None:
	# shrunk schema: only canvas and shapes are required
	raw_scene = {
		"canvas": {"width": 200, "height": 200},
		"shapes": [{"type": "circle", "cx": 100, "cy": 100, "r": 30}],
	}
	scene, warnings = normalize_scene(raw_scene, seed=1, width=200, height=200)
	assert warnings == []
	assert scene.shapes[0]["type"] == "circle"


def test_normalize_scene_keeps_star_semantics() -> None:
	raw_scene = {
		"canvas": {"width": 200, "height": 200, "viewBox": [0, 0, 200, 200]},
		"shapes": [
			{
				"type": "star",
				"cx": 100,
				"cy": 100,
				"points": 5,
				"outerRadius": 50,
				"innerRadius": 25,
				"rotation": 0,
				"fill": "none",
				"stroke": "#ffffff",
				"strokeWidth": 3,
			}
		],
	}
	scene, warnings = normalize_scene(raw_scene, seed=7, width=200, height=200)
	assert warnings == []
	assert scene.shapes[0]["type"] == "star"
	assert len(star_to_points(scene.shapes[0])) == 10


def test_render_svg_has_no_hardcoded_background() -> None:
	# the renderer no longer paints dark gray; the scene's own shapes decide the backdrop
	raw_scene = {
		"canvas": {"width": 200, "height": 200, "viewBox": [0, 0, 200, 200]},
		"shapes": [{"type": "circle", "cx": 100, "cy": 100, "r": 40, "fill": "#ff0000"}],
	}
	scene, _ = normalize_scene(raw_scene, seed=1, width=200, height=200)
	svg = render_svg(scene)
	assert 'fill="#2a2a2a"' not in svg
	assert "<circle" in svg


def test_render_svg_lowers_star_to_polygon() -> None:
	raw_scene = {
		"canvas": {"width": 200, "height": 200, "viewBox": [0, 0, 200, 200]},
		"shapes": [
			{
				"type": "star",
				"cx": 100,
				"cy": 100,
				"points": 5,
				"outerRadius": 50,
				"innerRadius": 25,
				"rotation": 0,
			}
		],
	}
	scene, _ = normalize_scene(raw_scene, seed=1, width=200, height=200)
	svg = render_svg(scene)
	assert "<polygon" in svg
	assert "points=" in svg


def test_prompt_loader_returns_system_text_and_examples() -> None:
	# human-editable prompt files exist and parse
	system_text, examples = load_scene_prompt()
	assert "svg scene" in system_text.lower()
	assert isinstance(examples, list)
	assert len(examples) >= 3
	for example in examples:
		assert "canvas" in example
		assert "shapes" in example


def test_extract_scene_json_picks_last_tag_block() -> None:
	# an echoed example appears first; the real answer is the LAST <scene> block
	text = "Here is an example:\n"
	text += '<scene>{"canvas":{"width":10,"height":10},"shapes":[]}</scene>\n'
	text += "And my answer:\n"
	text += '<scene>{"canvas":{"width":400,"height":300},"shapes":[{"type":"circle","cx":200,"cy":150,"r":40}]}</scene>\n'
	text += "Done."
	extracted = scene_generator._extract_scene_json(text)
	parsed = json.loads(extracted)
	# rfind means the LAST block wins
	assert parsed["canvas"]["width"] == 400
	assert parsed["shapes"][0]["type"] == "circle"


def test_extract_scene_json_returns_empty_when_no_tag() -> None:
	extracted = scene_generator._extract_scene_json("no tags here")
	assert extracted == ""


def test_extract_scene_json_accepts_fenced_json_without_opener() -> None:
	# apple_foundation often drops the opening <scene> tag and wraps JSON
	# in a markdown code fence; this pattern must still parse
	text = "```json\n"
	text += '{"canvas":{"width":400,"height":300},"shapes":[{"type":"circle","cx":10,"cy":10,"r":5}]}\n'
	text += "</scene>\n```"
	extracted = scene_generator._extract_scene_json(text)
	parsed = json.loads(extracted)
	assert parsed["canvas"]["width"] == 400
	assert parsed["shapes"][0]["type"] == "circle"


def test_extract_scene_json_accepts_bare_json_in_prose() -> None:
	# plain JSON object floating in prose should still be recovered
	text = "Here is my scene: "
	text += '{"canvas":{"width":200,"height":200},"shapes":[{"type":"rect","x":1,"y":1,"width":10,"height":10}]}'
	text += " done."
	extracted = scene_generator._extract_scene_json(text)
	parsed = json.loads(extracted)
	assert parsed["shapes"][0]["type"] == "rect"


def test_extract_scene_json_picks_last_valid_when_example_echoed_as_bare_json() -> None:
	# echoed example earlier in the reply must not beat the final answer
	text = '{"canvas":{"width":10,"height":10},"shapes":[]}\n'
	text += "And my answer:\n"
	text += '{"canvas":{"width":500,"height":500},"shapes":[{"type":"circle","cx":1,"cy":1,"r":1}]}'
	extracted = scene_generator._extract_scene_json(text)
	parsed = json.loads(extracted)
	assert parsed["canvas"]["width"] == 500


def test_generate_scene_uses_retry_then_succeeds(monkeypatch) -> None:
	# first call emits malformed output, retry emits a clean <scene> block
	calls: list[str] = []

	def fake_request(request, follow_up: str = "") -> str:
		calls.append(follow_up)
		if not follow_up:
			return "garbage with no scene tags at all"
		return '<scene>{"canvas":{"width":200,"height":200},"shapes":[{"type":"rect","x":10,"y":10,"width":50,"height":50,"fill":"#00ff00"}]}</scene>'

	monkeypatch.setattr(scene_generator, "_request_text", fake_request)
	request = scene_generator.GenerateSceneRequest(
		prompt="a green square",
		seed=3,
		width=200,
		height=200,
	)
	response = scene_generator.generate_scene(request)
	# two calls: one original, one retry
	assert len(calls) == 2
	assert calls[0] == ""
	assert calls[1]
	assert response.scene.shapes[0]["type"] == "rect"
	assert response.debug["usedFallback"] is False
	assert any("Recovered after retry" in w for w in response.warnings)


def test_generate_scene_falls_back_when_retry_also_fails(monkeypatch) -> None:
	# both attempts return unusable text -> fallback circle
	monkeypatch.setattr(scene_generator, "_request_text", lambda request, follow_up="": "")
	request = scene_generator.GenerateSceneRequest(
		prompt="anything",
		seed=1,
		width=200,
		height=200,
	)
	response = scene_generator.generate_scene(request)
	assert response.debug["usedFallback"] is True
	assert response.scene.shapes[0]["type"] == "circle"
	assert response.warnings
