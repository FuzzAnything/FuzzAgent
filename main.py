from dotenv import load_dotenv
import subprocess
import argparse
import os
import logging
load_dotenv(".env") # Load environment variables before importing other modules
subprocess.run(["/bin/bash", os.path.join(os.path.dirname(__file__), "src/tools/copy_tools.sh")], check=True)
from src.agents.ManagerAgent.agent import ManagerAgent
from src.utils.config import get_agent_addresses
from src.utils.config import CONFIG
from src.agents.ManagerAgent.prompt import INITIAL_INPUT_MESSAGE


# Set logging level for dependencies to critical
openai_logger = logging.getLogger('openai')
openai_logger.setLevel(logging.CRITICAL)

http_logger = logging.getLogger('httpcore')
http_logger.setLevel(logging.CRITICAL)

httpx_logger = logging.getLogger('httpx')
httpx_logger.setLevel(logging.CRITICAL)

if __name__ == "__main__":        
    manager = ManagerAgent(agent_addresses=get_agent_addresses())
    user_input = INITIAL_INPUT_MESSAGE
    while True:
        manager.run(user_input)

