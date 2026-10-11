"""Health check endpoint."""

import asyncio
import logging
import time

from fastapi import APIRouter, Request

from controller import __version__
from controller.models import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()


async def _check_docker() -> str:
    """Check Docker daemon availability with 2s timeout."""
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "docker", "info", "--format", "{{.ServerVersion}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=2.0,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            return "ok"
        logger.warning("Docker check failed (rc=%d): %s", proc.returncode, stderr.decode(errors="replace").strip())
        return "unavailable"
    except asyncio.TimeoutError:
        logger.warning("Docker check timed out")
        return "unavailable"
    except Exception as e:
        logger.warning("Docker check failed: %s", e)
        return "unavailable"


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    logger.debug("Health check requested")
    started_at: float = request.app.state.started_at
    docker_status = await _check_docker()
    logger.debug("Health check result: docker=%s", docker_status)
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=round(time.time() - started_at, 1),
        docker=docker_status,
    )
