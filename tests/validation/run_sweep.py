#!/usr/bin/env python3
"""
Validation sweep harness for text-to-svg.

Runs the 5 fixed prompts across available local models under both the NEW
(post-fix) and OLD (pre-fix) pipelines. Writes per-cell artifacts under
output_sweep/<pipeline>/<model>/<slug>/ for later scoring.

Usage:
	source source_me.sh && python3 tests/validation/run_sweep.py --dry-run
	source source_me.sh && python3 tests/validation/run_sweep.py
"""

# Standard Library
import re
import sys
import json
import time
import pathlib
import argparse
import dataclasses
import urllib.request

# PIP3 modules
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

# local repo modules
import backend.scene_generator as scene_generator
from backend.scene_model import GenerateSceneRequest
from backend.scene_renderer import render_svg


# ============================================
# Prompts are loaded from prompts.yaml; tags and adherence rules live there
# so the scorer can reuse them without duplicating the prompt catalog.
PROMPTS_FILE = pathlib.Path(__file__).resolve().parent / "prompts.yaml"
SEED = 42
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
MAX_MODELS = 3
OUTPUT_ROOT = REPO_ROOT / "output_sweep"


# ============================================
def load_prompts() -> list[dict]:
	# YAML file is the single source of truth for prompt catalog
	data = yaml.safe_load(PROMPTS_FILE.read_text(encoding="utf-8"))
	prompts = data.get("prompts")
	if not isinstance(prompts, list):
		raise ValueError(f"prompts.yaml must have a top-level `prompts:` list ({PROMPTS_FILE})")
	return prompts


# ============================================
# Pre-fix prompt text, kept verbatim so the OLD pipeline is a faithful
# replay of the prompt the user was shipping before the 2026-04-17 fixes.
OLD_SCENE_PROMPT = """You generate a scene description for a compiler.
The final answer must include one JSON object with version, canvas, style, and shapes.
Shapes may be circle, rect, ellipse, line, polygon, polyline, star, or group.
Use star for regular stars.
Keep shape count small and scene composition coherent.
Use a dark gray canvas background.

Example scene:
{
  "version": "1.0",
  "canvas": {"width": 800, "height": 800, "viewBox": [0, 0, 800, 800]},
  "style": {"mood": ["clean"], "symmetry": "radial", "density": "low", "palette": "mixed", "seed": 1},
  "shapes": [
    {"type": "star", "cx": 400, "cy": 400, "points": 11, "outerRadius": 192, "innerRadius": 88, "rotation": 0, "fill": "none", "stroke": "#7ad1ff", "strokeWidth": 4}
  ]
}

Example scene:
{
  "version": "1.0",
  "canvas": {"width": 800, "height": 800, "viewBox": [0, 0, 800, 800]},
  "style": {"mood": ["calm"], "symmetry": "centered", "density": "low", "palette": "mixed", "seed": 2},
  "shapes": [
    {"type": "circle", "cx": 400, "cy": 400, "r": 180, "fill": "none", "stroke": "#ffcc66", "strokeWidth": 6}
  ]
}

Example scene:
{
  "version": "1.0",
  "canvas": {"width": 800, "height": 800, "viewBox": [0, 0, 800, 800]},
  "style": {"mood": ["bright"], "symmetry": "loose", "density": "medium", "palette": "mixed", "seed": 3},
  "shapes": [
    {"type": "rect", "x": 240, "y": 280, "width": 320, "height": 240, "rx": 28, "ry": 28, "fill": "none", "stroke": "#ff88aa", "strokeWidth": 5},
    {"type": "line", "x1": 280, "y1": 360, "x2": 520, "y2": 440, "fill": "none", "stroke": "#ffffff", "strokeWidth": 4}
  ]
}
"""


# ============================================
def _slugify(text: str) -> str:
	# collapse non-alphanumerics so the prompt maps to a safe directory name
	slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
	return slug[:40] or "prompt"


# ============================================
def _count_shapes(shapes: list) -> int:
	# count leaf shapes, descending into groups so density is comparable
	total = 0
	for shape in shapes:
		if isinstance(shape, dict) and shape.get("type") == "group":
			total += _count_shapes(shape.get("shapes", []))
		else:
			total += 1
	return total


