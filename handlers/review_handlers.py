import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import datetime
import zoneinfo

import database
import config
import scheduler_engine
import nlp_engine

logger = logging.getLogger(__name__)

CHECKLIST_STATE = 1
JOURNAL_INPUT = 2
ROLLOVER_CONFIRM = 3

async def nightly_review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today_dt = datetime.datetime.now(tz).date()
    today = str(today_dt)
    
    tasks = await database.get_tasks_for_date(user_id, today)
    if not tasks:
        await update.message.reply_text("شما امروز هیچ وظیفه‌ای نداشتید.")
        return ConversationHandler.END
        
    context.user_data['review_tasks'] = tasks
    context.user_data['review_index'] = 0
    context.user_data['review_date'] = today
    
    keyboard = []
    for task in tasks:
        tname = task.get('task_name', 'بدون نام')
        keyboard.append([
            InlineKeyboardButton(f"✅ انجام شد: {tname}", callback_data=f"mark_done:{task['id']}"),
            InlineKeyboardButton(f"❌ انجام نشد: {tname}", callback_data=f"mark_missed:{task['id']}")
        ])
        
    keyboard.append([InlineKeyboardButton("پایان بررسی و ثبت روز", callback_data='complete_review')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("بررسی شبانه. وضعیت وظایف امروز را مشخص کنید:", reply_markup=reply_markup)
    return CHECKLIST_STATE

async def mark_task_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split(':')[1])
    await database.update_task_status(task_id, 'done')
    
    await _update_review_keyboard(query, context)
    return CHECKLIST_STATE

async def mark_task_missed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split(':')[1])
    await database.update_task_status(task_id, 'skipped')
    
    await _update_review_keyboard(query, context)
    return CHECKLIST_STATE
    
