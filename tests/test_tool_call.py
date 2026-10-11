from src.utils.aci import ACI
from src.utils.llm import ToolCall
from src.utils.log import get_logger


def mock_tool_call(tool_name: str = "", tool_id: str ="", arguments = {}):
    return ToolCall(function_call=tool_name, function_call_id= tool_id, arguments=arguments)


def test_tool_call():
    aci = ACI(logger=get_logger(__name__))
    tool_call = mock_tool_call(tool_name="bash", tool_id="123", arguments={"command": "echo 'Hello, World!'"})
    result = aci.execute_tool_calling(tool_call)
    assert result is not None
    assert result.strip() == "Command executed with exit code 0.\nHello, World!"