# ============================================
def _list_ollama_models() -> list[str]:
	# reuse the same endpoint the backend uses; return [] on failure
	models: list[str] = []
	url = "http://localhost:11434/api/tags"
	request = urllib.request.Request(url, method="GET")
	try:
		with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
			data = json.loads(response.read().decode("utf-8"))
	except Exception:
		return models
	for model_info in data.get("models", []):
		name = model_info.get("name", "")
		if isinstance(name, str) and name:
			models.append(name)
	return models


# ============================================
def select_models() -> list[str]:
	# Apple foundation is always tried (empty string = backend default)
	# then the first MAX_MODELS Ollama models by alphabetical order for
	# stable cross-run comparison
	choices = [""]
	ollama = sorted(_list_ollama_models())
	choices.extend(ollama[:MAX_MODELS])
	return choices


# ============================================
def _build_old_prompt(request: GenerateSceneRequest) -> str:
	# faithful reproduction of the pre-fix prompt assembly
	prompt = OLD_SCENE_PROMPT
	prompt += "\n"
	prompt += f"User prompt: {request.prompt}\n"
	prompt += f"Seed: {request.seed}\n"
	prompt += f"Canvas: {request.width}x{request.height}\n"
	prompt += f"Model override: {request.model or 'default'}\n"
	prompt += "Return the final JSON object somewhere in the reply, ideally last."
	return prompt


# ============================================
def _old_extract_json_text(raw_text: str) -> str:
	# byte-for-byte clone of the pre-fix brace-walker extractor
	text = raw_text.strip()
	if not text:
		return ""
	spans: list[tuple[int, int]] = []
	starts: list[int] = []
	for index, ch in enumerate(text):
		if ch == "{":
			starts.append(index)
		elif ch == "}" and starts:
			start = starts.pop()
			spans.append((start, index + 1))
	for start, end in reversed(spans):
		candidate = text[start:end]
		try:
			data = json.loads(candidate)
		except json.JSONDecodeError:
			continue
		if isinstance(data, dict):
			if "shapes" in data and "canvas" in data and "version" in data:
				return candidate
	return text


# ============================================
def _run_old_pipeline(request: GenerateSceneRequest) -> dict:
	# replay the full pre-fix pipeline end to end: old prompt, old extractor,
	# no retry, single-circle fallback on failure
	from backend.scene_model import normalize_scene

	client = scene_generator._build_client(request.model)
	prompt = _build_old_prompt(request)
	raw_text = ""
	used_fallback = False
	error = ""
	try:
		raw_text = client.generate(prompt, purpose="scene JSON", max_tokens=1200)
		json_text = _old_extract_json_text(raw_text)
		if not json_text:
			raise ValueError("Empty model response.")
		raw_scene = json.loads(json_text)
		if not isinstance(raw_scene, dict):
			raise ValueError("Model response must be a JSON object.")
		if not isinstance(raw_scene.get("shapes"), list):
			raise ValueError("Model response did not include a shapes array.")
		scene, warnings = normalize_scene(
			raw_scene,
			seed=request.seed,
			width=request.width,
			height=request.height,
		)
	except Exception as exc:
		used_fallback = True
		error = str(exc)
		scene_dict, warnings = scene_generator._fallback_scene(request, f"old-pipeline fallback: {exc}")
		scene, extra = normalize_scene(
			scene_dict,
			seed=request.seed,
			width=request.width,
			height=request.height,
		)
		warnings = warnings + extra
	cell = {
		"raw": raw_text,
		"retry": "",
		"scene": dataclasses.asdict(scene),
		"used_fallback": used_fallback,
		"warnings": warnings,
		"error": error,
	}
	return cell


# ============================================
def _run_new_pipeline(request: GenerateSceneRequest) -> dict:
	# new pipeline is just a normal call into generate_scene
	response = scene_generator.generate_scene(request)
	cell = {
		"raw": response.debug.get("rawModelOutput", ""),
		"retry": response.debug.get("retryModelOutput", ""),
		"scene": dataclasses.asdict(response.scene),
		"used_fallback": bool(response.debug.get("usedFallback", False)),
		"warnings": response.warnings,
		"error": "",
	}
	return cell


