from src.agents.base_agent.agent import BaseAgent
from src.utils.llm import ToolCall
from src.utils.log import get_logger
from .prompt import SYSTEM_PROMPT
from typing import override
from typing import List
from src.tools.APIToolCall import API_TOOL_CALLS
import logging


class BuilderAgent(BaseAgent):
    logger = get_logger("Builder Agent")
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
            "run_and_check_build_script",
            "search_web",
            "bash",
            "exit"
        ]
    )

    def __init__(self):
        super().__init__()
        self.system_prompt = self.format_system_prompt()
        self.logger.log(level=logging.INFO, msg="Builder Agent Initialized.")

    @override
    def format_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @override
    def register_agent_pre_call(self):
        self.tool_calls = []

    @override
    def execute_tool_calling(self, tool_call: ToolCall) -> str:
        self.tool_calls.append(tool_call)
        return self.aci.execute_tool_calling(tool_call)
    
    @override
    def is_agent_task_completed(self) -> bool:
        build_tool_count = len(list(filter(lambda x: x.function_call == "run_and_check_build_script", self.tool_calls)))
        if build_tool_count == 0:
            reminder_message = f"This is a reminder message from user.\n"
            reminder_message += f"No build script running tool call found. Please make sure you have called the tool `run_and_check_build_script` to run and check the build script.\n"
            self.history_processor.extend_user_msg(content=reminder_message)
            return False
        last_build_tool_call = 0
        for i,tool_call in enumerate(self.tool_calls):
            if tool_call.function_call == "run_and_check_build_script":
                last_build_tool_call = i
        for tool_call in self.tool_calls[last_build_tool_call:]:
            if tool_call.function_call in ["edit", "write_file"]:
                reminder_message = f"This is a reminder message from user.\n"
                reminder_message += f"Found build script editing after the last `run_and_check_build_script` tool call. Please make sure you have called the tool `run_and_check_build_script` to run and check the build script after each editing.\n"
                self.history_processor.extend_user_msg(content=reminder_message)
                return False
        return True