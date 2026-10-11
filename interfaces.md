# Interface Specification
The interfaces of **FuzzAgent** are implemented as a set of tools abstract the tasks in library fuzzing workflow. These interfaces shield agents from low-level complexity and expose high-level actions that map directly to library fuzzing tasks, allowing agents to focus on strategic decisions rather than brittle system operations.


## Computer-use Interface

This interface lets agents interact with the underlying file system and execution environment, mirroring the workflow of human fuzzing experts. It is divided into file-system operation tools, a general bash tool, and specialized fuzzing tools that encapsulate recurring high-level fuzzing procedures.

### File-system Operation Tools

These tools are adapted from SWE-Agent and tailored for library fuzzing, supporting robust and efficient file reading, writing, searching, and navigation within the fuzzing workspace.

```
tools:
  open:
    timeout: 30
    signature: open "<path>" [<line_number>]
    docstring: opens the file at the given path in the editor. If line_number is provided, the window will be move to include that line.
    arguments:
      - name: path
        type: string
        description: the path to the file to open
        required: true
      - name: line_number
        type: integer
        description: the line number to move the window to (if not provided, the window will start at the top of the file)
        required: false
  write_file:
    timeout: 30
    signature: |-
      write_file "<path>" << 'end_of_write'
      <content>
      end_of_write
    docstring: writes the given content to the given file. Make sure your indentation is formatted properly. If the file does not exist, it will be created. If the file exists, it will be overwritten. 
    arguments:
      - name: path
        type: string
        description: the path to the file to write to
        required: true
      - name: content
        type: string
        description: the content to write to the file. 
        required: true
        redirect: true
  goto:
    timeout: 30
    signature: goto <line_number>
    docstring: moves the window to show <line_number>
    arguments:
      - name: line_number
        type: integer
        description: the line number to move the window to
        required: true
  scroll_up:
    timeout: 30
    signature: scroll_up
    docstring: moves the window up {WINDOW} lines
  scroll_down:
    timeout: 30
    signature: scroll_down
    docstring: moves the window down {WINDOW} lines
  edit:
    timeout: 30
    signature: |-
      edit <start_line>:<end_line> [<file_path>] << 'end_of_edit'
      <replacement_text>
      end_of_edit
    docstring: replaces lines <start_line> through <end_line> (inclusive) with the given text in the specified file or the currently open file. All of the <replacement text> will be entered, so make sure your indentation is formatted properly. A backup file is automatically created in /tmp directory before editing, which can be used with undo_edit command.
    arguments:
      - name: start_line
        type: integer
        description: the line number to start the edit at
        required: true
      - name: end_line
        type: integer
        description: the line number to end the edit at (inclusive)
        required: true
      - name: file_path
        type: string
        description: the path to the file to edit (if not provided, uses the currently open file)
        required: false
      - name: replacement_text
        type: string
        description: the text to replace the current selection with
        required: true
        redirect: true
  undo_edit:
    timeout: 30
    signature: undo_edit
    docstring: undoes the last edit operation by restoring the file from the backup created in /tmp directory. This will revert the file to its state before the most recent edit command.
    arguments: []
  write_bin_to_file:
    timeout: 30
    signature: |-
      write_bin_to_file <path> << 'end_of_write_bin'
      <binary_string>
      end_of_write_bin
    docstring: writes the given binary string (as text, e.g. hex or base64) to the given file. If the file does not exist, it will be created. If the file exists, it will be overwritten. Supports hex (default) and base64 encoding via --encoding argument.
    arguments:
      - name: path
        type: string
        description: the path to the file to write to
        required: true
      - name: binary_string
        type: string
        description: the binary string to write to the file. 
        required: true
        redirect: true
      - name: encoding
        type: string
        description: "encoding of the input string (`hex` or `base64`, default: `hex`)"
        required: false
  search_dir:
    timeout: 30
    signature: search_dir <search_term> [<dir>]
    docstring: searches for search_term in all files in dir. If dir is not provided, searches in the current directory.
    arguments:
      - name: search_term
        type: string
        description: the term to search for
        required: true
      - name: dir
        type: string
        description: the directory to search in
        required: false
  search_file:
    timeout: 30
    signature: search_file <search_term> [<file>]
    docstring: searches for search_term in file. If file is not provided, searches in the current open file
    arguments:
      - name: search_term
        type: string
        description: the term to search for
        required: true
      - name: file
        type: string
        description: the file to search in (if not provided, searches in the current open file)
        required: false
  find_file:
    timeout: 30
    signature: find_file <file_name> [<dir>]
    docstring: finds all files with the given name in dir. If dir is not provided, searches in the current directory
    arguments:
      - name: file_name
        type: string
        description: the name of the file to search for
        required: true
      - name: dir
        type: string
        description: the directory to search in
        required: false
```

