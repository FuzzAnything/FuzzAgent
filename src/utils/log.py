import os
import datetime
import logging
from src.utils.project import get_log_dir

# Logger setup
def get_logger(name: str) -> logging.Logger:
    """
    Get the logger object.
    """
    formatted_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.path.join(get_log_dir(), f"{name}_{formatted_now}.log")
    logging.basicConfig(
        level=logging.INFO,
        filename=log_file,
        filemode="w",
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(name)
    return logger
