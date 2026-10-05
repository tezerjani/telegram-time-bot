"""
Live Deck Handlers — In-day live controls: extend, pause, skip tasks.
"""

import logging
import datetime
import zoneinfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database
import scheduler_engine
import config
import progress_tracker as pt

logger = logging.getLogger(__name__)


async def _get_today_tasks(user_id: int) -> list[dict]:
    """Helper: fetch today's tasks sorted by scheduled time."""
    date_str = scheduler_engine.get_today_date_str(config.TIMEZONE)
    return await database.get_tasks_for_date(user_id, date_str)


async def _find_current_task(tasks: list[dict]) -> dict | None:
    """Return the first pending or active task."""
    now = scheduler_engine.get_now(config.TIMEZONE)
    current_time = now.strftime("%H:%M")
    # Prefer a task whose window includes now
    for t in tasks:
        if t.get("status") in ("pending", "active"):
            sched_end = t.get("scheduled_end")
            if sched_end and sched_end >= current_time:
                return t
    # Fallback: first non-done task
    for t in tasks:
        if t.get("status") not in ("done", "skipped"):
            return t
    return None


def _format_task_line(task: dict, current: bool = False) -> str:
    emoji = task.get("emoji") or "🔹"
    name = task.get("task_name", "بدون نام")
    start = task.get("scheduled_start", "--:--")
    end = task.get("scheduled_end", "--:--")
    dur = task.get("estimated_minutes", 0)
    status = task.get("status", "pending")

    if status == "done":
        prefix = "✅"
    elif status == "skipped":
        prefix = "⏩"
    elif current:
        prefix = "👉"
    else:
        prefix = "⬜"

    return f"{prefix} {emoji} {name} | {start}–{end} ({dur}د)"


async def send_live_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deck — Show current task and live control buttons."""
    user_id = update.effective_user.id
    tasks = await _get_today_tasks(user_id)

    if not tasks:
        await update.message.reply_text(
            "📭 شما امروز هیچ برنامه‌ای ندارید.\n"
            "برای ایجاد برنامه از /plan یا /apply_weekly استفاده کنید."
        )
        return

    current_task = await _find_current_task(tasks)

    if not current_task:
        await update.message.reply_text("🎉 تمام وظایف امروز انجام شده‌اند!")
        return

    task_name = current_task.get("task_name", "بدون نام")
    emoji = current_task.get("emoji") or "🔹"
    dur = current_task.get("estimated_minutes", 0)
    start = current_task.get("scheduled_start", "--:--")
    end = current_task.get("scheduled_end", "--:--")
    task_id = current_task.get("id", 0)

    card_text = (
        f"🎯 *وظیفه فعلی*\n\n"
        f"{emoji} *{task_name}*\n"
        f"⏰ {start} ← {end}  |  ⏱ {dur} دقیقه\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("⏱ ۳۰ دقیقه تمدید", callback_data="extend:30"),
            InlineKeyboardButton("⏸ توقف اضطراری", callback_data="emergency_pause"),
        ],
        [
            InlineKeyboardButton("⏩ رد کردن پارت", callback_data="skip_task"),
            InlineKeyboardButton("📋 نمای کلی برنامه", callback_data="show_overview"),
        ],
        [InlineKeyboardButton("🔄 بروزرسانی وضعیت", callback_data=f"refresh_progress:{task_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="Markdown")


async def extend_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data='extend:30' — Extend current task by N minutes."""
    query = update.callback_query
    await query.answer()

    extra = int(query.data.split(":")[1])
    user_id = update.effective_user.id
    tasks = await _get_today_tasks(user_id)

    current_task = await _find_current_task(tasks)
    if not current_task:
        await query.edit_message_text("هیچ وظیفه فعالی یافت نشد.")
        return

    task_id = current_task["id"]
    updated_tasks = scheduler_engine.extend_task(tasks, task_id, extra)

    # Persist updated scheduled times for all affected tasks
    for t in updated_tasks:
        if t.get("scheduled_start") and t.get("scheduled_end"):
            await database.update_task_scheduled_times(
                t["id"], t["scheduled_start"], t["scheduled_end"]
            )

    task_name = current_task.get("task_name", "وظیفه")
    await query.edit_message_text(
        f"⏱ وظیفه *{task_name}* تا {extra} دقیقه تمدید شد.\n"
        f"زمان‌بندی بقیه وظایف بروزرسانی شد.",
        parse_mode="Markdown",
    )


async def emergency_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data='emergency_pause' — Show pause duration picker."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("۱۵ دقیقه", callback_data="pause_for:15"),
            InlineKeyboardButton("۳۰ دقیقه", callback_data="pause_for:30"),
            InlineKeyboardButton("۴۵ دقیقه", callback_data="pause_for:45"),
            InlineKeyboardButton("۶۰ دقیقه", callback_data="pause_for:60"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "⏸ چند دقیقه توقف اضطراری نیاز دارید؟", reply_markup=reply_markup
    )


async def confirm_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data='pause_for:N' — Apply emergency pause."""
    query = update.callback_query
    await query.answer()

    minutes = int(query.data.split(":")[1])
    user_id = update.effective_user.id
    tasks = await _get_today_tasks(user_id)

    current_task = await _find_current_task(tasks)
    if not current_task:
        await query.edit_message_text("هیچ وظیفه فعالی یافت نشد.")
        return

    now = scheduler_engine.get_now(config.TIMEZONE)
    pause_until = (now + datetime.timedelta(minutes=minutes)).strftime("%H:%M")

    updated_tasks = scheduler_engine.emergency_pause(tasks, current_task["id"], pause_until)

    for t in updated_tasks:
        if t.get("scheduled_start") and t.get("scheduled_end"):
            await database.update_task_scheduled_times(
                t["id"], t["scheduled_start"], t["scheduled_end"]
            )

    await query.edit_message_text(
        f"⏸ توقف {minutes} دقیقه‌ای اعمال شد.\n"
        f"ادامه برنامه از ساعت {pause_until}",
    )


async def skip_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data='skip_task' — Mark current task as skipped."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    tasks = await _get_today_tasks(user_id)
    current_task = await _find_current_task(tasks)

    if not current_task:
        await query.edit_message_text("هیچ وظیفه فعالی یافت نشد.")
        return

    await database.update_task_status(current_task["id"], "skipped")

    task_name = current_task.get("task_name", "وظیفه")
    await query.edit_message_text(f"⏩ وظیفه *{task_name}* رد شد.", parse_mode="Markdown")


async def refresh_progress_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data='refresh_progress:TASK_ID' — Force-refresh progress card."""
    query = update.callback_query
    user_id = update.effective_user.id

    # Get the shared tracker from bot_data if present, else just answer
    tracker: pt.TaskProgressTracker | None = context.bot_data.get("progress_tracker")
    if tracker:
        await tracker.handle_refresh_callback(query, user_id)
    else:
        await query.answer("🔄 بروزرسانی شد")


async def show_overview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data='show_overview' — Show full day schedule as text."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    tasks = await _get_today_tasks(user_id)
    current_task = await _find_current_task(tasks)

    if not tasks:
        await query.message.reply_text("📭 امروز هیچ برنامه‌ای ندارید.")
        return

    lines = ["📋 *نمای کلی برنامه امروز:*\n"]
    for t in tasks:
        is_current = current_task and t.get("id") == current_task.get("id")
        lines.append(_format_task_line(t, current=is_current))

    # Summary stats
    done = sum(1 for t in tasks if t.get("status") == "done")
    total = len(tasks)
    lines.append(f"\n✅ {done} از {total} وظیفه انجام شده")

    await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
