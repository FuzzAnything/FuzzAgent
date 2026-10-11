from dotenv import load_dotenv
load_dotenv()
from src.tools.APIToolCall import API_TOOL_CALLS
from src.utils.llm import query_llm
from openai import OpenAI
import os
import json
from src.utils.config import CONFIG
from src.utils.log import get_logger
import pytest
logger = get_logger(__name__)

class TestLLM:

    @staticmethod
    def strip_llm_response(text: str):
        text = text.replace("```json", "").replace("```", "")
        return text.strip()

    @pytest.fixture(autouse=True)
    def setup_client(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=CONFIG.LLMARGs["OPENAI_API_BASE"])
        self.model = CONFIG.LLMARGs["OPENAI_MODEL"]
    
    def test_openai_client(self):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Calculate the sum of 1 and 1. Display the result in a JSON format with the key 'result'"}
            ],
            max_tokens=50
        )
        assert response
        assert response.choices
        assert response.choices[0]
        assert response.choices[0].message
        assert response.choices[0].message.content
        print(response.choices[0].message.content)
        content = self.strip_llm_response(response.choices[0].message.content)
        result = json.loads(content)
        print(result)
        assert result["result"] == 2, "The result should be 2"

    def test_llm_query(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=CONFIG.LLMARGs["OPENAI_API_BASE"])
        self.model = CONFIG.LLMARGs["OPENAI_MODEL"]
        messages = [
            {"role": "user", "content": "Calculate the sum of 1 and 1. Display the result in a JSON format with the key 'result'"}
        ]
        assert 1 + 1 == 2, "1 + 1 should be 2"
        response, _, _ = query_llm(self.client, messages, logger=logger, tool_choice="none")
        content = self.strip_llm_response(response)
        result = json.loads(content)
        print(result)
        assert result["result"] == 2, "The result should be 2"

    def test_llm_query_with_function_call(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=CONFIG.LLMARGs["OPENAI_API_BASE"])
        self.model = CONFIG.LLMARGs["OPENAI_MODEL"]
        messages = [
            {"role": "user", "content": "Calculate the sum of 11241 and 1356253. Display the result in a JSON format with the key 'result'"}
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculate_sum",
                    "description": "Calculate the sum of two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"]
                    }
                }
            },
        ]
        response, tool_call, _ = query_llm(self.client, messages, tools=tools, logger=logger, tool_choice="required")
        print(response)
        print(tool_call)
        assert tool_call is not None, "The tool call should not be None"
        assert tool_call.function_call == "calculate_sum", "The function call should be calculate_sum"
        assert tool_call.arguments == {"a": 11241, "b": 1356253}, "The arguments should be {'a': 11241, 'b': 1356253}"

    def test_llm_query_with_agent_tools(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=CONFIG.LLMARGs["OPENAI_API_BASE"])
        self.model = CONFIG.LLMARGs["OPENAI_MODEL"]
        messages = [
            {"role": "user", "content": "This is a simple test. Please randomly call a tool from the list of tools. The tool call will not be executed."}
        ]
        response, tool_call, _ = query_llm(self.client, messages, tools=API_TOOL_CALLS.tool_calls, logger=logger, tool_choice="required")
        assert tool_call is not None, "The tool call should not be None"
        print(tool_call.function_call)



if __name__ == "__main__":
    test = TestLLM()
    #test.setup_client()
    #test.test_openai_client()
    #test.test_llm_query()
    test.test_llm_query_with_function_call()
    test.test_llm_query_with_agent_tools()
