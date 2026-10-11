"""Custom exceptions for the FuzzAgent Controller."""


class ControllerError(Exception):
    """Base exception for controller errors."""


class TaskNotFoundError(ControllerError):
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")


class TaskNotCancellableError(ControllerError):
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task cannot be cancelled in current state: {task_id}")


class DockerLaunchError(ControllerError):
    def __init__(self, task_id: str, detail: str):
        self.task_id = task_id
        super().__init__(f"Docker launch failed for task {task_id}: {detail}")


class DockerComposeError(ControllerError):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        stderr_snippet = stderr.strip()[:500] or "(empty)"
        super().__init__(
            f"Docker compose failed (rc={returncode}): {' '.join(cmd)}\nstderr: {stderr_snippet}"
        )


class ProjectSourceNotFoundError(ControllerError):
    def __init__(self, source_path: str):
        self.source_path = source_path
        super().__init__(f"Project source path does not exist: {source_path}")


class PathTraversalError(ControllerError):
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        super().__init__(f"Path traversal rejected: {name}={path}")


class ConcurrencyLimitExceededError(ControllerError):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Maximum concurrent tasks limit reached ({limit})")
