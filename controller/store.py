"""Task storage layer for the FuzzAgent Controller.

Contains the TaskStore protocol and its sole implementation, RedisTaskStore.
"""

import json
import logging
from typing import Protocol

import redis.asyncio as aioredis

from controller.models import FuzzingTask, TaskStatusEnum

logger = logging.getLogger(__name__)


class TaskStore(Protocol):
    async def create(self, task: FuzzingTask) -> FuzzingTask: ...
    async def get(self, task_id: str) -> FuzzingTask | None: ...
    async def update(self, task_id: str, **fields) -> FuzzingTask: ...
    async def list_tasks(
        self, status: TaskStatusEnum | None = None, offset: int = 0, limit: int = 50
    ) -> list[FuzzingTask]: ...
    async def delete(self, task_id: str) -> bool: ...
    async def count_tasks(self, status: TaskStatusEnum | None = None) -> int: ...
    async def pop_pending(self) -> FuzzingTask | None: ...


class RedisTaskStore:
    """Redis-backed implementation of the TaskStore protocol.

    Data layout:
      - task:{task_id}           -> JSON-serialized FuzzingTask
      - task_status:{status}     -> Redis set of task IDs
      - task_queue               -> Redis list of pending task IDs
    """

    def __init__(self, redis_url: str = "redis://localhost:61004/0") -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.close()

    # --- TaskStore protocol ---

    async def create(self, task: FuzzingTask) -> FuzzingTask:
        try:
            pipe = self._redis.pipeline()
            pipe.set(f"task:{task.task_id}", task.model_dump_json())
            pipe.sadd(f"task_status:{task.status.value}", task.task_id)
            if task.status == TaskStatusEnum.PENDING:
                pipe.lpush("task_queue", task.task_id)
            await pipe.execute()
            return task
        except Exception:
            logger.exception("Redis create failed for task %s", task.task_id)
            raise

    async def get(self, task_id: str) -> FuzzingTask | None:
        raw = await self._redis.get(f"task:{task_id}")
        if raw is None:
            return None
        return FuzzingTask.model_validate_json(raw)

    async def update(self, task_id: str, **fields) -> FuzzingTask:
        raw = await self._redis.get(f"task:{task_id}")
        if raw is None:
            logger.error("Redis update failed: task %s not found", task_id)
            raise KeyError(f"Task not found: {task_id}")
        task = FuzzingTask.model_validate_json(raw)

        old_status = task.status.value
        updated = task.model_copy(update=fields)
        new_status = updated.status.value

        pipe = self._redis.pipeline()
        pipe.set(f"task:{task_id}", updated.model_dump_json())

        if old_status != new_status:
            pipe.srem(f"task_status:{old_status}", task_id)
            pipe.sadd(f"task_status:{new_status}", task_id)

        await pipe.execute()
        return updated

    async def list_tasks(
        self, status: TaskStatusEnum | None = None, offset: int = 0, limit: int = 50
    ) -> list[FuzzingTask]:
        if status is not None:
            task_ids = await self._redis.smembers(f"task_status:{status.value}")
        else:
            keys = await self._redis.keys("task:*")
            logger.debug("Redis KEYS task:* returned %d entries", len(keys))
            task_ids = {k.split(":", 1)[1] for k in keys}

        if not task_ids:
            return []

        pipe = self._redis.pipeline()
        for tid in task_ids:
            pipe.get(f"task:{tid}")
        raws = await pipe.execute()

        tasks = []
        for raw in raws:
            if raw is not None:
                tasks.append(FuzzingTask.model_validate_json(raw))

        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[offset : offset + limit]

    async def delete(self, task_id: str) -> bool:
        raw = await self._redis.get(f"task:{task_id}")
        if raw is None:
            return False
        task = FuzzingTask.model_validate_json(raw)

        pipe = self._redis.pipeline()
        pipe.delete(f"task:{task_id}")
        for status_val in TaskStatusEnum:
            pipe.srem(f"task_status:{status_val.value}", task_id)
        pipe.lrem("task_queue", 0, task_id)
        await pipe.execute()
        return True

    async def count_tasks(self, status: TaskStatusEnum | None = None) -> int:
        if status is not None:
            return await self._redis.scard(f"task_status:{status.value}")
        keys = await self._redis.keys("task:*")
        return len(keys)

    async def pop_pending(self) -> FuzzingTask | None:
        task_id = await self._redis.rpop("task_queue")
        if task_id is None:
            return None
        task = await self.get(task_id)
        if task is not None and task.status == TaskStatusEnum.PENDING:
            return task
        return None

    # --- Reconciliation helpers ---

    async def get_task_ids_by_status(self, status: TaskStatusEnum) -> set[str]:
        members = await self._redis.smembers(f"task_status:{status.value}")
        return set(members)
