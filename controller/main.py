"""CLI entry point for the FuzzAgent Controller."""

import argparse
import logging
import sys

import uvicorn

from controller.app import create_app
from controller.config import ControllerConfig

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d  %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_logging(config: ControllerConfig) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if config.log_file:
        file_handler = logging.FileHandler(config.log_file)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="FuzzAgent Controller Server")
    parser.add_argument("--host", type=str, default=None, help="Override host")
    parser.add_argument("--port", type=int, default=None, help="Override port")
    args = parser.parse_args()

    config = ControllerConfig.from_env()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    _setup_logging(config)

    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
