"""Docker container lifecycle management for the FuzzAgent Controller."""

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass

from controller.compose_generator import ComposeGenerator
from controller.exceptions import DockerComposeError, DockerLaunchError
from controller.models import FuzzingTask

logger = logging.getLogger(__name__)


@dataclass
class DockerLaunchResult:
    container_id: str
    container_name: str
    compose_dir: str


class DockerLauncher:
    """Launches and manages Docker containers for fuzzing tasks."""

    def __init__(self) -> None:
        self.compose_generator = ComposeGenerator()

    async def launch(self, task: FuzzingTask) -> DockerLaunchResult:
        compose_file = self.compose_generator.generate(task)

        logger.info("Launching container for task %s via %s", task.task_id, compose_file)

        await self._remove_existing_container(task.container_name)

        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-p", task.container_name,
            "-f", str(compose_file), "up", "-d",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise DockerComposeError(
                cmd=["docker", "compose", "up", "-d"],
                returncode=proc.returncode if proc.returncode is not None else -1,
                stderr=stderr.decode(errors="replace"),
            )

        container_name = task.container_name
        container_id = await self._get_container_id(container_name)

        if not container_id:
            raise DockerLaunchError(task.task_id, "Failed to get container ID after compose up")

        logger.info("Container %s started (id=%s)", container_name, container_id[:12])
        return DockerLaunchResult(
            container_id=container_id,
            container_name=container_name,
            compose_dir=str(compose_file.parent),
        )

    async def _remove_existing_container(self, container_name: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "Pre-launch cleanup: docker rm -f %s returned rc=%s: %s",
                container_name,
                proc.returncode,
                stderr.decode(errors="replace").strip() if stderr else "",
            )
        else:
            logger.debug("Pre-launch cleanup: ensured %s is fresh", container_name)

    async def stop(self, task: FuzzingTask) -> None:
        if not task.compose_dir:
            return

        compose_file = str(Path(task.compose_dir) / "docker-compose.yml")
        logger.info("Stopping container for task %s", task.task_id)

        # 正常路径：用 compose down（同时停 service + 清 network）
        if Path(compose_file).exists():
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-p", task.container_name,
                "-f", compose_file, "down",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return
            logger.warning(
                "docker compose down failed for task %s (rc=%s): %s",
                task.task_id,
                proc.returncode,
                stderr.decode(errors="replace").strip() if stderr else "",
            )
            # 继续走 fallback
        else:
            logger.info(
                "stop: compose file missing for task %s, falling back to docker rm -f",
                task.task_id,
            )

        # Fallback：compose 文件丢了或 compose down 失败，直接按容器名 kill。
        # container_name 同时是 compose 的 service 容器名和 docker rm 的目标。
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", task.container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "docker rm -f failed for container %s (rc=%s): %s",
                task.container_name,
                proc.returncode,
                stderr.decode(errors="replace").strip() if stderr else "",
            )

    async def stop_container_by_id(self, container_id: str) -> None:
        """Force-remove a container by ID.

        Used by cancel_analysis: the parent fuzz task's compose_dir is not the
        analysis compose_dir, and the analysis FuzzingTask record is not
        persisted, so we cannot reconstruct a FuzzingTask to feed to stop().
        docker rm -f by container ID is the cleanest reach.
        """
        logger.info("Force-removing container %s", container_id[:12])
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "docker rm -f failed for container %s (rc=%s): %s",
                container_id[:12],
                proc.returncode,
                stderr.decode(errors="replace").strip() if stderr else "",
            )

    async def get_container_status(self, container_id: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.Status}}", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("Failed to inspect container %s: %s", container_id[:12], stderr.decode(errors="replace"))
            return "unknown"

        return stdout.decode().strip()

    async def get_exit_code(self, container_id: str) -> int:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.ExitCode}}", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("Failed to get exit code for container %s: %s", container_id[:12], stderr.decode(errors="replace").strip())
            return -1

        try:
            return int(stdout.decode().strip())
        except ValueError:
            logger.warning("Unexpected exit code format for container %s: %r", container_id[:12], stdout.decode().strip())
            return -1

    async def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "--tail", str(tail), container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("Failed to fetch logs for container %s", container_id[:12])
            return f"Failed to fetch logs for container {container_id[:12]}"

        return stdout.decode(errors="replace")

    async def _get_container_id(self, container_name: str) -> str | None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "-q", "--filter", f"name={container_name}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("docker ps failed for %s: %s", container_name, stderr.decode(errors="replace").strip())
            return None

        output = stdout.decode().strip()
        return output.split("\n")[0] if output else None
