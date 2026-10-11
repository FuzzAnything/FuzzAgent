from src.agents.base_agent.agent import BaseAgent
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.utils.log import get_logger
from .prompt import SYSTEM_PROMPT
from typing import override
from typing import List
from src.tools.APIToolCall import API_TOOL_CALLS
import logging
import re


class FuzzerExecutorAgent(BaseAgent):
    logger = get_logger("Fuzzer Executor Agent")
    tools: List[dict] = API_TOOL_CALLS.get_tool_calls(
        [
            "find_file",
            "search_file",
            "search_dir",
            "write_file",
            "open",
            "goto",
            "edit",
            "scroll_up",
            "scroll_down",
            "run_fuzz_target",
            "exit",
            "bash"
        ]
    )

    def __init__(self):
        super().__init__()
        self.prompt_factory = ACIPromptFactory(
            agents=[]
        )
        self.system_prompt = self.format_system_prompt()
        self.logger.log(level=logging.INFO, msg="Fuzzer Executor Agent Initialized.")

    @override
    def format_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def forbiden_fuzzer_run(self, action_input: str):
        pattern = re.compile(r"/fuzzer\s")
        if pattern.match(action_input):
            return True
        return False

