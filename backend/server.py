"""
Local HTTP server for scene generation and static frontend delivery.
"""

import dataclasses
import json
import pathlib
import sys
import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from backend.scene_generator import generate_scene
from backend.scene_model import GenerateSceneRequest
from backend.scene_renderer import render_svg


API_VERSION = "1.1"


WEB_ROOT = REPO_ROOT / "web"


def _list_ollama_models() -> list[str]:
	models: list[str] = []
	try:
		import urllib.request

		url = "http://localhost:11434/api/tags"
		request = urllib.request.Request(url, method="GET")
		with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
			data = json.loads(response.read().decode("utf-8"))
	except Exception:
		return models
	for model_info in data.get("models", []):
		name = model_info.get("name", "")
		if isinstance(name, str) and name:
			models.append(name)
	return models


def _dataclass_to_dict(value: Any) -> Any:
	if dataclasses.is_dataclass(value):
		return dataclasses.asdict(value)
	if isinstance(value, list):
		return [_dataclass_to_dict(item) for item in value]
	if isinstance(value, dict):
		return {key: _dataclass_to_dict(item) for key, item in value.items()}
	return value


class SceneRequestHandler(BaseHTTPRequestHandler):
	def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
		body = json.dumps(payload).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _send_file(self, path: pathlib.Path, content_type: str) -> None:
		body = path.read_bytes()
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self) -> None:  # noqa: N802
		if self.path == "/api/health":
			self._send_json(HTTPStatus.OK, {"ok": True, "version": API_VERSION})
			return
		if self.path == "/api/models":
			self._send_json(HTTPStatus.OK, {"models": _list_ollama_models()})
			return
		if self.path == "/":
			self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
			return
		if self.path == "/app.css":
			self._send_file(WEB_ROOT / "app.css", "text/css; charset=utf-8")
			return
		if self.path == "/app.js":
			self._send_file(WEB_ROOT / "app.js", "application/javascript; charset=utf-8")
			return
		self.send_error(HTTPStatus.NOT_FOUND)

	def do_POST(self) -> None:  # noqa: N802
		if self.path != "/api/generate":
			self.send_error(HTTPStatus.NOT_FOUND)
			return
		length = int(self.headers.get("Content-Length", "0"))
		raw = self.rfile.read(length).decode("utf-8")
		data = json.loads(raw)
		request = GenerateSceneRequest(
			prompt=str(data["prompt"]),
			seed=int(data.get("seed", 1)),
			width=int(data.get("width", 800)),
			height=int(data.get("height", 800)),
			model=str(data["model"]) if data.get("model") else None,
		)
		response = generate_scene(request)
		scene_dict = _dataclass_to_dict(response.scene)
		svg = render_svg(response.scene)
		self._send_json(
			HTTPStatus.OK,
			{
				"scene": scene_dict,
				"normalizedFromModel": response.normalizedFromModel,
				"warnings": response.warnings,
				"debug": response.debug,
				"svg": svg,
			},
		)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--port", type=int, default=0)
	args = parser.parse_args()
	server = ThreadingHTTPServer(("127.0.0.1", args.port), SceneRequestHandler)
	print(f"Serving on http://127.0.0.1:{server.server_port}")
	server.serve_forever()


if __name__ == "__main__":
	main()
