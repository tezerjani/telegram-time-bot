"""
Message Cleaner — Ephemeral/transient message self-destruct system.
Tracks temporary messages and deletes them after TTL expires.
"""

import asyncio
import datetime
import logging

import telegram
import telegram.ext

import database
import config

logger = logging.getLogger(__name__)


class MessageCleaner:
    def __init__(self, bot: telegram.Bot):
        self.bot = bot

    async def schedule_delete(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        delay_seconds: int = config.EPHEMERAL_TTL_SECONDS,
    ) -> None:
        """
        Track a message for deletion and schedule its removal.
        Saves to DB so the record survives container restarts.
        """
        delete_at = (
            datetime.datetime.utcnow() + datetime.timedelta(seconds=delay_seconds)
        ).strftime("%Y-%m-%dT%H:%M:%S")

        try:
            await database.track_ephemeral(user_id, chat_id, message_id, delete_at)
        except Exception as e:
            logger.warning("Could not track ephemeral in DB: %s", e)

        # Also fire-and-forget in-process deletion for low-latency cleanup
        asyncio.create_task(self._delete_after_delay(chat_id, message_id, delay_seconds))

    async def _delete_after_delay(self, chat_id: int, message_id: int, delay: int) -> None:
        """Sleep then delete. Silently ignores 'message not found' errors."""
        await asyncio.sleep(delay)
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except telegram.error.BadRequest as e:
            if "Message to delete not found" in str(e) or "message can't be deleted" in str(e).lower():
                pass  # already gone, no problem
            else:
                logger.warning("BadRequest deleting message %s in %s: %s", message_id, chat_id, e)
        except Exception as e:
            logger.error("Unexpected error deleting message %s in %s: %s", message_id, chat_id, e)

    async def process_expired_ephemerals(self) -> int:
        """
        Pull expired ephemeral records from DB and delete their messages.
        Called by the JobQueue cleanup job every 60 seconds.
        Returns count of deleted messages.
        """
        current_time = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        deleted_count = 0

        try:
            expired_records = await database.get_expired_ephemerals(current_time)
        except Exception as e:
            logger.error("Could not fetch expired ephemerals: %s", e)
            return 0

        for record in expired_records:
            chat_id = record.get("chat_id")
            message_id = record.get("message_id")
            record_id = record.get("id")

            # Attempt deletion
            try:
                await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
                deleted_count += 1
            except telegram.error.BadRequest as e:
                if "Message to delete not found" not in str(e):
                    logger.warning(
                        "Failed deleting ephemeral msg %s in %s: %s", message_id, chat_id, e
                    )
            except Exception as e:
                logger.error(
                    "Unexpected error deleting ephemeral msg %s in %s: %s", message_id, chat_id, e
                )

            # Remove DB record regardless of whether deletion succeeded
            if record_id:
                try:
                    await database.delete_ephemeral_record(record_id)
                except Exception as e:
                    logger.warning("Could not remove ephemeral record %s: %s", record_id, e)

        return deleted_count


async def cleanup_job(context: telegram.ext.CallbackContext) -> None:
    """JobQueue periodic job: delete expired ephemeral messages."""
    cleaner = MessageCleaner(context.bot)
    count = await cleaner.process_expired_ephemerals()
    if count > 0:
        logger.debug("Cleaned up %d expired ephemeral messages", count)
