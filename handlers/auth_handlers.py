"""
Auth Handlers — Whitelist subscription requests & Admin approval buttons.
All database calls are properly awaited.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import telegram.error

import database
import config

logger = logging.getLogger(__name__)

AWAITING_NONE = 0


def is_authorized(user_id: int) -> bool:
    """Sync stub — always returns True. Actual auth is done async via check_authorization."""
    return True


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Async authorization check. Returns True if user is active.
    Sends a rejection message if not authorized.
    """
    user_id = update.effective_user.id
    
    # Auto-authorize admin
    if config.ADMIN_ID and user_id == config.ADMIN_ID:
        return True

    user = await database.get_user(user_id)
    if user and user.get("status") == "active":
        return True

    msg = "⛔ شما دسترسی لازم را ندارید. لطفاً با /start درخواست دسترسی بدهید."
    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await update.callback_query.answer(msg, show_alert=True)
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — entry point for new and existing users."""
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    full_name = user.full_name or ""

    # SPECIAL CASE: The user is the Admin!
    if config.ADMIN_ID and user_id == config.ADMIN_ID:
        db_user = await database.get_user(user_id)
        if db_user is None:
            await database.create_user(user_id, username, full_name)
        await database.update_user_status(user_id, "active")

        streak = db_user.get("streak_days", 0) if db_user else 0
        streak_line = f"\n🔥 رکورد پیوستگی: {streak} روز" if streak > 0 else ""
        
        await update.message.reply_text(
            f"👑 سلام ادمین عزیز ({full_name})! خوش آمدید.{streak_line}\n\n"
            "شما دسترسی کامل به تمامی بخش‌های ربات دارید:\n\n"
            "📅 شروع برنامه‌ریزی امروز: /plan\n"
            "🎯 دک کنترل زنده: /deck\n"
            "🌙 بررسی و یادداشت شبانه: /review\n"
            "📊 آمار و تحلیل: /mystats\n"
            "⚙️ پنل مدیریت کاربران: /admin"
        )
        return

    # Regular users
    db_user = await database.get_user(user_id)

    if db_user is None:
        await database.create_user(user_id, username, full_name)

        await update.message.reply_text(
            "👋 سلام!\n\n"
            "درخواست دسترسی شما برای ادمین ارسال شد.\n"
            "لطفاً منتظر تایید بمانید. ⏳"
        )

        await _notify_admin_new_user(context.bot, user_id, full_name, username)

    else:
        status = db_user.get("status")
        if status == "active":
            streak = db_user.get("streak_days", 0)
            streak_line = f"\n🔥 رکورد فعلی: {streak} روز" if streak > 0 else ""
            await update.message.reply_text(
                f"🎉 خوش برگشتی، {full_name}!{streak_line}\n\n"
                "برای شروع برنامه‌ریزی امروز: /plan\n"
                "مشاهده دک زنده: /deck\n"
                "بررسی شبانه: /review"
            )
        elif status == "banned":
            await update.message.reply_text("⛔ متأسفیم، دسترسی شما به ربات مسدود شده است.")
        elif status == "pending":
            keyboard = [
                [InlineKeyboardButton("🔄 ارسال مجدد درخواست به ادمین", callback_data=f"resend_request:{user_id}")]
            ]
            await update.message.reply_text(
                "⏳ درخواست شما هنوز در دست بررسی است. به محض تایید ادمین مطلع خواهید شد.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


async def _notify_admin_new_user(bot, user_id: int, full_name: str, username: str) -> None:
    """Helper to send approval request to ADMIN_ID safely."""
    if not config.ADMIN_ID:
        logger.warning("ADMIN_ID is not configured. Cannot notify admin.")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ تایید دسترسی", callback_data=f"approve_user:{user_id}"),
            InlineKeyboardButton("❌ رد / مسدودسازی", callback_data=f"reject_user:{user_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=config.ADMIN_ID,
            text=(
                f"🔔 درخواست دسترسی جدید به ربات:\n\n"
                f"👤 نام: {full_name}\n"
                f"🪪 یوزرنیم: @{username}\n"
                f"🆔 شناسه: {user_id}"
            ),
            reply_markup=reply_markup,
        )
        logger.info(f"Access request for user {user_id} successfully sent to admin {config.ADMIN_ID}")
    except telegram.error.BadRequest as e:
        logger.error(f"Failed to notify admin {config.ADMIN_ID}: {e}. Make sure the admin has sent /start to the bot!")
    except Exception as e:
        logger.error(f"Unexpected error notifying admin: {e}")


async def resend_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User taps resend request button."""
    query = update.callback_query
    await query.answer("درخواست مجدداً به ادمین ارسال شد.", show_alert=True)
    user = update.effective_user
    await _notify_admin_new_user(context.bot, user.id, user.full_name or "", user.username or "")


