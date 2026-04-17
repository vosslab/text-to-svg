# Text to SVG

A local experiment that turns short natural-language descriptions into simple
shape-based SVG scenes. A Python backend calls the vendored
[local-llm-wrapper/](local-llm-wrapper/) (Apple foundation model or an Ollama
model) to emit a small scene, and a TypeScript frontend renders it in the
browser. For geometric compositions like "five interlocking rings" or "an
eleven-point star", not for pictorial illustration.

Status: experimental, local-only.

## Quick start

Build the frontend bundle, start the server, and open the app in a browser:

```bash
bash build_and_run.sh
```

The script picks a random localhost port, prints the URL, and opens it on
macOS. To run the server manually on a fixed port:

```bash
source source_me.sh && python3 -m backend.server --port 8000
```

## Documentation

- [docs/CHANGELOG.md](docs/CHANGELOG.md): chronological record of changes.
- [docs/AUTHORS.md](docs/AUTHORS.md): maintainers and contributors.
- [docs/PLAYWRIGHT_USAGE.md](docs/PLAYWRIGHT_USAGE.md): browser-automation notes.
- [docs/REPO_STYLE.md](docs/REPO_STYLE.md): repo layout and naming conventions.
- [docs/PYTHON_STYLE.md](docs/PYTHON_STYLE.md): Python conventions for this repo.
- [docs/TYPESCRIPT_STYLE.md](docs/TYPESCRIPT_STYLE.md): TypeScript conventions.
- [docs/MARKDOWN_STYLE.md](docs/MARKDOWN_STYLE.md): Markdown style for this repo.
- [docs/CLAUDE_HOOK_USAGE_GUIDE.md](docs/CLAUDE_HOOK_USAGE_GUIDE.md): agent hook notes.

## Testing

```bash
source source_me.sh && python3 -m pytest tests/backend/ -x
```

Validation sweep (runs the 12-prompt benchmark against all local models, then
scores the results into `output_sweep/REPORT.md`):

```bash
source source_me.sh && python3 tests/validation/run_sweep.py
source source_me.sh && python3 tests/validation/score_sweep.py
```

## License

- Code: LGPL v3. See [LICENSE.LGPL_v3](LICENSE.LGPL_v3).
- Non-code materials (docs, figures): CC BY 4.0. See [LICENSE.CC_BY_4_0](LICENSE.CC_BY_4_0).