### Bash Tools

A general-purpose shell execution tool for ad-hoc system operations not covered by the specialized tools. Agents are encouraged to prefer the dedicated file-system tools over equivalent shell commands for reliability.

```
tools:
  bash:
    timeout: 120
    signature: bash <command>
    docstring: Run a command to interact with the system.
    arguments:
      - name: command
        type: string
        description: The command to run to interact with the system. If you need to search one file/directory or read/edit file contents, __PLEASE USE THE PROVIDED FUNCTIONS (open, edit, find_file, goto, scroll_up, scroll_down, write_file, etc.)__ rather than Linux commands (e.g. cat, less, more, fine, head, tail, find, echo, etc.).
        required: true
```

### Specialized Fuzzing Tools

These tools encapsulate the error-prone recurring procedures in the fuzzing pipeline, each abstracting a full task sequence behind a single command.

```
tools:
  run_and_check_build_script:
    timeout: 7200
    signature: run_and_check_build_script <script_path>
    docstring: "Run the build script and verify the correct generation of build artifacts. This tool: 1. Automatically exports required environment variables (CC, CXX, CFLAGS, CXXFLAGS, WORK) to the build script's context. 2. Executes the build script to generate building artifacts with three kinds of instrumentation: LibFuzzer Engine (stored in 'basic/' subdirectory), Sanitizers (stored in 'sanitizer/' subdirectory) and Code coverage  (stored in 'coverage/' subdirectory)."
    arguments:
      - name: script_path
        type: string
        description: the path of the build script
        required: true
  validate_dictionary_file:
    signature: validate_dictionary_file "<dictionary_file>"
    docstring: Validate whether the format of the dictionary file is legal.
    arguments:
      - name: dictionary_file
        type: string
        description: The path of dictionary file you want to validate.
        required: true
  compile_and_check_harness:
    timeout: 1200
    signature: compile_and_check_harness <harness_id> [<extra_flags>]
    docstring: Compile the harness to fuzzers and check whether it contains compilation errors. The compiler flags for fuzzing is equipped internally.
    arguments:
      - name: harness_id
        type: integer
        description: The harness instance ID to compile. E.g., 000, 001, etc.
        required: true
      - name: extra_flags
        type: string
        description: The extra flags used to compile the harness. Provide it only if you encountered fatal compilation errors.
        required: false
  run_fuzz_target:
    timeout: 3900
    signature: run_fuzz_target <fuzzer_id>
    docstring: A custom wrapper to run a fuzz target with a specific fuzzer instance ID. It automatically loads the fuzzing corpus and dictionaries for the specified fuzzer instance and sets the appropriate arguments to run the fuzz target. You should always use this tool to run your fuzzers. If you use any other command to start a fuzzer, it will not be in the timeout whitelist, causing the fuzzer to run for only a very short time before exiting immediately.
    arguments:
      - name: fuzzer_id
        type: integer
        description: The fuzzer instance ID to run. E.g., 000, 001, etc.
        required: true
```



## Web Interface

