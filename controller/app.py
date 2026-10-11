"""FastAPI application factory for the FuzzAgent Controller."""

import asyncio
import logging
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse

from controller import __version__
from controller.auth import verify_token
from controller.config import ControllerConfig
from controller.docker_launcher import DockerLauncher
from controller.exceptions import (
    ConcurrencyLimitExceededError,
    ControllerError,
    DockerLaunchError,
    PathTraversalError,
    ProjectSourceNotFoundError,
    TaskNotCancellableError,
    TaskNotFoundError,
)
from controller.routes import health, tasks
from controller.store import TaskStore, RedisTaskStore
from controller.task_manager import ControllerTaskManager
from controller.models import TaskStatusEnum

logger = logging.getLogger(__name__)


async def _start_redis(config: ControllerConfig) -> RedisTaskStore:
    """Start Redis container via redis_compose.yml and wait until ready."""
    compose_file = str(
        __import__("pathlib").Path(__file__).parent / "redis_compose.yml"
    )
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_file, "-p", "fuzzanything_redis_" + config.app_env, "up", "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Failed to start Redis container: %s", stderr.decode(errors="replace"))
    else:
        logger.info("Redis container started via %s", compose_file)

    # Wait for Redis to be ready
    store = RedisTaskStore(redis_url=config.redis_url)
    for attempt in range(10):
        try:
            await store._redis.ping()
            logger.info("Redis is ready at %s", config.redis_url)
            return store
        except Exception:
            await asyncio.sleep(1)
    logger.warning("Redis not ready after 10s, proceeding anyway")
    return store


async def _stop_redis() -> None:
    """Stop the Redis container."""
    compose_file = str(
        __import__("pathlib").Path(__file__).parent / "redis_compose.yml"
    )
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_file, "down",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    logger.info("Redis container stopped")


async def _reconcile_tasks(store: TaskStore, launcher: DockerLauncher) -> None:
    """Reconcile stale RUNNING/PENDING tasks on startup by checking container status."""
    for status in (TaskStatusEnum.RUNNING, TaskStatusEnum.PENDING):
        task_ids: set[str] = set()
        if isinstance(store, RedisTaskStore):
            task_ids = await store.get_task_ids_by_status(status)
        else:
            all_tasks = await store.list_tasks(status=status, limit=10000)
            task_ids = {t.task_id for t in all_tasks}

        for task_id in task_ids:
            task = await store.get(task_id)
            if task is None:
                continue
            if task.container_id is None:
                # No container ever started — mark as FAILED
                await store.update(task_id, status=TaskStatusEnum.FAILED, error_message="Lost on restart", finished_at=datetime.now(timezone.utc))
                logger.info("Reconciled task %s: no container, marked FAILED", task_id)
                continue
            container_status = await launcher.get_container_status(task.container_id)
            if container_status in ("exited", "dead"):
                exit_code = await launcher.get_exit_code(task.container_id)
                final = TaskStatusEnum.COMPLETED if exit_code == 0 else TaskStatusEnum.FAILED
                await store.update(task_id, status=final, exit_code=exit_code, finished_at=datetime.now(timezone.utc))
                logger.info("Reconciled task %s: container %s, marked %s", task_id, container_status, final)
            elif container_status == "unknown":
                await store.update(task_id, status=TaskStatusEnum.FAILED, error_message="Container lost on restart", finished_at=datetime.now(timezone.utc))
                logger.info("Reconciled task %s: container unknown, marked FAILED", task_id)


