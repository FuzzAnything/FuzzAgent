from pydantic import BaseModel, Field, field_validator
from typing import Tuple, Any
import os, sys
from pathlib import Path
import yaml

_REQUIRED_ENV_VARS = ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"]
_MISSING = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
if _MISSING:
    print(f"Required environment variables not set: {', '.join(_MISSING)}", file=sys.stderr)
    sys.exit(-1)

_script_path = os.path.realpath(__file__)

_script_dir = os.path.dirname(_script_path)
class ACIVariables(BaseModel):
    CURRENT_FILE: str = ""
    CURRENT_LINE: int = 0
    OVERLAP: int = 2
    WINDOW: int = 100
    CMD_OUTPUT_LINES: int = 100
    MAX_OUTPUT_CHARACTERS: int = 100000 # 10k tokens * 10 characters per token
    WHITELIST_CMD_TIMEOUT: int = 5400
    DISABLE_COVERAGE_GUIDANCE: int = 0

    def __getitem__(self, key):
        return getattr(self, key)


class LLMArgs(BaseModel):
    OPENAI_API_BASE: str = os.environ["OPENAI_BASE_URL"]
    OPENAI_MODEL: str = os.environ["OPENAI_MODEL"]
    LLM_REPLY_TIMEOUT: int = int(os.environ.get("LLM_REPLY_TIMEOUT", 600))
    LLM_TEMPERATURE: float = float(os.environ.get("LLM_TEMPERATURE", 0.6))
    MAX_AGENT_EPOCHS: int = int(os.environ.get("MAX_AGENT_EPOCHS", 100))
    LLM_TOP_P: float = float(os.environ.get("LLM_TOP_P", 0.9))
    LLM_TOP_K: int = int(os.environ.get("LLM_TOP_K", 20))
    REMINDER_TOKEN_RATIO: float = float(os.environ.get("REMINDER_TOKEN_RATIO", 0.8))
    MAX_TOKEN_LEN: int = int(os.environ.get("MAX_TOKEN_LEN", 128000))
    def __getitem__(self, key):
        return getattr(self, key)


class Config(BaseModel):
    docker: bool = Field(..., alias="docker")

    @field_validator("docker", mode="before")
    def convert_docker_flag(cls, v):
        return bool(int(v))

    ACIARGs: ACIVariables = Field(..., alias="aci_variables")
    LLMARGs: LLMArgs = Field(default_factory=LLMArgs, alias="llm_args")

    def get_aci_variables(self) -> dict[str, Any]:
        return self.ACIARGs.model_dump()


if os.environ.get("CONFIG_FILE"):
    CONFIG_FILE = os.environ["CONFIG_FILE"]
else:
    CONFIG_FILE = os.path.join(Path(_script_dir).parent.parent, "config.yaml")

if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as file:
        yaml_data = yaml.safe_load(file)
    CONFIG = Config(**yaml_data)
else:
    print(f"Configuration file not found: {CONFIG_FILE}", file=sys.stderr)
    sys.exit(-1)


CMD_TIMEOUT_WHITELIST = ["run_and_check_build_script", "run_fuzz_target"]
WHITELIST_CMD_TIMEOUT = CONFIG.ACIARGs.WHITELIST_CMD_TIMEOUT

def get_agent_addresses():
    addresses = []
    agents = ["BuilderAgent", "DictionaryAgent", "SeedAgent", "HarnessAgent", "FuzzerExecutorAgent", "CrashAnalyzerAgent", "CoverageAnalyzerAgent"]
    spec_location = ".well-know/agent.json"
    SRC_AGENT_PATH = os.path.join(Path(_script_dir).parent, "agents")
    for agent in agents:
        address = os.path.join(SRC_AGENT_PATH, agent)
        address = os.path.join(address, spec_location)
        if not os.path.exists(address):
            raise Exception(f"file {address} not found!")
        addresses.append(address)
    return addresses
