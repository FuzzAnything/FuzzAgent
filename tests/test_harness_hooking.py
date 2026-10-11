from dotenv import load_dotenv
load_dotenv()
from src.agents.HarnessAgent.agent import HarnessAgent
from src.utils.llm import ToolCall
import pytest


def mock_tool_call(tool_name: str = "", tool_id: str ="", arguments = {}):
    return ToolCall(function_call=tool_name, function_call_id= tool_id, arguments=arguments)

def test_harness_hooking():
    harness_agent = HarnessAgent()
    harness_agent.register_agent_pre_call()
    open_tool_call = mock_tool_call("open", "123", {"path": "test.txt"})
    harness_agent.execute_tool_calling(open_tool_call)
    assert len(harness_agent.tool_calls) == 1


def test_harness_complete():
    harness_agent = HarnessAgent()
    harness_agent.register_agent_pre_call()
    compile_tool_call = mock_tool_call("compile_and_check_harness", "123", {"harness_id": 0})
    harness_agent.execute_tool_calling(compile_tool_call)
    assert len(harness_agent.tool_calls) == 1
    assert harness_agent.is_agent_task_completed() == True

def test_last_compile_id():
    harness_agent = HarnessAgent()
    harness_agent.register_agent_pre_call()

    # 0
    compile_tool_call = mock_tool_call("compile_and_check_harness", "123", {"harness_id": 0})
    harness_agent.execute_tool_calling(compile_tool_call)

    # 1
    compile_tool_call = mock_tool_call("compile_and_check_harness", "123", {"harness_id": 0})
    harness_agent.execute_tool_calling(compile_tool_call)

    # 2
    compile_tool_call = mock_tool_call("compile_and_check_harness", "123", {"harness_id": 0})
    harness_agent.execute_tool_calling(compile_tool_call)
    assert len(harness_agent.tool_calls) == 3
    assert harness_agent.is_agent_task_completed() == True


def test_harness_editing_complete():
    harness_agent = HarnessAgent()
    harness_agent.register_agent_pre_call()

    # 0
    compile_tool_call = mock_tool_call("write_file", "123", {"path": "/tmp/test.c", "content": "int main() { return 0; }"})
    harness_agent.execute_tool_calling(compile_tool_call)

    # 1
    compile_tool_call = mock_tool_call("compile_and_check_harness", "123", {"harness_id": 0})
    harness_agent.execute_tool_calling(compile_tool_call)

    assert len(harness_agent.tool_calls) == 2
    assert harness_agent.is_agent_task_completed() == True

def test_harness_editing_not_complete():
    harness_agent = HarnessAgent()
    harness_agent.register_agent_pre_call()

    # 0
    compile_tool_call = mock_tool_call("compile_and_check_harness", "123", {"harness_id": 0})
    harness_agent.execute_tool_calling(compile_tool_call)

    # 1
    compile_tool_call = mock_tool_call("write_file", "123", {"path": "/tmp/test.c", "content": "int main() { return 0; }"})
    harness_agent.execute_tool_calling(compile_tool_call)

    assert len(harness_agent.tool_calls) == 2
    assert harness_agent.is_agent_task_completed() == False

if __name__ == "__main__":
    test_harness_hooking()
    test_harness_complete()
    test_last_compile_id()
    test_harness_editing_complete()
    test_harness_editing_not_complete()