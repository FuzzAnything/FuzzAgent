from src.agents.base_agent.agent import BaseAgent
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.utils.log import get_logger
from .prompt import SYSTEM_PROMPT
from typing import override
from typing import List
from src.tools.APIToolCall import API_TOOL_CALLS
import logging

class CrashAnalyzerAgent(BaseAgent):
    logger = get_logger("Crash Analyzer Agent")
    tools: List[dict] = API_TOOL_CALLS.get_tool_calls(
        [
            "find_file",
            "search_file",
            "search_dir",
            "open",
            "goto",
            "edit",
            "write_file",
            "scroll_up",
            "scroll_down",
            "crash_artifact_analysis",
            "crash_debugger",
            "generate_crash_report",
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
        self.logger.log(level=logging.INFO, msg="Crash Analyzer Agent Initialized.")

    @override
    def format_system_prompt(self) -> str:
        return SYSTEM_PROMPT


