import logging
from contextlib import contextmanager

import click
from tqdm.contrib.logging import logging_redirect_tqdm


class EmojiFormatter(logging.Formatter):
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


@contextmanager
def setup_logging(verbosity):
    match verbosity:
        case v if v > 0:
            level = logging.DEBUG
        case v if v < 0:
            level = logging.WARNING
        case _:
            level = logging.INFO

    console_handler = logging.StreamHandler()
    fmt = "%(levelemoji)s %(levelname)5.5s | %(message)s"
    console_handler.setFormatter(EmojiFormatter(fmt))

    logging.basicConfig(level=level, handlers=[console_handler])
    logging.captureWarnings(True)

    with logging_redirect_tqdm():
        yield


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
