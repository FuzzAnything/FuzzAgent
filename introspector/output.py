"""Unified JSON / PNG output helpers for the introspector package."""

import json
import os
from typing import Any

from .logging_setup import get_logger

logger = get_logger(__name__)


def write_json(introspector_dir: str, filename: str, data: dict[str, Any]) -> str:
    """Write *data* as pretty-printed JSON. Returns the output path."""
    os.makedirs(introspector_dir, exist_ok=True)
    path = os.path.join(introspector_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("Wrote JSON %s", path)
    return path


def try_write_png(introspector_dir: str, filename: str, fig) -> str | None:
    """Attempt to save a matplotlib figure as PNG.

    Silently returns ``None`` when matplotlib is not installed so that
    analysis steps can always produce JSON without requiring matplotlib.
    """
    try:
        import matplotlib  # noqa: F401 – ensure Agg backend before pyplot

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        os.makedirs(introspector_dir, exist_ok=True)
        path = os.path.join(introspector_dir, filename)
        fig.savefig(path)
        plt.close(fig)
        logger.info("Wrote PNG %s", path)
        return path
    except ImportError:
        logger.info("matplotlib not available, skipping PNG %s", filename)
        return None