async def _update_review_keyboard(query, context):
    user_id = query.from_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today = str(datetime.datetime.now(tz).date())
    
    tasks = await database.get_tasks_for_date(user_id, today)
    
    keyboard = []
    for task in tasks:
        tname = task.get('task_name', 'بدون نام')
        if task.get('status') == 'done':
            btn1 = InlineKeyboardButton(f"🟢 انجام شد: {tname}", callback_data=f"mark_done:{task['id']}")
            btn2 = InlineKeyboardButton(f"انجام نشد: {tname}", callback_data=f"mark_missed:{task['id']}")
        elif task.get('status') == 'skipped':
            btn1 = InlineKeyboardButton(f"انجام شد: {tname}", callback_data=f"mark_done:{task['id']}")
            btn2 = InlineKeyboardButton(f"🔴 انجام نشد: {tname}", callback_data=f"mark_missed:{task['id']}")
        else:
            btn1 = InlineKeyboardButton(f"✅ انجام شد: {tname}", callback_data=f"mark_done:{task['id']}")
            btn2 = InlineKeyboardButton(f"❌ انجام نشد: {tname}", callback_data=f"mark_missed:{task['id']}")
            
        keyboard.append([btn1, btn2])
        
    keyboard.append([InlineKeyboardButton("پایان بررسی و ثبت روز", callback_data='complete_review')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_reply_markup(reply_markup=reply_markup)

async def complete_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today = str(datetime.datetime.now(tz).date())
    
    tasks = await database.get_tasks_for_date(user_id, today)
    score, completed_minutes, planned_minutes = scheduler_engine.calculate_productivity_score(tasks)
    
    context.user_data['review_score'] = score
    context.user_data['review_completed_minutes'] = completed_minutes
    context.user_data['review_planned_minutes'] = planned_minutes
    
    user = await database.get_user(user_id)
    current_streak = user.get('streak_days', 0)
    
    if score >= 70:
        await database.increment_streak(user_id)
        current_streak += 1
        await award_badge_if_eligible(user_id, current_streak, context.bot)
    else:
        await database.reset_streak(user_id)
        current_streak = 0
        
    context.user_data['review_streak'] = current_streak
        
    rating = "🌟 عالی!" if score >= 80 else ("👍 خوب" if score >= 50 else "⚠️ نیاز به تلاش بیشتر")
    
    text = f"خلاصه امروز:\nامتیاز بهره‌وری: %{score}\nارزیابی: {rating}\n\nنکته، چالش یا دستاورد امروزت رو بنویس:"
    await query.edit_message_text(text)
    
    return JOURNAL_INPUT

async def receive_journal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today = str(datetime.datetime.now(tz).date())
    
    journal_text = update.message.text
    score = context.user_data.get('review_score', 0)
    planned_minutes = context.user_data.get('review_planned_minutes', 0)
    completed_minutes = context.user_data.get('review_completed_minutes', 0)
    current_streak = context.user_data.get('review_streak', 0)
    
    await database.save_journal(user_id, today, journal_text, score, planned_minutes, completed_minutes)
    
    insight = await nlp_engine.generate_productivity_insight(
        score, completed_minutes, planned_minutes, current_streak, journal_text
    )
    
    await update.message.reply_text(f"تحلیل هوش مصنوعی:\n{insight}")
    
    keyboard = [
        [InlineKeyboardButton("🔄 انتقال وظایف ناتمام به فردا", callback_data='rollover:yes')],
        [InlineKeyboardButton("✅ نه، پاک کن", callback_data='rollover:no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("آیا می‌خواهید وظایف انجام‌نشده به فردا منتقل شوند؟", reply_markup=reply_markup)
    return ROLLOVER_CONFIRM

async def confirm_rollover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == 'rollover:yes':
        tz = zoneinfo.ZoneInfo(config.TIMEZONE)
        today_dt = datetime.datetime.now(tz).date()
        today = str(today_dt)
        tomorrow = str(today_dt + datetime.timedelta(days=1))
        
        tasks = await database.get_tasks_for_date(user_id, today)
        
        missed = [t for t in tasks if t.get('status') in ['skipped', 'pending', None]]
        for t in missed:
            task_data_dict = {
                'task_name': t.get('task_name', ''),
                'emoji': t.get('emoji', ''),
                'estimated_minutes': t.get('estimated_minutes', 60),
                'is_anchor': t.get('is_anchor', False),
                'anchor_start': t.get('anchor_start'),
                'anchor_end': t.get('anchor_end'),
                'cognitive_load': t.get('cognitive_load', 'medium'),
            }
            await database.add_task(user_id, task_data_dict, tomorrow)
            
        await query.edit_message_text(f"{len(missed)} وظیفه به برنامه فردا منتقل شد. شب بخیر! 🌙")
    else:
        await query.edit_message_text("وظایف به فردا منتقل نشدند. شب بخیر! 🌙")
        
    return ConversationHandler.END

async def award_badge_if_eligible(user_id: int, streak: int, bot) -> None:
    badges = {
        10: ('streak_10', 'مدال برنزی استقامت 🥉'), 
        20: ('streak_20', 'مدال نقره‌ای پیوستگی 🥈'), 
        30: ('streak_30', 'مدال طلایی قهرمان 🥇')
    }
    if streak in badges:
        badge_type, badge_name = badges[streak]
        await database.award_badge(user_id, badge_type)
        await bot.send_message(chat_id=user_id, text=f"🎉 تبریک! شما به دلیل حفظ {streak} روز موفقیت‌آمیز، {badge_name} را دریافت کردید!")

async def nightly_review_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        users = await database.get_all_active_users()
        tz = zoneinfo.ZoneInfo(config.TIMEZONE)
        now = datetime.datetime.now(tz)
        
        for u in users:
            sleep_time_str = u.get('sleep_time')
            if not sleep_time_str:
                continue
                
            try:
                h, m = map(int, sleep_time_str.split(':'))
                sleep_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                
                # Adjust for times that have already passed or are early morning next day
                if h < 12 and now.hour >= 12:
                    sleep_dt += datetime.timedelta(days=1)
                elif h >= 12 and now.hour < 12:
                    sleep_dt -= datetime.timedelta(days=1)
                    
                time_diff = (sleep_dt - now).total_seconds() / 60.0
                
                # Trigger around 30 minutes before sleep (assuming 1-minute job precision)
                if 29 <= time_diff < 31:
                    await context.bot.send_message(
                        chat_id=u['user_id'],
                        text="🌙 زمان استراحت نزدیک است. آیا مایلید بررسی شبانه را انجام دهید؟\nلطفاً دستور /review را ارسال کنید."
                    )
            except Exception as e:
                logger.error(f"Error processing nightly review for user {u.get('user_id')}: {e}")
                
    except Exception as e:
        logger.error(f"Failed to execute nightly review job: {e}")