async def _reattach_monitors(
    store: TaskStore,
    launcher: DockerLauncher,
    manager: ControllerTaskManager,
) -> None:
    """Re-arm polling monitors for tasks whose containers survived a Controller restart.

    Called after _reconcile_tasks has cleaned up stale tasks. Only tasks that
    are still RUNNING with a live container get re-attached.
    """
    running_ids: set[str] = set()
    if isinstance(store, RedisTaskStore):
        running_ids = await store.get_task_ids_by_status(TaskStatusEnum.RUNNING)
    else:
        all_running = await store.list_tasks(status=TaskStatusEnum.RUNNING, limit=10000)
        running_ids = {t.task_id for t in all_running}

    reattached = 0
    for task_id in running_ids:
        task = await store.get(task_id)
        if task is None or not task.container_id:
            continue
        status = await launcher.get_container_status(task.container_id)
        if status in ("running", "created", "paused"):
            manager._monitor_tasks[task_id] = asyncio.create_task(
                manager._monitor_container(task_id)
            )
            reattached += 1
            logger.info(
                "Re-attached monitor for surviving task %s (container=%s)",
                task_id, task.container_id[:12],
            )
    if reattached:
        logger.info("Recovered %d running task monitors after restart", reattached)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config: ControllerConfig = app.state.config
    launcher = DockerLauncher()

    # Start Redis-backed store (the only supported backend)
    store: TaskStore = await _start_redis(config)

    manager = ControllerTaskManager(store, launcher, config)

    # Reconcile stale tasks on startup
    try:
        await _reconcile_tasks(store, launcher)
    except Exception:
        logger.exception("Failed to reconcile tasks on startup")

    # Re-arm monitors for tasks whose containers survived the restart
    try:
        await _reattach_monitors(store, launcher, manager)
    except Exception:
        logger.exception("Failed to re-attach task monitors on startup")

    app.state.store = store
    app.state.launcher = launcher
    app.state.manager = manager
    app.state.started_at = time.time()

    await manager.start()

    logger.info("FuzzAgent Controller v%s started on %s:%d", __version__, config.host, config.port)
    yield

    await manager.shutdown()
    if isinstance(store, RedisTaskStore):
        await store.close()
    await _stop_redis()
    logger.info("FuzzAgent Controller shutdown complete")


def create_app(config: ControllerConfig) -> FastAPI:
    app = FastAPI(
        title="FuzzAgent Controller",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.config = config

    _register_exception_handlers(app)
    _register_routes(app, config)
    _add_request_logging(app)

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(request, exc):
        logger.warning("Task not found: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(TaskNotCancellableError)
    async def task_not_cancellable_handler(request, exc):
        logger.warning("Task not cancellable: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ProjectSourceNotFoundError)
    async def source_not_found_handler(request, exc):
        logger.warning("Source not found: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(PathTraversalError)
    async def path_traversal_handler(request, exc):
        logger.warning("Path traversal rejected: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ConcurrencyLimitExceededError)
    async def concurrency_limit_handler(request, exc):
        logger.warning("Concurrency limit exceeded: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=429, content={"detail": "Maximum concurrent tasks limit reached"})

    @app.exception_handler(DockerLaunchError)
    async def docker_launch_error_handler(request, exc):
        logger.error("Docker launch error: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(ControllerError)
    async def controller_error_handler(request, exc):
        logger.error("Controller error: %s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


def _register_routes(app: FastAPI, config: ControllerConfig) -> None:
    # Conditionally apply auth based on config (item 4)
    # api_token is None → auth disabled; empty string or set → auth required
    if config.api_token is not None:
        tasks.router.dependencies = [Depends(verify_token)]
    else:
        tasks.router.dependencies = []

    app.include_router(tasks.router, prefix=config.api_prefix)
    app.include_router(health.router)


def _add_request_logging(app: FastAPI) -> None:
    import re

    # Redact sensitive patterns before logging request body at DEBUG level.
    _SENSITIVE_PATTERNS = [
        re.compile(r'(sk-)[a-zA-Z0-9\-_]{20,}'),              # OpenAI-style keys
        re.compile(r'("(?:api_key|openai_api_key|password|token)"\s*:\s*")[^"]*"', re.IGNORECASE),
        re.compile(r'(Bearer\s+)[a-zA-Z0-9\-._]+', re.IGNORECASE),
    ]

    def _redact_body(text: str) -> str:
        for pattern in _SENSITIVE_PATTERNS:
            text = pattern.sub(r"\1***", text)
        return text

    @app.middleware("http")
    async def log_requests(request, call_next):
        # Read body before call_next so we can log it at DEBUG.
        # request.body() is cached by Starlette, so downstream handlers
        # can still call it without consuming the stream.
        body_bytes = await request.body()

        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        logger.info(
            "%s %s -> %d (%.0fms)",
            request.method, request.url.path, response.status_code, duration_ms,
        )

        if logger.isEnabledFor(logging.DEBUG):
            body_str = body_bytes.decode(errors="replace") if body_bytes else "<empty>"
            redacted = _redact_body(body_str)
            logger.debug("Request body: %s", redacted)

        return response