This interface lets agents reach online resources when local knowledge is insufficient.
```
tools:
  search_web:
    timeout: 60
    max_output_lines: 1500
    signature: search_web <path>
    docstring: |
      Retrieves directory listings or file contents from the google/oss-fuzz repository. Enter the path to view the contents of the path.
    arguments:
      - name: path
        type: string
        description: |
          The relative path within the 'projects/' directory. 
          - To list all available projects, pass "list". 
          - To inspect a specific project, pass the project name (e.g., "zlib"). 
          - To read a file, pass the full path (e.g., "zlib/build.sh").
        required: true
  track_web_retrieve_progress:
    signature: track_web_retrieve_progress "<task_kind>" "<action>" "<project_names>"
    docstring: Record and track the web retrieve progress for the given task kind and project names. 
    arguments:
      - name: task_kind
        type: string
        enum: ["dictionary", "seed"]
        description: The task kind to track the web retrieve progress.
        required: true
      - name: action
        type: string
        enum: ["record_tasks", "complete_tasks"]
        description: The action to track the web retrieve progress.
        required: true
      - name: project_names
        type: string
        description: The project names to track the web retrieve progress. Use comma to separate multiple project names.
        required: true
```


## Coverage Analysis Interface

Inspired by FuzzIntrospector, this interface organizes code coverage data into a six-level hierarchy (project → module → file → API → internal function → branch), enabling the Coverage Analyzer Agent to pinpoint critical coverage gaps and derive concrete API invocation sequences that guide the generation of the next targeted harness.

```
tools:
  show_overview_code_coverage:
    timeout: 1200
    signature: show_overview_code_coverage
    docstring: Displays the overall code coverage statistics for the project.
  show_module_code_coverage:
    timeout: 1200
    signature: show_module_code_coverage <path> <page> [options]
    docstring: Displays the module-level code coverage statistics for the project.
    arguments:
      - name: path
        type: string
        description: The path to the module to show coverage for. In this tool, the default path is '/' representing the location of the project.
        required: true
      - name: page
        type: integer
        description: The page number to show coverage for. Defaults to 1.
        required: true
  show_file_code_coverage:
    timeout: 1200
    signature: show_file_code_coverage  <page> [options]
    docstring: Displays the file-level code coverage statistics for the project.
    arguments:
      - name: page
        type: integer
        description: The page number to show coverage for. Defaults to 1.
        required: true
  show_api_code_coverage:
    timeout: 1200
    signature: show_api_code_coverage <page> [options]
    docstring: Displays the API-level code coverage statistics for the project.
    arguments:
      - name: page
        type: integer
        description: The page number to show coverage for. Defaults to 1.
        required: true
  show_func_code_coverage:
    timeout: 1200
    signature: show_func_code_coverage <page> <search_func> [options]
    docstring: Displays the function-level code coverage statistics for the project.
    arguments:
      - name: page
        type: integer
        description: The page number to show coverage for. Defaults to 1.
        required: true
      - name: search_func
        type: string
        description: The function name to search (not regex), all matches will be displayed. Defaults to ''.
        required: false
  show_branch_blocker_code_coverage:
    timeout: 1200
    signature: show_branch_blocker_code_coverage
    docstring: Displays the branch blocker-level code coverage statistics for the project.
  call_chain_analysis:
    timeout: 1200
    signature: call_chain_analysis <target_func>
    docstring: Analyze the call graph to find the shortest call traces from public APIs to the target function. This help you understand how to reach the target function from public APIs.
    arguments:
      - name: target_func
        type: string
        description: The target function to analyze the call chain to.
        required: true
  generate_coverage_guidance_report:
    timeout: 10
    signature: generate_coverage_guidance_report <harness_id> <content>
    docstring: Generates a coverage analysis report for the next harness and save it to the coverage guidance directory.
    arguments:
      - name: harness_id
        type: integer
        description: The ID of the next harness to generate the coverage guide report for.
        required: true
      - name: content
        type: string
        description: The content of the coverage analysis report.
        required: true
        redirect: true
```

## Crash Debugging Interface

This interface supports evidence-based crash triage. It enables the Crash Analyzer Agent to distinguish genuine library bugs from harness-induced false positives through iterative, step-by-step debugging.

