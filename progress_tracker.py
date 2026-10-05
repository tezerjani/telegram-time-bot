import asyncio
import datetime
import logging

import telegram

try:
    import database
    import config
    _HAS_CONFIG = True
except ImportError:
    _HAS_CONFIG = False

logger = logging.getLogger(__name__)

# Use config value if available, else fallback
_UPDATE_INTERVAL = config.TASK_UPDATE_INTERVAL_MINUTES if _HAS_CONFIG else 12


def build_progress_bar(percent: float, width: int = 10) -> str:
    """Returns string like `▰▰▰▰▱▱▱▱▱▱` for 40%."""
    percent = max(0.0, min(100.0, percent))
    filled = int((percent / 100.0) * width)
    empty = width - filled
    return "▰" * filled + "▱" * empty


def build_progress_card(
    task: dict, elapsed_minutes: float, total_minutes: int
) -> tuple[str, telegram.InlineKeyboardMarkup]:
    """Returns (message_text, keyboard)."""
    emoji = task.get("emoji") or ""
    task_name = task.get("task_name") or task.get("name") or "وظیفه"
    start_time = task.get("scheduled_start", "--:--")
    end_time = task.get("scheduled_end", "--:--")
    task_id = task.get("id")

    if total_minutes <= 0:
        percent = 100.0
        remaining = 0
    else:
        percent = min(100.0, (elapsed_minutes / total_minutes) * 100)
        remaining = max(0, total_minutes - int(elapsed_minutes))

    progress_bar = build_progress_bar(percent)
    name_display = f"{emoji} {task_name}".strip()

    message_text = (
        f"{name_display}\n"
        f"{progress_bar} {percent:.0f}% | {remaining} دقیقه مانده\n"
        f"⏰ شروع: {start_time} | پایان: {end_time}"
    )

    keyboard = telegram.InlineKeyboardMarkup(
        [[telegram.InlineKeyboardButton("🔄 بروزرسانی وضعیت", callback_data=f"refresh_progress:{task_id}")]]
    )

    return message_text, keyboard


def build_completion_card(task: dict) -> str:
    emoji = task.get("emoji") or ""
    task_name = task.get("task_name") or task.get("name") or "وظیفه"
    return f"✨ پارت {emoji} {task_name} با موفقیت تمام شد!".strip()


class TaskProgressTracker:
    def __init__(self, bot: telegram.Bot):
        self.bot = bot
        self._tracking_tasks: dict[int, asyncio.Task] = {}
        self._last_updates: dict[int, datetime.datetime] = {}
        self._active_task_data: dict[int, dict] = {}

    async def start_task_tracking(self, chat_id: int, user_id: int, task: dict) -> None:
        """Send initial progress card and start the update loop."""
        await self.stop_tracking(user_id)

        total_minutes = task.get("estimated_minutes") or task.get("duration") or 30
        text, kb = build_progress_card(task, 0, total_minutes)

        try:
            msg = await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
        except Exception as e:
            logger.error("Failed to send initial progress card: %s", e)
            return

        # Persist progress message record
        if _HAS_CONFIG:
            try:
                task_id = task.get("id") or 0
                await database.save_progress_message(user_id, chat_id, msg.message_id, task_id)
            except Exception as e:
                logger.warning("Could not save progress message to DB: %s", e)

        self._active_task_data[user_id] = {
            "task": task,
            "message_id": msg.message_id,
            "chat_id": chat_id,
            "start_time": datetime.datetime.now(),
            "total_minutes": total_minutes,
        }
        self._last_updates[user_id] = datetime.datetime.now()

        loop_task = asyncio.create_task(self._update_loop(user_id))
        self._tracking_tasks[user_id] = loop_task

    async def _update_loop(self, user_id: int):
        while True:
            await asyncio.sleep(_UPDATE_INTERVAL * 60)
            await self.update_progress(user_id)

    async def update_progress(self, user_id: int, force: bool = False) -> bool:
        """Edits the existing progress message."""
        if user_id not in self._active_task_data:
            return False
            
        now = datetime.datetime.now()
        last_upd = self._last_updates.get(user_id)
        
        if not force and last_upd:
            diff_mins = (now - last_upd).total_seconds() / 60
            if diff_mins < _UPDATE_INTERVAL:
                return False
                
        data = self._active_task_data[user_id]
        task = data['task']
        chat_id = data['chat_id']
        msg_id = data['message_id']
        start_time = data['start_time']
        total_minutes = data['total_minutes']
        
        elapsed_minutes = (now - start_time).total_seconds() / 60
        
        if elapsed_minutes >= total_minutes:
            # Complete
            text = build_completion_card(task)
            try:
                await self.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
            except Exception as e:
                logger.error("Failed to edit completion card: %s", e)
            await self.stop_tracking(user_id)
            if _HAS_CONFIG:
                try:
                    await database.delete_progress_message(user_id)
                except Exception:
                    pass
            return True
        
        text, kb = build_progress_card(task, elapsed_minutes, total_minutes)
        try:
            await self.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=kb)
            self._last_updates[user_id] = now
            return True
        except telegram.error.BadRequest as e:
            if "Message is not modified" in str(e):
                self._last_updates[user_id] = now
                return True
            logger.error(f"Failed to update progress: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in update progress: {e}")
            return False

    async def stop_tracking(self, user_id: int) -> None:
        """Cancels the tracking loop for this user."""
        if user_id in self._tracking_tasks:
            self._tracking_tasks[user_id].cancel()
            del self._tracking_tasks[user_id]
            
        if user_id in self._active_task_data:
            del self._active_task_data[user_id]
            
        if user_id in self._last_updates:
            del self._last_updates[user_id]

    async def handle_refresh_callback(
        self,
        query: telegram.CallbackQuery,
        user_id: int
    ) -> None:
        """Handles the manual refresh button."""
        await query.answer("بروزرسانی شد🔄")
        await self.update_progress(user_id, force=True)
