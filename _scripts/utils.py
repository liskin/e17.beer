import copy
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar

import click
from dotenv import load_dotenv
from google.maps import places_v1

_log_context: ContextVar[str] = ContextVar("log_context", default="")


class ContextFormatterMixin:
    def format(self, record):
        record.context = _log_context.get()
        return super().format(record)


class EmojiFormatterMixin:
    LEVEL_EMOJIS = {
        logging.DEBUG: "💡",
        logging.INFO: "✅",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "🔥",
    }

    def format(self, record):
        record.levelemoji = self.LEVEL_EMOJIS.get(record.levelno, record.levelname)
        return super().format(record)


class MultilineFormatterMixin:
    def format(self, record):
        s = record.getMessage()
        if "\n" not in s:
            return super().format(record)
        else:
            lines = s.splitlines()
            formatted_lines = []
            for line in lines:
                rec = copy.copy(record)
                rec.args = None
                rec.msg = line
                formatted_lines.append(super().format(rec))
            return "\n".join(formatted_lines)


class Formatter(ContextFormatterMixin, EmojiFormatterMixin, MultilineFormatterMixin, logging.Formatter):
    def __init__(self):
        fmt = "%(levelemoji)s %(levelname)5.5s | %(context)s%(message)s"
        super().__init__(fmt)


@contextmanager
def logging_context(context: str):
    """Context manager to add temporary data to logs."""
    saved_log_context = _log_context.set(_log_context.get() + context + " | ")
    try:
        yield
    finally:
        _log_context.reset(saved_log_context)


def setup_logging(verbosity):
    match verbosity:
        case v if v > 0:
            level = logging.DEBUG
        case v if v < 0:
            level = logging.WARNING
        case _:
            level = logging.INFO

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(Formatter())

    logging.basicConfig(level=level, handlers=[console_handler])


def click_option_verbosity():
    verbose = click.option(
        "--verbose",
        "verbosity",
        flag_value=1,
        default=0,
    )
    quiet = click.option(
        "--quiet",
        "verbosity",
        flag_value=-1,
        default=0,
    )
    return lambda f: verbose(quiet(f))


def get_places_client() -> places_v1.PlacesClient:
    load_dotenv()

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise ValueError("No API Key found! Check your .env file.")

    return places_v1.PlacesClient(client_options={"api_key": api_key})
