"""Core task orchestration logic for the FuzzAgent Controller."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from controller.config import ControllerConfig
from controller.docker_launcher import DockerLauncher
from controller.exceptions import (
    ConcurrencyLimitExceededError,
    PathTraversalError,
    ProjectSourceNotFoundError,
    TaskNotCancellableError,
    TaskNotFoundError,
)
from controller.models import FuzzingTask, FuzzingTaskCreate, TaskStatusEnum
from controller.store import TaskStore

logger = logging.getLogger(__name__)


FUZZ_COMMAND_TEMPLATE = (
    "bash /root/FuzzAgent/src/tools/copy_tools.sh && uv sync && "
    "timeout {fuzzing_duration_hours}h uv run main.py"
)
DEFAULT_FUZZING_DURATION_HOURS = 24

# Command executed inside the analysis container.
# Reuses the same fuzzagent image; only the command differs.
ANALYSIS_COMMAND = (
    "bash /root/FuzzAgent/src/tools/copy_tools.sh && "
    "python3 -m introspector"
)


def _validate_host_path(path: str, name: str, allowed_paths: list[str]) -> Path:
    """Validate a host path is absolute, exists, and resolves under allowed paths."""
    resolved = Path(path).resolve()
    if not resolved.is_absolute():
        raise PathTraversalError(name, path)
    if not resolved.exists():
        raise ProjectSourceNotFoundError(path)
    if not any(str(resolved).startswith(allowed) for allowed in allowed_paths):
        raise PathTraversalError(name, path)
    return resolved


def _coerce_positive_hours(value: Any) -> int:
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return DEFAULT_FUZZING_DURATION_HOURS
    return hours if hours > 0 else DEFAULT_FUZZING_DURATION_HOURS


class ControllerTaskManager:
    def __init__(self, store: TaskStore, launcher: DockerLauncher, config: ControllerConfig) -> None:
        self.store = store
        self.launcher = launcher
        self.config = config
        self._monitor_tasks: dict[str, asyncio.Task] = {}
        self._analysis_semaphore = asyncio.Semaphore(config.max_concurrent_analysis)
        self._analysis_queue: asyncio.Queue[str] = asyncio.Queue()
        self._analysis_running: set[str] = set()
        self._analysis_monitors: dict[str, asyncio.Task] = {}
        self._queue_processor: asyncio.Task | None = None

    async def start(self) -> None:
        """Start background analysis queue processor."""
        self._queue_processor = asyncio.create_task(self._process_analysis_queue())

    async def submit_task(self, request: FuzzingTaskCreate) -> FuzzingTask:
        # Concurrency limit check (item 11)
        running_count = await self.store.count_tasks(TaskStatusEnum.RUNNING)
        pending_count = await self.store.count_tasks(TaskStatusEnum.PENDING)
        if running_count + pending_count >= self.config.max_concurrent_tasks:
            raise ConcurrencyLimitExceededError(self.config.max_concurrent_tasks)

        # Path traversal validation (item 5)
        allowed_paths = self.config.get_allowed_paths()
        _validate_host_path(request.src_dir, "src_dir", allowed_paths)
        _validate_host_path(request.raw_output_dir, "raw_output_dir", allowed_paths)
        _validate_host_path(request.fuzzagent_dir, "fuzzagent_dir", allowed_paths)

        # Extract fuzzing_duration_hours from config
        fuzzing_duration_hours = None
        extra_env: dict[str, str] = {}
        if request.config:
            fuzzing_duration_hours = request.config.get("fuzzing_duration_hours")
            extra_env = request.config.get("extra_env", {})

        # Resolve command → actual command, write_mode, auto_clean
        actual_command, write_mode, auto_clean = self._resolve_command(
            request.command,
            fuzzing_duration_hours,
        )

        task = FuzzingTask(
            task_id=request.task_id,
            container_name=request.container_name,
            command=actual_command,
            fuzzagent_dir=request.fuzzagent_dir,
            write_mode=write_mode,
            raw_output_dir=request.raw_output_dir,
            repo_base_name=request.repo_base_name,
            src_dir=request.src_dir,
            fuzzing_engine=request.fuzzing_engine,
            auto_clean=auto_clean,
            llm_model=request.llm_model,
            openai_base_url=request.openai_base_url,
            openai_api_key=request.openai_api_key,
            llm_temperature=request.llm_temperature,
            llm_top_p=request.llm_top_p,
            llm_top_k=request.llm_top_k,
            llm_reply_timeout=request.llm_reply_timeout,
            max_agent_epochs=request.max_agent_epochs,
            reminder_token_ratio=request.reminder_token_ratio,
            max_token_len=request.max_token_len,
            extra_env=extra_env,
            callback_url=request.callback_url,
            callback_token=request.callback_token,
            enable_analysis=request.enable_analysis,
            config=request.config,
            fuzzing_duration_hours=fuzzing_duration_hours,
        )
        await self.store.create(task)
        logger.info("Task %s created (engine=%s, src=%s, command=%s)", task.task_id, task.fuzzing_engine, task.src_dir, request.command)
        asyncio.create_task(self._launch_and_monitor(task.task_id))
        return task

    @staticmethod
    def _resolve_command(
        semantic_command: str,
        fuzzing_duration_hours: int | None,
    ) -> tuple[str, bool, bool]:
        """Map semantic command to (actual_command, write_mode, auto_clean)."""
        if semantic_command == "fuzz":
            duration_hours = _coerce_positive_hours(fuzzing_duration_hours)
            return (FUZZ_COMMAND_TEMPLATE.format(fuzzing_duration_hours=duration_hours), True, True)
        elif semantic_command == "analysis":
            return (ANALYSIS_COMMAND, False, False)
        else:
            return (semantic_command, False, False)

    async def cancel_task(self, task_id: str) -> FuzzingTask:
        task = await self.store.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.status not in (TaskStatusEnum.PENDING, TaskStatusEnum.RUNNING):
            raise TaskNotCancellableError(task_id)

        if task.container_id:
            await self.launcher.stop(task)

        monitor = self._monitor_tasks.pop(task_id, None)
        if monitor and not monitor.done():
            monitor.cancel()

        task = await self.store.update(
            task_id,
            status=TaskStatusEnum.CANCELLED,
            finished_at=datetime.now(timezone.utc),
        )
        logger.info("Task %s cancelled", task_id)
        return task

    async def cancel_analysis(self, task_id: str) -> FuzzingTask:
        """Cancel an in-progress (queued or running) introspector analysis.

        Mirrors cancel_task's pattern but operates on the parent task's
        analysis_container_id / analysis_status, since the analysis FuzzingTask
        itself is never persisted to the store.
        """
        task = await self.store.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.analysis_status not in ("queued", "running"):
            from controller.exceptions import ControllerError
            raise ControllerError(
                f"Analysis not cancellable in status '{task.analysis_status}'"
            )

        # 1. Cancel the monitor FIRST so it can't race us and overwrite our
        # 'cancelled' status with 'failed' (container exits non-zero when killed).
        monitor = self._analysis_monitors.pop(task_id, None)
        if monitor and not monitor.done():
            monitor.cancel()

        # 2. Stop the analysis container by ID. We don't have the analysis
        # FuzzingTask record (never persisted), so we can't reconstruct one to
        # feed to launcher.stop(); docker rm -f by container_id is the cleanest.
        if task.analysis_container_id:
            try:
                await self.launcher.stop_container_by_id(task.analysis_container_id)
            except Exception:
                logger.exception(
                    "Failed to stop analysis container for task %s", task_id
                )

        # 3. Update analysis_status BEFORE firing callback so the callback
        # payload correctly reports 'cancelled'.
        task = await self.store.update(task_id, analysis_status="cancelled")
        self._analysis_running.discard(task_id)
        logger.info("Analysis for task %s cancelled by user", task_id)

        # 4. Fire callback (existing _notify_analysis_callback reads
        # task.analysis_status, which is now 'cancelled').
        await self._notify_analysis_callback(task_id)
        return task

    async def delete_task(self, task_id: str) -> None:
        task = await self.store.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.status in (TaskStatusEnum.PENDING, TaskStatusEnum.RUNNING):
            raise TaskNotCancellableError(task_id)

        monitor = self._monitor_tasks.pop(task_id, None)
        if monitor and not monitor.done():
            monitor.cancel()

        await self.store.delete(task_id)
        logger.info("Task %s deleted", task_id)

    async def shutdown(self) -> None:
        # NOTE: we deliberately do NOT call launcher.stop() here. Docker containers
        # survive Controller restarts by design — app.py's _reattach_monitors will
        # re-arm polling for any task whose container is still running when the
        # Controller comes back up. Stopping containers on shutdown would defeat
        # that recovery path and surface as "Container lost on restart" failures
        # after every restart.
        logger.info(
            "Shutting down task manager; leaving running containers in place "
            "for cross-restart recovery"
        )
        for _task_id, monitor in list(self._monitor_tasks.items()):
            if not monitor.done():
                monitor.cancel()
        self._monitor_tasks.clear()

        for monitor in self._analysis_monitors.values():
            if not monitor.done():
                monitor.cancel()
        self._analysis_monitors.clear()

        if self._queue_processor and not self._queue_processor.done():
            self._queue_processor.cancel()
            try:
                await self._queue_processor
            except asyncio.CancelledError:
                pass

    async def _launch_and_monitor(self, task_id: str) -> None:
        try:
            task = await self.store.get(task_id)
            if task is None:
                logger.warning("Task %s disappeared before launch", task_id)
                return
            result = await self.launcher.launch(task)
            await self.store.update(
                task_id,
                status=TaskStatusEnum.RUNNING,
                container_id=result.container_id,
                container_name=result.container_name,
                compose_dir=result.compose_dir,
                started_at=datetime.now(timezone.utc),
            )

            self._monitor_tasks[task_id] = asyncio.create_task(
                self._monitor_container(task_id)
            )
        except Exception as e:
            logger.exception("Failed to launch task %s", task_id)
            await self.store.update(
                task_id,
                status=TaskStatusEnum.FAILED,
                error_message=str(e),
                finished_at=datetime.now(timezone.utc),
            )

    async def _monitor_container(self, task_id: str) -> None:
        while True:
            try:
                task = await self.store.get(task_id)
                if task is None or task.status == TaskStatusEnum.CANCELLED:
                    break

                if task.container_id is None:
                    logger.debug("Task %s has no container_id yet, waiting", task_id)
                    await asyncio.sleep(self.config.monitor_interval_seconds)
                    continue

                container_status = await self.launcher.get_container_status(task.container_id)
                if container_status in ("exited", "dead"):
                    exit_code = await self.launcher.get_exit_code(task.container_id)
                    final_status = TaskStatusEnum.COMPLETED if exit_code in (0, 124) else TaskStatusEnum.FAILED
                    await self.store.update(
                        task_id,
                        status=final_status,
                        exit_code=exit_code,
                        finished_at=datetime.now(timezone.utc),
                    )
                    logger.info("Task %s finished with status %s (exit_code=%d)", task_id, final_status, exit_code)

                    # Callback notification (item 9)
                    await self._notify_callback(task_id)

                    # Analysis is NOT auto-launched here. Backend decides
                    # whether to trigger analysis via POST /tasks/{id}/analysis.

                    break

                await asyncio.sleep(self.config.monitor_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error monitoring task %s", task_id)
                await asyncio.sleep(self.config.monitor_interval_seconds)

    async def _process_analysis_queue(self) -> None:
        """Background loop that dispatches analysis tasks with concurrency control."""
        while True:
            try:
                task_id = await self._analysis_queue.get()
                await self._analysis_semaphore.acquire()
                self._analysis_running.add(task_id)
                try:
                    await self._do_launch_analysis(task_id)
                except Exception:
                    self._analysis_semaphore.release()
                    self._analysis_running.discard(task_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in analysis queue processor")

    async def _launch_analysis(self, task_id: str) -> None:
        """Enqueue analysis task for controlled execution."""
        await self.store.update(task_id, analysis_status="queued")
        await self._analysis_queue.put(task_id)
        logger.info(
            "Analysis for task %s queued (running=%d, limit=%d)",
            task_id, len(self._analysis_running), self.config.max_concurrent_analysis,
        )

    async def _do_launch_analysis(self, task_id: str) -> None:
        """Launch an analysis container (called by queue processor)."""
        try:
            task = await self.store.get(task_id)
            if task is None or not task.enable_analysis:
                self._analysis_semaphore.release()
                self._analysis_running.discard(task_id)
                return

            analysis_task = FuzzingTask(
                task_id=f"{task.task_id}_analysis",
                container_name=f"{task.container_name}_analysis",
                command=ANALYSIS_COMMAND,
                fuzzagent_dir=task.fuzzagent_dir,
                write_mode=False,
                raw_output_dir=task.raw_output_dir,
                repo_base_name=task.repo_base_name,
                src_dir=task.src_dir,
                fuzzing_engine=task.fuzzing_engine,
                auto_clean=False,
                llm_model=task.llm_model,
                openai_base_url=task.openai_base_url,
                openai_api_key=task.openai_api_key,
                llm_temperature=task.llm_temperature,
                llm_top_p=task.llm_top_p,
                llm_top_k=task.llm_top_k,
                llm_reply_timeout=task.llm_reply_timeout,
                max_agent_epochs=task.max_agent_epochs,
                reminder_token_ratio=task.reminder_token_ratio,
                max_token_len=task.max_token_len,
                callback_url=task.callback_url,
                callback_token=task.callback_token,
            )

            # Check if cancel_analysis ran while we were waiting in the queue
            if task.analysis_status == "cancelled":
                logger.info("Analysis for task %s was cancelled while queued; skipping launch", task_id)
                self._analysis_semaphore.release()
                self._analysis_running.discard(task_id)
                return

            await self.store.update(task_id, analysis_status="running")
            result = await self.launcher.launch(analysis_task)
            await self.store.update(
                task_id,
                analysis_container_id=result.container_id,
            )
            logger.info(
                "Analysis container launched for task %s (container=%s)",
                task_id, result.container_id[:12],
            )
            self._analysis_monitors[task_id] = asyncio.create_task(
                self._monitor_analysis(task_id, result.container_id)
            )
        except Exception:
            logger.exception("Failed to launch analysis for task %s", task_id)
            await self.store.update(task_id, analysis_status="failed")
            self._analysis_semaphore.release()
            self._analysis_running.discard(task_id)

    async def _monitor_analysis(self, task_id: str, container_id: str) -> None:
        """Monitor the analysis container until it exits."""
        try:
            while True:
                try:
                    container_status = await self.launcher.get_container_status(container_id)
                    if container_status in ("exited", "dead"):
                        # cancel_analysis may have already set analysis_status='cancelled'
                        # and fired its own callback. Don't overwrite.
                        current = await self.store.get(task_id)
                        if current and current.analysis_status == "cancelled":
                            logger.info("Analysis for task %s already cancelled; not overriding", task_id)
                            break
                        exit_code = await self.launcher.get_exit_code(container_id)
                        if exit_code == 0:
                            # Defense in depth: introspector should already
                            # exit non-zero on real failures (after the
                            # full_coverage_reply / __main__ fixes), but in
                            # case a future bug slips through, verify the
                            # output file actually has non-null metrics.
                            ok, probe_error = await self._probe_introspector_output(task_id)
                            if ok:
                                status = "completed"
                                error_message = None
                            else:
                                status = "failed"
                                error_message = f"introspector output probe failed: {probe_error}"
                        else:
                            status = "failed"
                            error_message = f"introspector exited with code {exit_code}"
                        update_fields: dict[str, Any] = {"analysis_status": status}
                        if error_message:
                            update_fields["error_message"] = error_message
                        await self.store.update(task_id, **update_fields)
                        logger.info(
                            "Analysis for task %s %s (exit_code=%d)",
                            task_id, status, exit_code,
                        )
                        await self._notify_analysis_callback(task_id)
                        break
                    if container_status == "unknown":
                        await self.store.update(task_id, analysis_status="failed")
                        logger.warning("Analysis container for task %s lost", task_id)
                        break
                    await asyncio.sleep(self.config.monitor_interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("Error monitoring analysis for task %s", task_id)
                    await asyncio.sleep(self.config.monitor_interval_seconds)
        finally:
            self._analysis_monitors.pop(task_id, None)
            self._analysis_running.discard(task_id)
            self._analysis_semaphore.release()

    async def _probe_introspector_output(self, task_id: str) -> tuple[bool, str | None]:
        """Verify introspector actually produced non-trial output.

        Returns (ok, error_message). ok=True if final_coverage.json exists,
        is valid JSON, and contains at least one non-null coverage metric.
        Used as defense in depth — introspector's own __main__.py should
        already exit non-zero on failure, but this catches future bugs.
        """
        task = await self.store.get(task_id)
        if task is None or not task.raw_output_dir:
            return True, None  # nothing we can probe; trust exit_code

        final_cov = Path(task.raw_output_dir) / ".cache" / "introspector" / "final_coverage.json"
        try:
            content = final_cov.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"final_coverage.json unreadable at {final_cov}: {exc}"

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            return False, f"final_coverage.json is not valid JSON: {exc}"

        if not isinstance(data, dict):
            return False, f"final_coverage.json is not a JSON object: {type(data).__name__}"

        metrics = ("coverage_percent", "regions", "functions", "lines", "branches")
        if not any(data.get(k) is not None for k in metrics):
            return False, f"final_coverage.json has all-null metrics: {content[:200]}"

        return True, None

    async def _notify_analysis_callback(self, task_id: str) -> None:
        """POST analysis completion to callback_url if configured."""
        task = await self.store.get(task_id)
        if task is None or task.callback_url is None:
            return

        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "status": "analysis_completed",
            "analysis_status": task.analysis_status,
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if task.callback_token:
            headers["Authorization"] = f"Bearer {task.callback_token}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(task.callback_url, json=payload, headers=headers)
            logger.info("Analysis callback sent for task %s", task_id)
        except Exception:
            logger.exception("Failed to send analysis callback for task %s", task_id)

    async def _notify_callback(self, task_id: str) -> None:
        """POST task status to callback_url if configured. Fire-and-forget."""
        task = await self.store.get(task_id)
        if task is None or task.callback_url is None:
            return

        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "status": task.status.value,
            "exit_code": task.exit_code,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "error_message": f"exited with code {task.exit_code}" if task.status == TaskStatusEnum.FAILED else None,
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if task.callback_token:
            headers["Authorization"] = f"Bearer {task.callback_token}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(task.callback_url, json=payload, headers=headers)
            logger.info("Callback sent for task %s to %s", task_id, task.callback_url)
        except Exception:
            logger.exception("Failed to send callback for task %s to %s", task_id, task.callback_url)
