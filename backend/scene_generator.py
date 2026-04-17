"""
Model-backed scene generation.
"""

import json
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER_ROOT = REPO_ROOT / "local-llm-wrapper"
if str(WRAPPER_ROOT) not in sys.path:
	sys.path.insert(0, str(WRAPPER_ROOT))

import local_llm_wrapper.llm as llm

from backend.prompt_loader import load_scene_prompt
from backend.scene_model import GenerateSceneRequest, GenerateSceneResponse, normalize_scene


SCENE_TAG = "scene"
MAX_TOKENS = 1600


#============================================
def _strip_example_markers(example: dict) -> dict:
	"""Remove `_when` commentary keys before serializing an example."""
	return {key: value for key, value in example.items() if not key.startswith("_")}


#============================================
def _format_examples(examples: list[dict]) -> str:
	"""Render example scenes as a labeled block of <scene>...</scene> snippets."""
	parts: list[str] = []
	for example in examples:
		when = example.get("_when", "")
		clean = _strip_example_markers(example)
		snippet = json.dumps(clean, indent=2)
		if when:
			parts.append(f"Example ({when}):")
		else:
			parts.append("Example:")
		parts.append(f"<{SCENE_TAG}>\n{snippet}\n</{SCENE_TAG}>")
		parts.append("")
	return "\n".join(parts)


#============================================
def _build_prompt(request: GenerateSceneRequest, follow_up: str = "") -> str:
	"""
	Assemble the final prompt.

	Order (user request first is the highest-leverage design choice):
	  1. One-line frame.
	  2. The user's prompt, seed, and canvas size.
	  3. System guidance and schema.
	  4. Varied examples.
	  5. Final instruction, plus any corrective follow-up for retries.
	"""
	system_text, examples = load_scene_prompt()
	examples_block = _format_examples(examples)
	# user request is intentionally BEFORE examples so small models anchor on it
	sections: list[str] = []
	sections.append("You are helping render an SVG scene.")
	sections.append("")
	sections.append(f"User prompt: {request.prompt}")
	sections.append(f"Canvas: {request.width} x {request.height}")
	sections.append(f"Seed: {request.seed}")
	sections.append("")
	sections.append(system_text.strip())
	sections.append("")
	sections.append(examples_block)
	sections.append(
		f"Now emit the scene as JSON for the user prompt above, "
		f"wrapped in <{SCENE_TAG}>...</{SCENE_TAG}>."
	)
	if follow_up:
		sections.append("")
		sections.append(follow_up)
	prompt = "\n".join(sections)
	return prompt


#============================================
def _build_client(model_override: str | None) -> llm.LLMClient:
	# When the user picks "apple foundation" (no override), use Apple only.
	# Falling through to an auto-picked Ollama model surprises users whose
	# local Ollama does not have that model installed.
	transports: list = [llm.AppleTransport()]
	if model_override:
		transports.append(llm.OllamaTransport(model=model_override))
	client = llm.LLMClient(transports=transports, quiet=True)
	return client


#============================================
def _request_text(request: GenerateSceneRequest, follow_up: str = "") -> str:
	prompt = _build_prompt(request, follow_up=follow_up)
	client = _build_client(request.model)
	text = client.generate(prompt, purpose="scene JSON", max_tokens=MAX_TOKENS)
	return text


#============================================
def _extract_scene_json(raw_text: str) -> str:
	"""
	Find the LAST valid scene JSON object anywhere in the reply.

	Tolerant by design: small models drop the opening <scene> tag, wrap
	JSON in ```json ... ``` fences, or emit bare JSON with prose around
	it. All of those shapes are accepted. The rule is simple: scan for
	every balanced {...} block, parse each, and return the LAST one that
	decodes to an object containing both 'canvas' and 'shapes'.
	"""
	if not raw_text:
		return ""
	# first try the advertised <scene>...</scene> wrapping (cheapest and
	# most specific); falls through if the model dropped the opening tag
	tagged = llm.extract_xml_tag_content(raw_text, SCENE_TAG).strip()
	if tagged:
		candidate = _strip_code_fences(tagged)
		if _is_valid_scene_json(candidate):
			return candidate
	# walk every balanced brace span and keep the LAST one that looks like
	# a scene; "last" matters because echoed examples appear earlier
	spans = _balanced_brace_spans(raw_text)
	last_valid = ""
	for start, end in spans:
		candidate = raw_text[start:end]
		if _is_valid_scene_json(candidate):
			last_valid = candidate
	return last_valid


