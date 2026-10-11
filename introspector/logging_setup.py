"""Centralized logging + subprocess helpers for the introspector package.

All modules should call ``get_logger(__name__)`` instead of
``logging.getLogger(__name__)`` so every log line propagates to the root
FileHandler + StreamHandler installed once in ``__main__``.

Subprocess calls should go through ``run_logged`` so command lines, rc,
and stdout/stderr are captured uniformly.
"""

import logging
import os
import subprocess
import sys
import time
from typing import Sequence

LOGGER_NAME = "fuzzagent_introspector"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the introspector root.

    - ``get_logger()`` → root ``"fuzzagent_introspector"``
    - ``get_logger(__name__)`` where ``__name__`` is e.g. ``"introspector.output"``
      → ``"fuzzagent_introspector.output"`` (child of root, inherits handlers)
    """
    if not name or name == "__main__":
        return logging.getLogger(LOGGER_NAME)
    short = name.split(".")[-1]
    if short == LOGGER_NAME or not short:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{short}")


def configure_logging(log_file: str, *, level: str | None = None) -> None:
    """Attach FileHandler (overwrite) + StreamHandler (stdout) to the root logger.

    Level defaults to INFO, can be overridden via ``INTROSPECTOR_LOG_LEVEL`` env
    or the ``level`` kwarg (kwarg wins).
    """
    log_level = (level or os.getenv("INTROSPECTOR_LOG_LEVEL") or "INFO").upper()
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    root = logging.getLogger()
    root.setLevel(log_level)
    for h in list(root.handlers):
        root.removeHandler(h)

    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(log_level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(log_level)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def run_logged(
    cmd: Sequence[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    log_ctx: str = "",
) -> subprocess.CompletedProcess:
    """Run a subprocess with full logging; raise ``CalledProcessError`` on non-zero rc.

    Logs the command line + cwd before run, rc + duration after, then the
    FULL stdout/stderr — no truncation, no tail. The caller accepts that
    log files can become large; completeness beats brevity for diagnosing
    internal tool failures.
    """
    logger = get_logger()
    label = f"[{log_ctx}] " if log_ctx else ""
    cmd_str = " ".join(cmd)
    logger.info("%sRUN %s (cwd=%s)", label, cmd_str, cwd or "<inherit>")
    start = time.monotonic()

    result = subprocess.run(
        list(cmd),
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - start
    logger.info("%sDONE %s rc=%d duration=%.2fs", label, cmd[0], result.returncode, duration)

    if result.returncode == 0:
        if result.stdout:
            logger.info("%sstdout:\n%s", label, result.stdout)
        if result.stderr:
            logger.info("%sstderr:\n%s", label, result.stderr)
        return result

    logger.error("%sFAILED %s rc=%d", label, cmd_str, result.returncode)
    if result.stdout:
        logger.error("%sstdout: %s", label, result.stdout)
    if result.stderr:
        logger.error("%sstderr: %s", label, result.stderr)
    raise subprocess.CalledProcessError(
        result.returncode, list(cmd), output=result.stdout, stderr=result.stderr
    )


def log_file_info(path: str, label: str = "") -> None:
    """Log existence + size of a file (or 'MISSING')."""
    logger = get_logger()
    prefix = f"{label}: " if label else ""
    if os.path.exists(path):
        try:
            size = os.path.getsize(path)
            logger.info("%s%s exists size=%d bytes", prefix, path, size)
        except OSError as exc:
            logger.warning("%s%s stat error: %s", prefix, path, exc)
    else:
        logger.warning("%s%s MISSING", prefix, path)
