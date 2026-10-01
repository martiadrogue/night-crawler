"""Logging setup from `logging_config.yaml`."""

import logging.config

import yaml
from night_crawler.core.config import get_settings


def setup_logging() -> None:
    """Configure logging from `logging_config.yaml`."""
    settings = get_settings()
    log_level = "DEBUG" if "development" == settings.app_env else "INFO"

    with open("logging_config.yaml", "r") as config_file:
        config = yaml.safe_load(config_file)

    config["handlers"]["console"]["level"] = log_level
    config["loggers"]["uvicorn"]["level"] = log_level
    config["loggers"]["night_crawler"]["level"] = log_level

    logging.config.dictConfig(config)
