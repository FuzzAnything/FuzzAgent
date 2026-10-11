import os
from typing import List
from src.agents.base_agent.agent import BaseAgent
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.utils.log import get_logger
from .prompt import SYSTEM_PROMPT
from typing import override
from src.tools.APIToolCall import API_TOOL_CALLS
from src.utils.project import get_project_coverage_guidance_dir, get_fuzzer_profile, FuzzerExecutionState
import logging


class CoverageAnalyzerAgent(BaseAgent):
    logger = get_logger("Coverage Analyzer Agent")
    tools: List[dict] = API_TOOL_CALLS.get_tool_calls(
        [
            "open",
            "goto",
            "scroll_up", 
            "scroll_down",
            "find_file",
            "show_overview_code_coverage",
            "show_module_code_coverage",
            "show_file_code_coverage",
            "show_api_code_coverage",
            "show_func_code_coverage",
            "show_branch_blocker_code_coverage",
            "call_chain_analysis",
            "generate_coverage_guidance_report",
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
        self.logger.log(level=logging.INFO, msg="Coverage Analyzer Agent Initialized.")

    @override
    def format_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def no_fuzzer_in_plateau(self) -> bool:
        fuzz_profile = get_fuzzer_profile()
        for _, fuzz_info in fuzz_profile.fuzzers.items():
            if fuzz_info.state == FuzzerExecutionState.PLATEAU:
                return True
        return False
    
    def get_fuzzer_info(self) -> str:
        fuzz_profile = get_fuzzer_profile()
        info = ""
        for _, fuzz_info in fuzz_profile.fuzzers.items():
            info += f"Fuzzer {fuzz_info.fuzzer_id:03d} is in state {fuzz_info.state.value}.\n"
        return info
    
    @override
    def register_agent_pre_call(self):
        self.can_return_early = False
        if self.no_fuzzer_in_plateau():
            self.can_return_early = True
            fuzzer_info = self.get_fuzzer_info()
            reminder = f"Here is the fuzzer stats:\n{fuzzer_info}\nBut you did not find any fuzzer in plateau state and is able to extract code coverage. Please directly exit and report this issue to let HarnessAgent or FuzzerAgent to continue."
            self.history_processor.extend_user_msg(content=reminder)
            return
        coverage_guidance_dir = get_project_coverage_guidance_dir()
        self.coverage_guidance_files = [file for file in os.listdir(coverage_guidance_dir) if file.startswith("harness_") and file.endswith("_guidance.md")]


    @override
    def is_agent_task_completed(self) -> bool:
        if self.can_return_early:
            return True
        coverage_guidance_dir = get_project_coverage_guidance_dir()
        current_files = [file for file in os.listdir(coverage_guidance_dir) if file.startswith("harness_") and file.endswith("_guidance.md")]
        new_files = set(current_files) - set(self.coverage_guidance_files)
        
        if len(new_files) == 0:
            reminder = f"As a Coverage Analyzer Agent, you are responsible for analyzing the code coverage of the project and generating coverage guidance. But you did not record any new coverage guidance by using the tool `generate_coverage_guidance_report`. Please generate a coverage analysis report before exiting."
            self.history_processor.extend_user_msg(content=reminder)
            return False
        return True  

    @override
    def register_agent_post_call(self, exit_reason: str) -> str:
        if self.can_return_early:
            return exit_reason + "\n[*] No fuzzer in plateau state and is able to extract code coverage. Please directly exit and report this issue to let HarnessAgent or FuzzerAgent to continue."
        coverage_guidance_dir = get_project_coverage_guidance_dir()
        current_files = [file for file in os.listdir(coverage_guidance_dir) if file.startswith("harness_") and file.endswith("_guidance.md")]
        new_files = set(current_files) - set(self.coverage_guidance_files)
        if len(new_files) == 0:
            return exit_reason + "\n[*] No new coverage guidance files recorded in this round of analysis."
        new_file = new_files.pop()
        file_path = os.path.join(coverage_guidance_dir, new_file)
        return exit_reason + f"\n[*] New coverage guidance files recorded in: [{file_path}]. Please delegate this guidance to the HarnessAgent to generate the next harness."
