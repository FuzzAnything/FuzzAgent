from typing import List, Optional, Callable
from src.a2a.client import A2ACardResolver
from src.a2a.types import (
    AgentCard
)
from src.agents.base_agent.agent import BaseAgent
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.utils.log import get_logger
from .prompt import NO_COVERAGE_GUIDANCE_SYSTEM_PROMPT, SYSTEM_PROMPT
from typing import override
from typing import List
import logging
from src.agents.BuilderAgent.agent import BuilderAgent
from src.agents.HarnessAgent.agent import HarnessAgent
from src.agents.FuzzerExecutorAgent.agent import FuzzerExecutorAgent
from src.agents.CrashAnalyzerAgent.agent import CrashAnalyzerAgent
from src.agents.DictionaryAgent.agent import DictionaryAgent
from src.agents.SeedAgent.agent import SeedAgent
from src.agents.CoverageAnalyzerAgent.agent import CoverageAnalyzerAgent
from src.tools.APIToolCall import API_TOOL_CALLS
from src.utils.config import CONFIG
class ManagerAgent(BaseAgent):
    logger = get_logger("Manager Agent")
    tools: List[dict] = API_TOOL_CALLS.get_tool_calls(
        [
            "open",
            "goto",
            "scroll_up",
            "scroll_down",
            "observe_current_states",
            "bash",
            "send_agent_task"
        ]
    )
    MAX_TOOL_CALL_TIMES = 10
    MAX_AGENT_EPOCHS = 100

    def __init__(self, agent_addresses: List[str]):
        super().__init__()
        self.logger.log(level=logging.INFO, msg="Manager Agent Initialized.")
        self.cards: dict[str, AgentCard] = self.resolve_agent_cards(agent_addresses)
        self.agents = self.list_agents()
        self.class_map = {
            "BuilderAgent": BuilderAgent(),
            "HarnessAgent": HarnessAgent(),
            "FuzzerExecutorAgent": FuzzerExecutorAgent(),
            "CrashAnalyzerAgent": CrashAnalyzerAgent(),
            "DictionaryAgent": DictionaryAgent(),
            "SeedAgent": SeedAgent(),
            "CoverageAnalyzerAgent": CoverageAnalyzerAgent(),
        }
        if CONFIG.ACIARGs.DISABLE_COVERAGE_GUIDANCE:
            self.class_map = {
                "BuilderAgent": BuilderAgent(),
                "HarnessAgent": HarnessAgent(),
                "FuzzerExecutorAgent": FuzzerExecutorAgent(),
                "CrashAnalyzerAgent": CrashAnalyzerAgent(),
                "DictionaryAgent": DictionaryAgent(),
                "SeedAgent": SeedAgent(),
            }
            self.agents = [agent for agent in self.agents if agent.name != "CoverageAnalyzerAgent"]
            
        self.prompt_factory = ACIPromptFactory(
             agents=self.agents,
        )

    def resolve_agent_cards(self, agent_addresses: List[str]) -> dict[str, AgentCard]:
        """Resolve agent cards from the given addresses."""
        cards = {}
        for address in agent_addresses:
            card_resolver = A2ACardResolver(address)
            card = card_resolver.get_agent_card()
            cards[card.name] = card
        return cards

    def list_agent_names(self) -> List[str]:
        """List the names of the available agents."""
        return list(self.cards.keys())

    def list_agents(self) -> List[AgentCard]:
        """List the names of the available agents."""
        return list(self.cards.values())

    @override
    def format_system_prompt(self) -> str:
        if CONFIG.ACIARGs.DISABLE_COVERAGE_GUIDANCE:
            return NO_COVERAGE_GUIDANCE_SYSTEM_PROMPT + self.prompt_factory.create_available_agents_prompt()
        else:
            return SYSTEM_PROMPT + self.prompt_factory.create_available_agents_prompt()

    @override
    def register_agent_pre_call(self):
        command = "observe_current_states"
        observation = self.aci.run_command_with_timeout(command, timeout=120, max_output_lines=200)
        message = f"This is the current states of the fuzzing tasks:\n{observation}"
        self.history_processor.extend_user_msg(content=message)

    @override
    def handle_agent_action(self, tool_args: dict) -> str:
        agent_name = tool_args.get("agent_name")
        if not agent_name:
            raise ValueError("You must specify the agent name to send the task to.")
        task_description = tool_args.get("task_description")
        if not task_description:
            raise ValueError("You must specify the task description to send to the agent.")
        
        agent = self.class_map.get(agent_name)
        if not agent:
            raise ValueError("The agent name: {} is not valid. The available agents are {}".format(agent_name, self.list_agent_names()))
        
        self.logger.info(msg=f"Sending Agent task: {agent_name}\nTask description: {task_description}")
        observation = agent.run(task_description)
        command = "observe_current_states"
        new_observation = self.aci.run_command_with_timeout(command, timeout=120, max_output_lines=200)
        message = f"This is the current states of the fuzzing tasks after the agent {agent_name} has completed its task:\n{new_observation}"
        return observation + "\n" + message

