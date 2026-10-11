import os
from openai import OpenAI
from abc import ABC, abstractmethod
from src.utils.config import CONFIG
from src.memory.summarizer import AgentSummarizer
from typing import List
from src.planning.ACIPromptFactory import ACIPromptFactory
from src.memory.history_processor import HistoryProcessor
from src.utils.llm import query_llm
from src.utils.aci import ACI, InvalidResponseFormatError
from src.utils.log import get_logger
from src.utils.project import PROJECT_VMS
from src.utils.llm import ToolCall, TokenLenExceed, TokenLenWillExceed
from src.tools.APIToolCall import API_TOOL_CALLS
from src.planning.prompt import NEXT_ACTION_PLANNING_PROMPT, RESPONSE_FORMAT_PROMPT, FRIST_ACTION_PLANNING_PROMPT
import traceback


class BaseAgent(ABC):
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"), base_url=CONFIG.LLMARGs["OPENAI_API_BASE"]
    )
    logger = get_logger("Base Agent")
    aci = ACI(logger)

    system_prompt: str = "You are a helpful assistant."
    tools: List[dict] = API_TOOL_CALLS.get_tool_calls(["exit", "bash"])
    exit_reason = "Normal Exit"
    prompt_factory = ACIPromptFactory(
        agents=[]
    )
    MAX_AGENT_EPOCHS = CONFIG.LLMARGs.MAX_AGENT_EPOCHS

    def __init__(self):
        self.summarizer = AgentSummarizer()
        self.history_processor = HistoryProcessor(logger=self.logger)

    def get_agent_name(self) -> str:
        """Get Agent name"""
        return self.__class__.__name__

    def format_message(self, input_msg: str):
        message = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": input_msg},
        ]
        return message

    def get_system_prompt(self) -> str:
        return self.format_system_prompt() + RESPONSE_FORMAT_PROMPT

    @abstractmethod
    def format_system_prompt(self) -> str:
        return ""

    def format_next_step_prompt(self) -> str:
        return NEXT_ACTION_PLANNING_PROMPT
    
    def format_tool_call_response_prompt(self, observation: str, tool_call: ToolCall) -> str:
        return self.prompt_factory.create_tool_call_response_prompt(
            observation=observation,
            open_file=self.aci.open_file,
            working_dir=self.aci.working_dir,
            command=self.aci.convert_tool_call_to_command(tool_call),
        )

    def execute_tool_calling(self, tool_call: ToolCall) -> str:
        return self.aci.execute_tool_calling(tool_call)

    def handle_agent_action(self, tool_args: dict) -> str:
        return ""
        
    def register_agent_pre_call(self):
        pass

    def register_agent_post_call(self, exit_reason: str) -> str:
        return exit_reason

    def is_agent_task_completed(self) -> bool:
        return True

    def handle_token_will_exceed(self, current_len: int, max_len: int):
        self.logger.warning(f"Token length will exceed! Current: {current_len}, Max allowed: {max_len}. Generating summary to reduce token length.")
        reminder_messages = "[IMPORTANT!][WARNING!] This is a reminder message from the user. The system detected that the current token length is approaching the maximum limit.\n"
        reminder_messages += f"[IMPORTANT!][WARNING!] Token length will exceed! Current: {current_len}, Max allowed: {max_len}.\n"
        reminder_messages += "[IMPORTANT!][WARNING!] To ensure smooth operation, please summarize the previous conversation concisely right now, focusing on key points and important information only.\n"
        reminder_messages += "[IMPORTANT!][WARNING!] Then directly invoke the 'exit' tool call with the summary as the argument to terminate the agent execution!\n"
        self.history_processor.extend_user_msg(content=reminder_messages)
    
    def handle_token_exceed(self, current_len: int, max_len: int):
        self.logger.error(f"[!] ERROR:Token length exceeded! Current: {current_len}, Max allowed: {max_len}. Terminating agent execution.")
        self.exit_reason = f"Token length exceeded! Current: {current_len}, Max allowed: {max_len}. The agent execution is forced to be terminated."

    def is_force_exit(self, arguments: dict) -> bool:
        return arguments.get("force", False)

    def run(self, input_msg: str):
        self.logger.debug(msg=f"System prompt: {self.get_system_prompt()}")
        self.logger.info(msg=f"User input: {input_msg}")

        # Get historical summaries for the target agent
        #historical_context = self.summarizer.format_history_for_agent(self.get_agent_name(), max_count=3)
        #if historical_context:
        #    input_msg = historical_context + input_msg
            
        epoch = 0
        observation = ""
        message = self.format_message(input_msg)
        self.history_processor.set_messages(message)
        self.register_agent_pre_call()
        #self.history_processor.extend_user_msg(content=FRIST_ACTION_PLANNING_PROMPT)

        while epoch < self.MAX_AGENT_EPOCHS:
            self.logger.info(msg=f"Epoch: {epoch}")
            response_text = ""
            tool_call = None
            out_messages = None
            try:
                response_text, tool_call, out_messages = query_llm(
                    client=self.client,
                    messages=self.history_processor.get_messages(),
                    tools=self.tools,
                    logger=self.logger,
                    tool_choice="auto"
                )
            except TokenLenWillExceed as e:
                self.handle_token_will_exceed(e.current_len, e.max_len)
                epoch += 1
                continue
            except TokenLenExceed as e:
                self.handle_token_exceed(e.current_len, e.max_len)
                break

            if out_messages is not None:
                self.history_processor.append_raw_messages(messages=out_messages)

            tool_reply_added = False
            try:
                if tool_call is not None:
                    function_call, arguments = tool_call.function_call, tool_call.arguments
                    if function_call == "send_agent_task":
                        observation = self.handle_agent_action(arguments)
                    elif function_call == "exit":
                        if self.is_force_exit(arguments):
                            self.exit_reason = self.register_agent_post_call(exit_reason=str(arguments))
                            self.logger.info(msg=f"Agent forced to exit with exit reason: {self.exit_reason}")
                            break
                        if not self.is_agent_task_completed():
                            continue
                        self.exit_reason = self.register_agent_post_call(exit_reason=str(arguments))
                        self.logger.info(msg=f"Agent exit reason: {self.exit_reason}")
                        break
                    else:
                        observation = self.execute_tool_calling(tool_call)
                    next_step_prompt = self.format_tool_call_response_prompt(observation=observation, tool_call=tool_call)
                    self.history_processor.extend_function_call_msg(content=next_step_prompt, name=tool_call.function_call, id=tool_call.function_call_id)
                    tool_reply_added = True
                next_step_prompt = self.format_next_step_prompt()
                self.history_processor.extend_user_msg(content=next_step_prompt)

                if not response_text and not tool_call:
                    raise InvalidResponseFormatError()

            except Exception as e:
                error_type = type(e).__name__
                error_message = str(e)
                observation = f"Error: {error_type} {error_message}\n{traceback.format_exc()}"
                # If the assistant message already carried tool_calls (appended above) but
                # we haven't added a matching tool reply yet, add one now to keep the
                # history balanced. Skip if already added (e.g. exception happened after
                # extend_function_call_msg succeeded).
                if not tool_reply_added and out_messages is not None and getattr(out_messages, "tool_calls", None):
                    tc = out_messages.tool_calls[0]
                    self.history_processor.extend_function_call_msg(content=observation, name=tc.function.name, id=tc.id)
                elif not tool_reply_added and tool_call is not None:
                    self.history_processor.extend_function_call_msg(content=observation, name=tool_call.function_call, id=tool_call.function_call_id)
                else:
                    self.history_processor.extend_user_msg(content=observation)
            epoch += 1


        # Terminate the bash subprocess
        #self.aci.kill_process_tree(self.aci.bash_subprocess)

        if epoch >= self.MAX_AGENT_EPOCHS:
            self.exit_reason = "The agent has reached the maximum number of epochs. End of the agent execution."
        # Generate and save summary after execution ends
        #self.summarizer.generate_and_save_summary(agent_name=self.get_agent_name(), original_input=input_msg, exit_reason=self.exit_reason, conversation_history=self.history_processor.get_messages())
        id, hash = PROJECT_VMS.create_snapshot(self.get_agent_name())
        self.logger.info(msg=f"Snapshot created: {id} {hash}")
        return self.exit_reason
    
