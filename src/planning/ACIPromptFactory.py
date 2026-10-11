from src.planning.prompt import (
    NEXT_ACTION_PLANNING_PROMPT,
    AGENET_DESCRIPTION_PROMPT,
    TOOL_CALL_RESPONSE_PROMPT
)
from typing import List
from src.a2a.types import AgentCard

from src.utils.project import get_project_source_dir, get_project_output_dir

class ACIPromptFactory:
    def __init__(
        self, agents: List[AgentCard]
    ):
        self.agents = agents


    def get_agent_cards_description(self) -> str:
        """Get a description of the agent cards."""
        agents_description = ""
        for agent in self.agents:
            description = agent.get_agent_description()
            agents_description += f"{description}\n\n"
        return agents_description

    def create_available_agents_prompt(self) -> str:
        if self.agents is None or len(self.agents) == 0:
            return ""
        return AGENET_DESCRIPTION_PROMPT.format(AGENTS=self.get_agent_cards_description())

    
    def create_tool_call_response_prompt(self, observation: str, open_file: str, working_dir: str, command: str) -> str:
        return TOOL_CALL_RESPONSE_PROMPT.format(
            OBSERVATION=observation,
            OPEN_FILE=open_file,
            WORKING_DIR=working_dir,
            COMMAND=command,
            SRC=get_project_source_dir(),
            OUTPUT=get_project_output_dir()
        )
    
    def check_response_format(self, response: str) -> bool:
        return response.find("Reasoning") != -1 and response.find("Thought") != -1 and response.find("Action") != -1

