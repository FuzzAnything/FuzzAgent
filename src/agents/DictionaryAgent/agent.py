from src.agents.base_agent.agent import BaseAgent
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.utils.log import get_logger
from .prompt import SYSTEM_PROMPT
from typing import override
from typing import List
from src.tools.APIToolCall import API_TOOL_CALLS
import logging
from src.utils.project import get_project_cache_dir
import os
import json

class DictionaryAgent(BaseAgent):
    logger = get_logger("Dictionary Agent")
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
            "validate_dictionary_file",
            "track_web_retrieve_progress",
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
        self.logger.log(level=logging.INFO, msg="Dictionary Agent Initialized.")

    @override
    def format_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_web_retrieve_progress_path(self) -> str:
        progress_file_path = os.path.join(get_project_cache_dir(), "dictionary_progress.json")
        return progress_file_path
        
    @override
    def register_agent_pre_call(self):
        progress_file_path = self.get_web_retrieve_progress_path()
        if os.path.exists(progress_file_path):
            with open(progress_file_path, "r") as f:
                project_progress = json.load(f)
            waiting_projects = []
            for project_name, progress in project_progress.items():
                if progress == "incomplete":
                    waiting_projects.append(project_name)
            if len(waiting_projects) > 0:
                reminder_message = f"This is a reminder message from user.\n"
                reminder_message += f"Found {len(waiting_projects)} projects waiting for dictionary retrieval after previous execution. Here is the web retrieve progress:\n"
                for project_name, progress in project_progress.items():
                    reminder_message += f"    - {project_name}: {progress}\n"
                reminder_message += f"Please continue the dictionary retrieval for the projects.\n"
                self.history_processor.extend_user_msg(content=reminder_message)
    
    @override
    def is_agent_task_completed(self) -> bool:
        progress_file_path = self.get_web_retrieve_progress_path()
        if not os.path.exists(progress_file_path):
            reminder_message = f"This is a reminder message from user.\n"
            reminder_message += f"No web retrieve progress file found. Please make sure you have recorded the web retrieve progress using the tool `track_web_retrieve_progress`.\n"
            self.history_processor.extend_user_msg(content=reminder_message)
            return False
        with open(progress_file_path, "r") as f:
            project_progress = json.load(f)
        waiting_projects = []
        for project_name, progress in project_progress.items():
            if progress == "incomplete":
                waiting_projects.append(project_name)
        if len(waiting_projects) > 0:
            reminder_message = f"This is a reminder message from user.\n"
            reminder_message += f"Found {len(waiting_projects)} projects waiting for dictionary retrieval after previous execution. Here is the web retrieve progress:\n"
            for project_name, progress in project_progress.items():
                reminder_message += f"    - {project_name}: {progress}\n"
            reminder_message += f"Please continue the dictionary retrieval for the projects.\n"
            self.history_processor.extend_user_msg(content=reminder_message)
            return False
        return True