"""Unified environment variable reading and path resolution.

No filesystem access happens at import time.  Call sites validate paths
lazily when the data is actually needed.
"""

import os
from dataclasses import dataclass

from .errors import AnalysisError


@dataclass
class AnalysisConfig:
    """Paths derived from the OUTPUT environment variable (or explicit arg)."""

    output_dir: str
    cache_dir: str
    log_dir: str
    vms_dir: str
    introspector_dir: str
    build_dir: str
    fuzzers_dir: str
    cache_fuzzers_dir: str
    cache_coverage_dir: str
    project_name: str

    @classmethod
    def from_env(cls) -> "AnalysisConfig":
        output = os.getenv("OUTPUT")
        if not output:
            raise AnalysisError(
                "OUTPUT environment variable is not set. "
                "Set it to the directory containing the fuzzing output."
            )
        return cls.from_output_dir(output)

    @classmethod
    def from_output_dir(cls, output_dir: str) -> "AnalysisConfig":
        name = os.path.basename(os.path.normpath(output_dir))
        return cls(
            output_dir=output_dir,
            cache_dir=os.path.join(output_dir, ".cache"),
            log_dir=os.path.join(output_dir, ".cache", "logs"),
            vms_dir=os.path.join(output_dir, ".vms"),
            introspector_dir=os.path.join(output_dir, ".cache", "introspector"),
            build_dir=os.path.join(output_dir, "build"),
            fuzzers_dir=os.path.join(output_dir, "fuzzers"),
            cache_fuzzers_dir=os.path.join(output_dir, ".cache", "fuzzers"),
            cache_coverage_dir=os.path.join(output_dir, ".cache", "coverage"),
            project_name=name,
        )

    def ensure_introspector_dir(self) -> None:
        os.makedirs(self.introspector_dir, exist_ok=True)

    def require_dir(self, path: str, name: str) -> None:
        """Validate that *path* exists and is a directory."""
        if not os.path.isdir(path):
            from .errors import PathMissingError

            raise PathMissingError(name, path)

    def require_file(self, path: str, name: str) -> None:
        """Validate that *path* exists and is a file."""
        if not os.path.isfile(path):
            from .errors import PathMissingError

            raise PathMissingError(name, path)