```
tools:
  harness_minimizer:
    timeout: 1200
    signature: harness_minimizer <fuzzer_id>
    docstring: Minimize the harness code while retaining the crash-triggering behavior.
      The minimized harness will be compiled into a new fuzzer binary for you to further
      analyze the crash.
    arguments:
    - name: fuzzer_id
      type: integer
      description: The fuzzer (or harness) instance ID to generate minimized harness
        for.
      required: true
  crash_artifact_analysis:
    timeout: 60
    signature: crash_artifact_analysis <fuzzer_id> <crash_artifact_path>
    docstring: Execute the crash artifact on the fuzzer binary and gather information
      from the crash stacktrace and source code.
    arguments:
    - name: fuzzer_id
      type: integer
      description: The fuzzer instance ID to generate the crash report for. E.g.,
        000, 001, etc.
      required: true
    - name: crash_artifact_path
      type: string
      description: Path to the artifact file that caused the crash artifact, which
        is usually named as "crash-<hash>", must be a file, not a directory
      required: true
  crash_debugger:
    timeout: 120
    signature: crash_debugger <fuzz_target_binary> <crash_artifact_path> <gdb_commands>
      [--reset <0|1>]
    docstring: Run a stateful GDB session on the fuzzer binary to debug a crash. The
      tool automatically maintains your previous GDB commands. You can pass multiple
      comma-separated commands at once (e.g., "b LLVMFuzzerTestOneInput, r, p var"). To reset the session
      history, pass --reset 1.
    arguments:
    - name: fuzz_target_binary
      type: string
      description: Path to the fuzzer binary.
      required: true
    - name: crash_artifact_path
      type: string
      description: Path to the crash artifact file that caused the crash
      required: true
    - name: gdb_commands
      type: string
      description: The new GDB commands to append & run, comma-separated. The target
        binary takes the crash_artifact_path as an argument automatically.
      required: true
    - name: reset
      type: integer
      description: Pass 1 to clear the session history before executing the new commands,
        0 otherwise. Default is 0.
      required: false
  generate_crash_report:
    timeout: 10
    signature: generate_crash_report "<fuzzer_id>" "<crash_artifact_path>" "<triage>"
      "<content>"
    docstring: 'Create a normalized crash report file for a given fuzzer and crash
      input.'
    arguments:
    - name: fuzzer_id
      type: string
      description: The fuzzer instance ID to generate the crash report for. E.g.,
        000, 001, etc.
      required: true
    - name: crash_artifact_path
      type: string
      description: Path to the crash artifact file that caused the crash, which is
        usually named as "crash-<hash>", must be a file, not a directory
      required: true
    - name: triage
      type: string
      enum:
        - library-bug
        - harness-bug
      description: The triage result of the crash, e.g., "library-bug", "harness-bug"
      required: true
    - name: content
      type: string
      description: Report content as a string. Provide the full markdown format text.
      required: true
      redirect: true
```

# Others
## Agent Coordination

These tools are used exclusively by the Manager Agent to orchestrate the multi-agent workflow: inspecting the global fuzzing state and dispatching subtasks to specialized agents (Builder, Harness Generator, Coverage Analyzer, etc.).

```
tools:
  observe_current_states:
    timeout: 120
    signature: observe_current_states
    docstring: Check and observe the status of the whole fuzzing tasks, including
      build status, harness status, dictionary status, fuzzing status, and any issues
      in the progress of fuzzing. Please feel free to use this tool to check the status
      of the whole fuzzing tasks. However, please note that the output of this tool
      is only a status of the system and does not constitute a guide for actual operation.
      You still need to decide what to do next based on the process you have executed,
      the feedback you received, and the actual situation of your current working
      directory.
  send_agent_task:
    signature: send_agent_task <agent_name> <task_description>
    docstring: Send a task to a specific agent.
    arguments:
      - name: agent_name
        type: string
        description: The name of the agent to send the task to.
        enum: ["BuilderAgent", "DictionaryAgent", "SeedAgent", "HarnessAgent", "CoverageAnalyzerAgent", "FuzzerExecutorAgent", "CrashAnalyzerAgent"]
        required: true
      - name: task_description
        type: string
        description: The detailed description of the task to send to the agent.
        required: true
  exit:
    signature: exit <exit_reason> <force>
    docstring: Exit the task. You can only exit the task when you are sure your task is finished. 
    arguments:
      - name: exit_reason
        type: string
        description: The reason to exit the task. You should always report your task status before exiting the task.
        required: true
      - name: force
        type: boolean
        description: Force to exit the task regardless of user reminders and restrictions. Only use this option when you encountered fatal errors and cannot be fixed in current task loop.
        required: false
```