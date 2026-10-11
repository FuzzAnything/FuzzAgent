"""Generate docker-compose.yml by filling the docker_template.yml template."""

import logging
import os
import re
from pathlib import Path

import yaml

from controller.models import FuzzingTask

logger = logging.getLogger(__name__)

# Environment variable keys forwarded from host into container (OSS only)
OSS_ENV_KEYS = [
    "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_ENDPOINT", "OSS_BUCKET", "GITHUB_TOKEN"
]


def _fill_template(template: str, variables: dict[str, str]) -> str:
    # 1. Replace ${VAR:-default} first (before simple form matches)
    def repl_default(m: re.Match) -> str:
        var = m.group(1)
        default = m.group(2)
        if var in variables and variables[var]:
            return variables[var]
        return default

    template = re.sub(r"\$\{([^}:]+):-([^}]*)\}", repl_default, template)

    # 2. Replace ${VAR} (no default)
    def repl_simple(m: re.Match) -> str:
        var = m.group(1)
        if var in variables and variables[var]:
            return variables[var]
        return m.group(0)

    template = re.sub(r"\$\{([^}:]+)\}", repl_simple, template)
    return template


class ComposeGenerator:
    TEMPLATE_PATH = Path(__file__).parent / "docker_template.yml"

    def generate(self, task: FuzzingTask) -> Path:
        """Fill template, merge extra_env, save to workspace, return compose file path."""
        variables: dict[str, str] = {
            "CONTAINER_NAME": task.container_name,
            "COMMAND": task.command,
            "FUZZAGENT_DIR": task.fuzzagent_dir,
            "WRITE_MODE": "rw" if task.write_mode else "ro",
            "RAW_OUTPUT_DIR": task.raw_output_dir,
            "SRC_DIR": task.src_dir,
            "REPO_BASE_NAME": task.repo_base_name,
            "FUZZAGENT_AUTO_CLEAN": "1" if task.auto_clean else "0",
            "FUZZING_ENGINE": task.fuzzing_engine,
            "OPENAI_MODEL": task.llm_model,
            "OPENAI_BASE_URL": task.openai_base_url,
            "OPENAI_API_KEY": task.openai_api_key,
            # Per-model LLM tuning forwarded from llm_models.toml via Backend.
            "LLM_TEMPERATURE": str(task.llm_temperature),
            "LLM_TOP_P": str(task.llm_top_p),
            "LLM_TOP_K": str(task.llm_top_k),
            "LLM_REPLY_TIMEOUT": str(task.llm_reply_timeout),
            "MAX_AGENT_EPOCHS": str(task.max_agent_epochs),
            "REMINDER_TOKEN_RATIO": str(task.reminder_token_ratio),
            "MAX_TOKEN_LEN": str(task.max_token_len),
        }

        # Apply config overrides if present
        if task.config:
            cfg = task.config
            if "engine" in cfg:
                variables["FUZZING_ENGINE"] = cfg["engine"]
            if "fuzzing_duration_hours" in cfg:
                # Convert hours to seconds for the container
                hours = cfg["fuzzing_duration_hours"]
                variables["FUZZING_DURATION"] = str(int(hours) * 3600)

        # Also support direct field overrides
        if task.fuzzing_duration_hours:
            variables["FUZZING_DURATION"] = str(task.fuzzing_duration_hours * 3600)

        # OSS keys are optional — only include if present in host environment
        for key in OSS_ENV_KEYS:
            val = os.environ.get(key)
            if val is not None:
                variables[key] = val

        template = self.TEMPLATE_PATH.read_text()
        filled = _fill_template(template, variables)

        # Analysis tasks get FUZZAGENT_DEBUG=1 so the src/tools/* scripts they
        # subprocess-call (show_overview_code_coverage, header_analysis, etc.)
        # emit verbose [DEBUG] output and unsuppressed tracebacks into the
        # introspector log via run_logged. Normal scan tasks are unaffected.
        is_analysis = task.container_name.endswith("_analysis")
        needs_env_injection = bool(task.extra_env) or is_analysis

        if needs_env_injection:
            compose_data = yaml.safe_load(filled)
            env_list = compose_data["services"]["fuzzagent"].setdefault("environment", [])
            if is_analysis:
                env_list.append("FUZZAGENT_DEBUG=1")
            if task.extra_env:
                for env_key, env_val in task.extra_env.items():
                    env_list.append(f"{env_key}={env_val}")
            filled = yaml.dump(compose_data, default_flow_style=False, sort_keys=False)

        suffix = ".analysis" if is_analysis else ""
        compose_file = Path(task.raw_output_dir).parent / f"docker-compose{suffix}.yml"
        compose_file.write_text(filled)
        logger.info("Generated compose file for task %s: %s", task.task_id, compose_file)
        return compose_file