async def approve_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles admin approval of a pending user."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":")[1])
    await database.update_user_status(user_id, "active")

    await query.edit_message_text(f"✅ کاربر {user_id} با موفقیت تایید شد.")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 تبریک! دسترسی شما به ربات تایید شد.\n\n"
                "اکنون می‌توانید از تمام امکانات استفاده کنید.\n"
                "برای شروع اولین برنامه‌ریزی: /plan"
            ),
        )
    except Exception as exc:
        logger.warning("Could not notify approved user %s: %s", user_id, exc)


async def reject_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles admin rejection of a pending user."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":")[1])
    await database.update_user_status(user_id, "banned")

    await query.edit_message_text(f"❌ درخواست کاربر {user_id} رد و مسدود شد.")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="⛔ متأسفیم، درخواست دسترسی شما توسط مدیریت تایید نشد.",
        )
    except Exception as exc:
        logger.warning("Could not notify rejected user %s: %s", user_id, exc)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin — Admin dashboard (ADMIN_ID only)."""
    if update.effective_user.id != config.ADMIN_ID:
        await update.message.reply_text("⛔ این دستور فقط مخصوص مدیر اصلی ربات است.")
        return

    active_users = await database.get_all_active_users()
    pending_users = await database.get_pending_users()

    header = (
        f"📊 *داشبورد مدیریت ربات*\n\n"
        f"👥 کاربران فعال: {len(active_users)}\n"
        f"⏳ درخواست‌های در انتظار: {len(pending_users)}\n"
    )
    await update.message.reply_text(header, parse_mode="Markdown")

    if pending_users:
        await update.message.reply_text(
            f"⏳ *{len(pending_users)} کاربر در انتظار تایید:*", parse_mode="Markdown"
        )
        for u in pending_users:
            uid = u["user_id"]
            uname = u.get("username") or "بدون یوزرنیم"
            fname = u.get("full_name") or "—"
            keyboard = [
                [
                    InlineKeyboardButton("✅ تایید", callback_data=f"approve_user:{uid}"),
                    InlineKeyboardButton("❌ رد", callback_data=f"reject_user:{uid}"),
                ]
            ]
            await update.message.reply_text(
                f"👤 {fname} (@{uname})\n🆔 `{uid}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

    if active_users:
        for u in active_users:
            uid = u["user_id"]
            if uid == config.ADMIN_ID:
                continue
            uname = u.get("username") or str(uid)
            fname = u.get("full_name") or "—"
            streak = u.get("streak_days", 0)

            keyboard = [
                [InlineKeyboardButton("🗑 لغو دسترسی", callback_data=f"revoke_user:{uid}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"👤 {fname} (@{uname})\n🆔 `{uid}` | 🔥 {streak} روز",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )


async def revoke_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke a user's access (ban them)."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":")[1])
    await database.update_user_status(user_id, "banned")

    await query.edit_message_text(f"🗑 دسترسی کاربر {user_id} لغو شد.")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="⛔ دسترسی شما توسط مدیر لغو شد.",
        )
    except Exception:
        pass


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/broadcast <message> — Send a message to all active users (ADMIN_ID only)."""
    if update.effective_user.id != config.ADMIN_ID:
        return

    text_parts = update.message.text.split(maxsplit=1)
    if len(text_parts) < 2:
        await update.message.reply_text("نحوه استفاده:\n/broadcast <متن پیام شما>")
        return

    msg = text_parts[1]
    active_users = await database.get_all_active_users()

    sent = 0
    failed = 0
    for u in active_users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=msg)
            sent += 1
        except Exception as exc:
            logger.warning("Broadcast failed for user %s: %s", u["user_id"], exc)
            failed += 1

    await update.message.reply_text(
        f"📣 پیام همگانی ارسال شد:\n✅ موفق: {sent}\n❌ ناموفق: {failed}"
    )
