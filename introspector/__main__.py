"""Entry-point for ``python3 -m introspector``.

Executes Category 1 analysis (requires full fuzzing runtime environment).
Only ``final_coverage`` remains here — other analyses have been migrated:

- coverage_over_time: produced on demand by Storage's generate_coverage_over_time
  gRPC handler (writes into the same .cache/introspector/ directory)
- token_cost / instr_classify / agent_gantt: moved to Storage normalizer (Rust)
"""

import os
import socket
import sys
import time
from typing import Any

from .config import AnalysisConfig
from .errors import AnalysisError
from .full_coverage_reply import FullCoverageReply
from .logging_setup import configure_logging, get_logger
from .output import write_json

ANALYSIS_STEPS: list[tuple[str, str, type]] = [
    ("reply_full_coverage", "final_coverage.json", FullCoverageReply),
]


def main() -> None:
    try:
        config = AnalysisConfig.from_env()
    except AnalysisError as exc:
        # Cannot configure file logger without config; print to stderr + exit.
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    config.ensure_introspector_dir()
    log_file = os.path.join(config.introspector_dir, "fuzzagent_introspector.log")
    configure_logging(log_file)

    logger = get_logger()
    # === Startup banner ===
    logger.info("=" * 60)
    logger.info("Introspector starting (pid=%d host=%s)", os.getpid(), socket.gethostname())
    logger.info("Python %s", sys.version.split()[0])
    logger.info("Plan: %d steps: %s", len(ANALYSIS_STEPS), [s[0] for s in ANALYSIS_STEPS])
    logger.info("Output directory:   %s", config.output_dir)
    logger.info("Introspector dir:   %s", config.introspector_dir)
    logger.info("VMS directory:      %s", config.vms_dir)
    logger.info("Cache coverage dir: %s", config.cache_coverage_dir)
    logger.info("Cache fuzzers dir:  %s", config.cache_fuzzers_dir)
    logger.info("Build dir:          %s", config.build_dir)
    logger.info("Fuzzers dir:        %s", config.fuzzers_dir)
    logger.info("Project name:       %s", config.project_name)
    logger.info("=" * 60)

    wall_start = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    failed_steps: list[str] = []

    for step_name, json_filename, cls in ANALYSIS_STEPS:
        logger.info("─" * 60)
        logger.info("STEP START %s", step_name)
        step_start = time.monotonic()
        try:
            analyzer = cls(config)
            data = analyzer.analyze()
            duration = time.monotonic() - step_start
            if data is not None:
                write_json(config.introspector_dir, json_filename, data)
                results[step_name] = data
                logger.info("STEP END %s status=ok duration=%.2fs", step_name, duration)
            else:
                logger.warning("STEP END %s status=skipped duration=%.2fs", step_name, duration)
                failed_steps.append(step_name)
        except AnalysisError:
            duration = time.monotonic() - step_start
            logger.error(
                "STEP END %s status=failed duration=%.2fs",
                step_name, duration, exc_info=True,
            )
            failed_steps.append(step_name)
        except Exception:
            duration = time.monotonic() - step_start
            logger.exception(
                "STEP END %s status=unexpected duration=%.2fs",
                step_name, duration,
            )
            failed_steps.append(step_name)

    wall_duration = time.monotonic() - wall_start
    logger.info("═" * 60)
    if failed_steps:
        logger.error(
            "Analysis complete WITH FAILURES: %d/%d succeeded in %.2fs; failed=%s",
            len(results), len(ANALYSIS_STEPS), wall_duration, failed_steps,
        )
        sys.exit(1)
    logger.info(
        "Analysis complete: %d/%d steps succeeded in %.2fs",
        len(results), len(ANALYSIS_STEPS), wall_duration,
    )


if __name__ == "__main__":
    main()
