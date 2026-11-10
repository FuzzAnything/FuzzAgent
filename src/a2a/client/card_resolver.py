# Contains code from Google Agent2Agent samples (Apache-2.0).
# Adapted for FuzzAgent.
# See THIRD_PARTY_NOTICES and THIRD_PARTY_LICENSES/Apache-2.0.txt.

import httpx
from src.a2a.types import (
    AgentCard,
    A2AClientJSONError,
)
import json


class A2ACardResolver:
    def __init__(self, agent_card_path):
        self.agent_card_path = agent_card_path

    def get_agent_card(self) -> AgentCard:
        with open(self.agent_card_path, "r") as f:
            spec = json.load(f)
        return AgentCard(**spec)
