"""FuzzAgent introspector analysis package.

Run via:  python3 -m introspector

Each sub-module exposes an ``analyze(config) -> dict | None`` function.
The package entry-point iterates over all analysis steps with per-step
error isolation so that one failure does not block the others.
"""
