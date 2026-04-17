# Changelog

## 2026-04-17

### Documentation
- Rewrite the README summary to emphasize user-facing capabilities, local
  generation, and the kinds of prompts the app is best suited for.

## 2026-04-17

### Additions and New Features
- Add a local text-to-scene web app with a TypeScript frontend and a Python backend.
- Add a shared scene contract with deterministic SVG rendering and a first-class `star` primitive.
- Add a backend JSON API that uses the vendored `local-llm-wrapper` for model-backed scene generation.
- Add `build_and_run.sh` to clear local caches, rebuild the frontend bundle, and start the web server.
- Update `build_and_run.sh` and `backend.server` to use a random localhost port and open the URL on macOS.
- Add `backend/prompts/scene_system.md` and `backend/prompts/scene_examples.json` so the LLM prompt and example scenes are human-editable without touching Python.
- Add `backend/prompt_loader.py` to load the externalized prompt on each request.
- Add a collapsible "Raw model output" panel and a clear "Fallback scene" banner to the frontend so the model's actual reply is visible and fallbacks are never mistaken for intentional output.

### Behavior or Interface Changes
- Rework the scene prompt to put the user's request FIRST (before schema and examples), drop the "compiler" framing, drop the forced dark-gray background, drop the "keep shape count small" bias, and drop the `Model override` line. These reduce the model overriding user intent.
- Replace the three near-identical examples with five varied scenes (different canvas sizes, filled shapes, polygons, groups, a star medallion, and a multi-shape landscape).
- Wrap the model's scene output in an explicit `<scene>...</scene>` tag and extract via `local_llm_wrapper.llm.extract_xml_tag_content` (uses `rfind`, so echoed example tags do not beat the final answer).
- Add a single corrective retry in `generate_scene` before falling back, so transient malformed replies are recovered instead of silently becoming single-circle fallbacks.
- Shrink the scene schema: drop the `version` field, make `style` fields optional. Only `canvas.width`, `canvas.height`, and `shapes` are required by the model contract.
- Stop hardcoding a `#2a2a2a` background rect in the renderer; scenes now decide their own backdrop (examples demonstrate drawing a background rect first).

### Fixes and Maintenance
- Extend `tests/backend/test_scene_backend.py` with coverage for prompt loader, tag extraction picking the LAST `<scene>` block, retry recovery path, fallback-on-double-failure path, and the shrunk minimal schema.

### Decisions and Failures
- Considered dropping JSON entirely for direct SVG or a custom DSL and rejected both for now: the evidence points at the prompt shape as the dominant problem, so prompt cleanup plus tag-wrapped JSON plus retry is the minimum-risk fix. Direct SVG remains on the table if model-vs-JSON failures persist after these changes.
- Enable Ollama thinking mode for thinking-capable model families (gemma3, gemma4, qwen3, deepseek-r1). Adds opt-in `think` parameter to the vendored `OllamaTransport`, and `backend/scene_generator.py` matches the request's model name against a prefix list to decide whether to set it. Models that do not support thinking ignore the field silently. Expected cost: slower inference on thinking-enabled cells; expected benefit: fewer geometry and color omissions (missing strokes, stacked centers) that the rubric currently penalizes.
- Adopt a benchmark-hygiene rule for `backend/prompts/scene_examples.json`: few-shot examples must not be isomorphic to any validation-prompt answer shape at the construction-recipe level (same leaf-shape count, same arrangement, same decomposition into the same primitive types, or near-identical topology). Same prompt text or same abstract pattern (repetition, symmetry) is fine; handing the model the same recipe the rubric checks is not. Reason: a first rays example (central circle + 8 radial lines) was a near-answer for the `sun_eight_rays` validation prompt, which would have made score movement on that prompt uninterpretable. Replaced it with a compass-tick-ring (central rect + 8 short tangential ticks) that teaches 8-way radial placement without being the answer shape.
