from src.agents.base_agent.agent import BaseAgent
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.utils.llm import ToolCall
from src.utils.log import get_logger
from .prompt import SYSTEM_PROMPT, NO_COVERAGE_GUIDANCE_SYSTEM_PROMPT
from typing import override
from typing import List
from src.tools.APIToolCall import API_TOOL_CALLS
import logging
from src.utils.config import CONFIG

class HarnessAgent(BaseAgent):
    logger = get_logger("Harness Agent")
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
            "compile_and_check_harness",
            "search_web",
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
        self.logger.log(level=logging.INFO, msg="Harness Generator Agent Initialized.")

    @override
    def format_system_prompt(self) -> str:
        if CONFIG.ACIARGs.DISABLE_COVERAGE_GUIDANCE:
            return NO_COVERAGE_GUIDANCE_SYSTEM_PROMPT
        else:
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
        compile_tool_count = len(list(filter(lambda x: x.function_call == "compile_and_check_harness", self.tool_calls)))
        if compile_tool_count == 0:
            reminder_message = f"This is a reminder message from user.\n"
            reminder_message += f"No compile and check harness tool call found. Please make sure you have called the tool `compile_and_check_harness` to compile and check the harness.\n"
            self.history_processor.extend_user_msg(content=reminder_message)
            return False
        last_compile_tool_call = 0
        for i,tool_call in enumerate(self.tool_calls):
            if tool_call.function_call == "compile_and_check_harness":
                last_compile_tool_call = i
        for tool_call in self.tool_calls[last_compile_tool_call:]:
            if tool_call.function_call in ["edit", "write_file"]:
                reminder_message = f"This is a reminder message from user.\n"
                reminder_message += f"Found harness editing after the last `compile_and_check_harness` tool call. Please make sure you have called the tool `compile_and_check_harness` to compile the harness after each editing.\n"
                self.history_processor.extend_user_msg(content=reminder_message)
                return False
        return True