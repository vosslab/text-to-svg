"""
Tests-dir conftest: ensure the repo root is on sys.path so tests can do
`import backend.*` regardless of whether pytest is invoked as `pytest`
(which does not add the current dir) or `python3 -m pytest` (which does).
"""

import sys
import pathlib

# this file lives at REPO_ROOT/tests/conftest.py, so go up two levels
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))
