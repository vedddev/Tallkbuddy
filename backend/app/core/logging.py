"""Application logging setup."""

import logging.config


def configure_logging(level: str) -> None:
    """Set up console logging without disabling framework loggers."""

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {"()": "app.core.observability.SafeJsonFormatter"}
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                }
            },
            "root": {"level": level, "handlers": ["console"]},
        }
    )
