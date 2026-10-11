RESPONSE_FORMAT_PROMPT = """
# Response Format
Your response must follow the following format:
- **Reasoning**: Reasoning about the feedback from the system (should be concise).
- **Thought**: Provide the strategy to achieve the goal (should be concise).
- **Action**: What you want to do next. (should be concise)

--- BEGIN OF EXAMPLE ---
**Reasoning**: The last function call get the location of source code directory.
**Thought**: First, I will check source directory contents.
**Action**: I will call the `bash` function to check source directory contents.
--- END OF EXAMPLE ---
"""


TOOL_CALL_RESPONSE_PROMPT = """
<TOOL_CALL>
system$ {COMMAND}
</TOOL_CALL>

<OBSERVATION> 
{OBSERVATION}
</OBSERVATION>
(Open file: {OPEN_FILE})
(Current directory: {WORKING_DIR})
(SRC: {SRC})
(OUTPUT: {OUTPUT})

**ACTION PLANNING**: Based on the current observation from the previous action, provide reasoning and select the appropriate next action to continue your task.
"""

FRIST_ACTION_PLANNING_PROMPT = """
Base on the previous interaction with the system, plan the next action you want to take. Your response must exactly follow the following format (without any other text):
- **Reasoning**: Reasoning about the feedback from the system (should be concise).
- **Thought**: Provide the strategy to achieve the goal (should be concise).
- **Action**: What you want to do next. (should be concise).

--- BEGIN OF EXAMPLE ---
**Reasoning**: The last function call get the location of source code directory.
**Thought**: First, I will check source directory contents.
**Action**: I will call the `bash` function to check source directory contents.
--- END OF EXAMPLE ---
"""

NEXT_ACTION_PLANNING_PROMPT = """
Base on the previous interaction with the system, plan the next action you want to take. Your response must exactly follow the following format (without any other text):
- **Reasoning**: Reasoning about the feedback from the system (should be concise).
- **Thought**: Provide the strategy to achieve the goal (should be concise).
- **Action**: What you want to do next. (should be concise).
"""

AGENET_DESCRIPTION_PROMPT = """
# Agent Team Members
You are the manager of the agent team. You can coordinate the agent team to achieve your goal. The following is the description of the agent team members:
{AGENTS}
"""