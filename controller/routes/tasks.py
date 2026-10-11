"""Task CRUD endpoints."""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, Query, Request

from controller.auth import verify_token
from controller.exceptions import (
    TaskNotFoundError,
)
from controller.models import (
    AnalysisResponse,
    FuzzingTaskCreate,
    FuzzingTaskListResponse,
    FuzzingTaskResponse,
    TaskStatusEnum,
)
from controller.task_manager import ControllerTaskManager
from controller.store import TaskStore
from controller.docker_launcher import DockerLauncher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.post("/tasks", response_model=FuzzingTaskResponse, status_code=201)
async def create_task(body: FuzzingTaskCreate, request: Request) -> FuzzingTaskResponse:
    started = time.time()
    logger.info("create_task entry task_id=%s body=%s", body.task_id, body.dict())
    manager: ControllerTaskManager = request.app.state.manager
    task = await manager.submit_task(body)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("create_task exit task_id=%s status=%s elapsed_ms=%.0f", task.task_id, task.status, elapsed_ms)
    return task.to_response()


@router.get("/tasks", response_model=FuzzingTaskListResponse)
async def list_tasks(
    status: TaskStatusEnum | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = None,
) -> FuzzingTaskListResponse:
    started = time.time()
    logger.info("list_tasks entry status=%s offset=%d limit=%d", status, offset, limit)
    store: TaskStore = request.app.state.store
    tasks = await store.list_tasks(status=status, offset=offset, limit=limit)
    total = await store.count_tasks(status)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("list_tasks exit count=%d total=%d elapsed_ms=%.0f", len(tasks), total, elapsed_ms)
    return FuzzingTaskListResponse(
        tasks=[t.to_response() for t in tasks],
        total=total,
    )


@router.get("/tasks/{task_id}", response_model=FuzzingTaskResponse)
async def get_task(task_id: str, request: Request) -> FuzzingTaskResponse:
    started = time.time()
    logger.info("get_task entry task_id=%s", task_id)
    store: TaskStore = request.app.state.store
    task = await store.get(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("get_task exit task_id=%s status=%s elapsed_ms=%.0f", task_id, task.status, elapsed_ms)
    logger.debug("get_task detail: container=%s", task.container_id)
    return task.to_response()


@router.post("/tasks/{task_id}/cancel", response_model=FuzzingTaskResponse)
async def cancel_task(task_id: str, request: Request) -> FuzzingTaskResponse:
    started = time.time()
    logger.info("cancel_task entry task_id=%s", task_id)
    manager: ControllerTaskManager = request.app.state.manager
    task = await manager.cancel_task(task_id)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("cancel_task exit task_id=%s status=%s elapsed_ms=%.0f", task_id, task.status, elapsed_ms)
    return task.to_response()


@router.get("/tasks/{task_id}/analysis", response_model=AnalysisResponse)
async def get_analysis_status(task_id: str, request: Request) -> AnalysisResponse:
    """Get the analysis status for a task."""
    started = time.time()
    logger.info("get_analysis_status entry task_id=%s", task_id)
    store: TaskStore = request.app.state.store
    task = await store.get(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    elapsed_ms = (time.time() - started) * 1000
    logger.info(
        "get_analysis_status exit task_id=%s analysis_status=%s elapsed_ms=%.0f",
        task_id, task.analysis_status, elapsed_ms,
    )
    return AnalysisResponse(
        task_id=task.task_id,
        analysis_status=task.analysis_status,
        analysis_container_id=task.analysis_container_id,
    )


@router.post("/tasks/{task_id}/analysis", response_model=AnalysisResponse)
async def trigger_analysis(task_id: str, request: Request) -> AnalysisResponse:
    """Manually trigger analysis for a task (or re-run if previously failed)."""
    started = time.time()
    logger.info("trigger_analysis entry task_id=%s", task_id)
    manager: ControllerTaskManager = request.app.state.manager
    store: TaskStore = request.app.state.store
    task = await store.get(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    logger.debug("trigger_analysis: task %s current status=%s", task_id, task.status)
    if task.status not in (TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED):
        from controller.exceptions import ControllerError
        raise ControllerError("Analysis can only be triggered for completed, failed, or cancelled tasks")

    await store.update(task_id, enable_analysis=True, analysis_status=None)
    asyncio.create_task(manager._launch_analysis(task_id))
    logger.debug("Analysis launched for task %s", task_id)

    task = await store.get(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("trigger_analysis exit task_id=%s elapsed_ms=%.0f", task_id, elapsed_ms)
    return AnalysisResponse(
        task_id=task.task_id,
        analysis_status=task.analysis_status,
        analysis_container_id=task.analysis_container_id,
    )


@router.post("/tasks/{task_id}/analysis/cancel", response_model=AnalysisResponse)
async def cancel_analysis(task_id: str, request: Request) -> AnalysisResponse:
    """Cancel an in-progress introspector analysis for a task."""
    started = time.time()
    logger.info("cancel_analysis entry task_id=%s", task_id)
    manager: ControllerTaskManager = request.app.state.manager
    task = await manager.cancel_analysis(task_id)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("cancel_analysis exit task_id=%s elapsed_ms=%.0f", task_id, elapsed_ms)
    return AnalysisResponse(
        task_id=task.task_id,
        analysis_status=task.analysis_status,
        analysis_container_id=task.analysis_container_id,
    )


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, request: Request) -> None:
    started = time.time()
    logger.info("delete_task entry task_id=%s", task_id)
    manager: ControllerTaskManager = request.app.state.manager
    await manager.delete_task(task_id)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("delete_task exit task_id=%s elapsed_ms=%.0f", task_id, elapsed_ms)


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    tail: int = Query(default=100, ge=1, le=5000),
    request: Request = None,
) -> dict:
    started = time.time()
    logger.info("get_task_logs entry task_id=%s tail=%d", task_id, tail)
    store: TaskStore = request.app.state.store
    launcher: DockerLauncher = request.app.state.launcher

    task = await store.get(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    if task.container_id is None:
        return {"logs": "", "task_id": task_id, "detail": "Container not yet started"}

    logs = await launcher.get_container_logs(task.container_id, tail=tail)
    elapsed_ms = (time.time() - started) * 1000
    logger.info("get_task_logs exit task_id=%s log_len=%d elapsed_ms=%.0f", task_id, len(logs), elapsed_ms)
    return {"logs": logs, "task_id": task_id}