# ============================================
def _write_cell(pipeline: str, model: str, prompt: str, cell: dict, wall_seconds: float) -> None:
	model_slug = _slugify(model) if model else "apple_foundation"
	prompt_slug = _slugify(prompt)
	cell_dir = OUTPUT_ROOT / pipeline / model_slug / prompt_slug
	cell_dir.mkdir(parents=True, exist_ok=True)
	(cell_dir / "raw.txt").write_text(cell["raw"], encoding="utf-8")
	(cell_dir / "retry.txt").write_text(cell["retry"], encoding="utf-8")
	(cell_dir / "scene.json").write_text(json.dumps(cell["scene"], indent=2), encoding="utf-8")
	# rebuild a Scene-like object for the renderer by re-normalizing
	from backend.scene_model import normalize_scene
	scene_obj, _ = normalize_scene(
		cell["scene"],
		seed=SEED,
		width=CANVAS_WIDTH,
		height=CANVAS_HEIGHT,
	)
	svg = render_svg(scene_obj)
	(cell_dir / "scene.svg").write_text(svg, encoding="utf-8")
	shape_count = _count_shapes(cell["scene"].get("shapes", []))
	meta = {
		"pipeline": pipeline,
		"model": model or "apple_foundation",
		"prompt": prompt,
		"seed": SEED,
		"canvasWidth": CANVAS_WIDTH,
		"canvasHeight": CANVAS_HEIGHT,
		"usedFallback": cell["used_fallback"],
		"shapeCount": shape_count,
		"wallSeconds": round(wall_seconds, 3),
		"warnings": cell["warnings"],
		"error": cell["error"],
	}
	(cell_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ============================================
def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"-d", "--dry-run",
		dest="dry_run",
		action="store_true",
		help="print the planned (pipeline, model, prompt) cells and exit",
	)
	parser.add_argument(
		"-p", "--pipelines",
		dest="pipelines",
		default="old,new",
		help="comma-separated pipelines to run (default: old,new)",
	)
	parser.add_argument(
		"-m", "--models",
		dest="models",
		default="",
		help='comma-separated model names to override auto-selection; use "" for apple foundation',
	)
	args = parser.parse_args()
	return args


# ============================================
def main() -> None:
	args = parse_args()
	pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
	# "old" replays the pre-fix pipeline; anything else ("new", "new2",
	# "experiment_x", ...) runs the current generate_scene and writes to
	# its own named subdirectory so prior runs are not overwritten.
	for pipeline in pipelines:
		if not pipeline:
			raise ValueError("empty pipeline name")
	if args.models:
		# explicit override; treat entries as-is. An empty string slot means apple
		models = [m.strip() for m in args.models.split(",")]
	else:
		models = select_models()
	prompt_entries = load_prompts()
	prompts = [entry["prompt"] for entry in prompt_entries]
	cells = []
	for pipeline in pipelines:
		for model in models:
			for prompt in prompts:
				cells.append((pipeline, model, prompt))
	print(f"planned cells: {len(cells)} ({len(pipelines)} pipelines x {len(models)} models x {len(prompts)} prompts)")
	for pipeline, model, prompt in cells:
		label = model or "apple_foundation"
		print(f"  [{pipeline}] {label} :: {prompt}")
	if args.dry_run:
		return
	OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
	for index, (pipeline, model, prompt) in enumerate(cells, start=1):
		label = model or "apple_foundation"
		print(f"\n[{index}/{len(cells)}] {pipeline} / {label} / {prompt}")
		request = GenerateSceneRequest(
			prompt=prompt,
			seed=SEED,
			width=CANVAS_WIDTH,
			height=CANVAS_HEIGHT,
			model=model if model else None,
		)
		started = time.monotonic()
		if pipeline == "old":
			cell = _run_old_pipeline(request)
		else:
			cell = _run_new_pipeline(request)
		elapsed = time.monotonic() - started
		_write_cell(pipeline, model, prompt, cell, elapsed)
		fallback_note = " FALLBACK" if cell["used_fallback"] else ""
		print(f"  -> wrote cell in {elapsed:.1f}s{fallback_note}")


if __name__ == "__main__":
	main()
