"""
Load the scene system prompt and examples from disk.

Kept in a separate module so prompt text is human-editable without touching
Python source. Reads on each call; no caching (local dev, negligible cost).
"""

import json
import pathlib


PROMPTS_DIR = pathlib.Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT_FILE = PROMPTS_DIR / "scene_system.md"
EXAMPLES_FILE = PROMPTS_DIR / "scene_examples.json"


#============================================
def load_scene_prompt() -> tuple[str, list[dict]]:
	"""
	Read the system prompt text and example scenes from disk.

	Returns:
		A tuple of (system_prompt_text, example_scenes).
	"""
	# read the markdown system prompt verbatim
	system_text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
	# read the example scenes as a JSON array of dicts
	examples_raw = EXAMPLES_FILE.read_text(encoding="utf-8")
	examples = json.loads(examples_raw)
	if not isinstance(examples, list):
		raise ValueError(f"Examples file must be a JSON array: {EXAMPLES_FILE}")
	return system_text, examples
