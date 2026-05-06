import copy
import logging

import click


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


class Formatter(EmojiFormatterMixin, MultilineFormatterMixin, logging.Formatter):
    pass


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
    console_handler.setFormatter(Formatter(fmt))

    logging.basicConfig(level=level, handlers=[console_handler])
    logging.captureWarnings(True)


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