#============================================
def _strip_code_fences(text: str) -> str:
	"""Remove surrounding ```json ... ``` or ``` ... ``` fences if present."""
	stripped = text.strip()
	# drop a leading ```json or ``` line
	if stripped.startswith("```"):
		first_newline = stripped.find("\n")
		if first_newline != -1:
			stripped = stripped[first_newline + 1:]
	# drop a trailing ``` line
	if stripped.rstrip().endswith("```"):
		stripped = stripped.rstrip()[:-3]
	# drop a trailing </scene> if the model emitted an orphan closer
	stripped = stripped.strip()
	if stripped.endswith("</" + SCENE_TAG + ">"):
		stripped = stripped[: -len("</" + SCENE_TAG + ">")].strip()
	return stripped


#============================================
def _balanced_brace_spans(text: str) -> list[tuple[int, int]]:
	"""Return all balanced {...} spans in the text as (start, end_exclusive)."""
	spans: list[tuple[int, int]] = []
	starts: list[int] = []
	for index, ch in enumerate(text):
		if ch == "{":
			starts.append(index)
		elif ch == "}" and starts:
			start = starts.pop()
			spans.append((start, index + 1))
	return spans


#============================================
def _is_valid_scene_json(text: str) -> bool:
	"""True iff text decodes to a dict with 'canvas' and 'shapes' keys."""
	try:
		data = json.loads(text)
	except (json.JSONDecodeError, ValueError):
		return False
	if not isinstance(data, dict):
		return False
	return "canvas" in data and "shapes" in data


#============================================
def _fallback_scene(request: GenerateSceneRequest, reason: str) -> tuple[dict[str, Any], list[str]]:
	warnings = [reason]
	radius = min(request.width, request.height) * 0.18
	shapes: list[dict[str, Any]] = [
		{
			"type": "circle",
			"cx": request.width / 2,
			"cy": request.height / 2,
			"r": radius,
			"fill": "none",
			"stroke": "#7ad1ff",
			"strokeWidth": 4,
		}
	]
	scene = {
		"canvas": {
			"width": request.width,
			"height": request.height,
			"viewBox": [0, 0, request.width, request.height],
		},
		"shapes": shapes,
	}
	return scene, warnings


#============================================
def _parse_and_normalize(
	raw_text: str,
	request: GenerateSceneRequest,
) -> tuple[dict[str, Any], list[str]]:
	"""
	Parse the scene JSON block out of raw model text and normalize it.

	Raises ValueError on any extraction or parse failure so the caller can
	decide whether to retry or fall back.
	"""
	json_text = _extract_scene_json(raw_text)
	if not json_text:
		raise ValueError("No <scene> block found in model reply.")
	raw_scene = json.loads(json_text)
	if not isinstance(raw_scene, dict):
		raise ValueError("Scene block did not decode to an object.")
	if not isinstance(raw_scene.get("shapes"), list):
		raise ValueError("Scene block did not include a shapes array.")
	return raw_scene, []


#============================================
def generate_scene(request: GenerateSceneRequest) -> GenerateSceneResponse:
	raw_text = ""
	retry_text = ""
	used_fallback = False
	warnings: list[str] = []
	scene = None
	# first attempt
	try:
		raw_text = _request_text(request)
		raw_scene, _ = _parse_and_normalize(raw_text, request)
		scene, warnings = normalize_scene(
			raw_scene,
			seed=request.seed,
			width=request.width,
			height=request.height,
		)
	except Exception as first_exc:
		# one corrective retry before giving up
		follow_up = (
			f"Your last reply was not valid. "
			f"Emit the scene JSON wrapped in <{SCENE_TAG}>...</{SCENE_TAG}> and "
			"nothing else. Reason: " + str(first_exc)
		)
		try:
			retry_text = _request_text(request, follow_up=follow_up)
			raw_scene, _ = _parse_and_normalize(retry_text, request)
			scene, warnings = normalize_scene(
				raw_scene,
				seed=request.seed,
				width=request.width,
				height=request.height,
			)
			warnings = ["Recovered after retry: " + str(first_exc)] + warnings
		except Exception as second_exc:
			# hard fallback: synthesize a single-circle placeholder scene
			used_fallback = True
			fallback_reason = (
				"Model output could not be parsed after one retry. "
				f"First error: {first_exc}; retry error: {second_exc}"
			)
			scene_dict, fallback_warnings = _fallback_scene(request, fallback_reason)
			scene, warnings = normalize_scene(
				scene_dict,
				seed=request.seed,
				width=request.width,
				height=request.height,
			)
			warnings = fallback_warnings + warnings
	# assemble debug payload with both attempts visible
	debug = {
		"rawModelOutput": raw_text,
		"retryModelOutput": retry_text,
		"usedFallback": used_fallback,
		"normalizationNotes": warnings.copy(),
	}
	response = GenerateSceneResponse(
		scene=scene,
		normalizedFromModel=bool(raw_text) and not used_fallback,
		warnings=warnings,
		debug=debug,
	)
	return response
