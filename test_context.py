import asyncio
import contextvars
import logging
import logging.config

user_context = contextvars.ContextVar("username", default="-")

class UserContextFilter(logging.Filter):
    def filter(self, record):
        record.username = user_context.get()
        return True

def setup_logging():
    log_config = {
        "version": 1,
        "filters": {
            "user_context": {
                "()": UserContextFilter,
            }
        },
        "formatters": {
            "custom": {
                "format": "%(asctime)s %(levelname)-5s [u:%(username)s] %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "custom",
                "filters": ["user_context"],
                "level": "INFO",
            },
        },
        "root": {
            "level": "DEBUG",
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(log_config)

setup_logging()
logger = logging.getLogger(__name__)

async def my_task(user):
    user_context.set(user)
    logger.info("Doing some work")
    await asyncio.sleep(0.1)
    logger.info("Finished work")

async def main():
    logger.info("Outside context")
    await asyncio.gather(my_task("alice"), my_task("bob"))
    logger.info("Back outside")

asyncio.run(main())
