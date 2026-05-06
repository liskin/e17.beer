import logging
from contextlib import contextmanager

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
def setup_logging():
    console_handler = logging.StreamHandler()
    fmt = "%(levelemoji)s %(levelname)5.5s | %(message)s"
    console_handler.setFormatter(EmojiFormatter(fmt))

    logging.basicConfig(level=logging.INFO, handlers=[console_handler])
    logging.captureWarnings(True)

    with logging_redirect_tqdm():
        yield
