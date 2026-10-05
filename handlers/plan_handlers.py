"""
Plan Handlers — Interactive inline keyboard flow, custom duration input,
manual/auto schedule modes, bulk text, voice and photo task intake.
"""

import logging
import datetime
import zoneinfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

import database
import config
import scheduler_engine
import nlp_engine
import duration_parser
import visual_engine

logger = logging.getLogger(__name__)

ASKING_WAKE_TIME = 1
ASKING_SLEEP_TIME = 2
ASKING_MODE = 3
ASKING_TASK_NAME = 4
ASKING_DURATION = 5
ASKING_CUSTOM_DURATION = 6
ASKING_ANCHOR = 7
ASKING_ANCHOR_TIME = 8
ASKING_COGNITIVE_LOAD = 9
CONFIRMING_PLAN = 10
EDITING_TASK = 11

FINISH_KEYWORDS = {"اتمام", "تمام", "پایان", "تموم", "ثبت", "finish", "done", "end"}


async def new_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("06:00", callback_data="wake:06:00"),
            InlineKeyboardButton("07:00", callback_data="wake:07:00"),
            InlineKeyboardButton("08:00", callback_data="wake:08:00"),
            InlineKeyboardButton("09:00", callback_data="wake:09:00"),
        ],
        [InlineKeyboardButton("⌨️ پیش‌فرض (07:00)", callback_data="wake:07:00")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⏰ ساعت بیداری امروز را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_WAKE_TIME


async def set_wake_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("wake:"):
        context.user_data['wake_time'] = ":".join(query.data.split(":")[1:])
    else:
        context.user_data['wake_time'] = "07:00"
    
    keyboard = [
        [
            InlineKeyboardButton("22:00", callback_data="sleep:22:00"),
            InlineKeyboardButton("23:00", callback_data="sleep:23:00"),
            InlineKeyboardButton("00:00", callback_data="sleep:00:00"),
        ],
        [InlineKeyboardButton("⌨️ پیش‌فرض (23:00)", callback_data="sleep:23:00")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🌙 ساعت خواب امشب را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_SLEEP_TIME


async def set_sleep_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("sleep:"):
        context.user_data['sleep_time'] = ":".join(query.data.split(":")[1:])
    else:
        context.user_data['sleep_time'] = "23:00"
    
    keyboard = [
        [
            InlineKeyboardButton("🤖 خودکار و هوشمند (پیشنهادی)", callback_data="mode:auto"),
            InlineKeyboardButton("✏️ دستی", callback_data="mode:manual")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("حالت زمان‌بندی را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_MODE


async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['mode'] = query.data.split(":")[1]
    context.user_data['tasks'] = []
    
    return await ask_task_name(update, context)


async def ask_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tasks_count = len(context.user_data.get('tasks', []))
    keyboard = []
    if tasks_count > 0:
        keyboard.append([InlineKeyboardButton("✅ اتمام برنامه‌ریزی و ثبت نهایی", callback_data="finish_planning")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    text = (
        f"📝 نام پارت/وظیفه شماره {tasks_count + 1} را ارسال کنید:\n"
        "(یا در صورت پایان، دکمه 'اتمام' زیر را بزنید یا کلمه 'اتمام' را بفرستید)"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
        
    return ASKING_TASK_NAME


async def receive_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if finish button was tapped or text is finish keyword
    if update.callback_query and update.callback_query.data == "finish_planning":
        return await finish_planning(update, context)
        
    user_text = (update.message.text or "").strip()
    if user_text.lower() in FINISH_KEYWORDS:
        return await finish_planning(update, context)
        
    context.user_data['current_task'] = {'task_name': user_text, 'emoji': ''}
    
    keyboard = [
        [
            InlineKeyboardButton("1:00", callback_data="dur:60"),
            InlineKeyboardButton("1:15", callback_data="dur:75"),
            InlineKeyboardButton("1:30", callback_data="dur:90"),
            InlineKeyboardButton("1:45", callback_data="dur:105"),
            InlineKeyboardButton("2:00", callback_data="dur:120"),
        ],
        [
            InlineKeyboardButton("30 دقیقه", callback_data="dur:30"),
            InlineKeyboardButton("2:30", callback_data="dur:150"),
            InlineKeyboardButton("3:00", callback_data="dur:180"),
            InlineKeyboardButton("سایر ⏱", callback_data="dur:custom"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"⏱ مدت زمان برای «{user_text}» را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_DURATION


async def receive_duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    val = query.data.split(":")[1]
    if val == "custom":
        await query.edit_message_text("مدت زمان دلخواه را بنویسید (مثال: ۴۵ دقیقه، ۱.۵ ساعت، ۹۰ دقیقه):")
        return ASKING_CUSTOM_DURATION
        
    context.user_data['current_task']['estimated_minutes'] = int(val)
    return await ask_anchor(update, context)


async def receive_custom_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    duration = duration_parser.parse_duration_to_minutes(update.message.text)
    if duration is None:
        await update.message.reply_text("فرمت زمان نامعتبر است. لطفاً مثلاً بنویسید: ۴۵ دقیقه یا ۱ ساعت و نیم:")
        return ASKING_CUSTOM_DURATION
        
    context.user_data['current_task']['estimated_minutes'] = duration
    return await ask_anchor(update, context)


async def ask_anchor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("⚓️ بله، زمان ثابت دارد (Anchor)", callback_data="anchor:yes"),
            InlineKeyboardButton("🔄 خیر، شناور است", callback_data="anchor:no")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "آیا این پارت ساعت مشخص و قفل‌شده‌ای در روز دارد؟"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
        
    return ASKING_ANCHOR


async def receive_anchor_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    val = query.data.split(":")[1]
    if val == "yes":
        await query.edit_message_text(
            "بازه زمانی مشخص را وارد کنید:\n"
            "نمونه‌های معتبر:\n"
            "▫️ 09:00 - 11:00\n"
            "▫️ 14 تا 16\n"
            "▫️ ۸ الی ۱۰"
        )
        return ASKING_ANCHOR_TIME
    
    context.user_data['current_task']['is_anchor'] = False
    context.user_data['current_task']['anchor_start'] = None
    context.user_data['current_task']['anchor_end'] = None
    return await ask_cognitive_load(update, context)


async def receive_anchor_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    parsed_range = duration_parser.parse_time_range(text)
    
    if parsed_range:
        start_t, end_t = parsed_range
        context.user_data['current_task']['is_anchor'] = True
        context.user_data['current_task']['anchor_start'] = start_t
        context.user_data['current_task']['anchor_end'] = end_t
    else:
        await update.message.reply_text(
            "فرمت نامعتبر است. لطفاً بازه را مشخص وارد کنید (مثال: 09:00 - 11:00 یا ۱۴ تا ۱۶):"
        )
        return ASKING_ANCHOR_TIME
        
    return await ask_cognitive_load(update, context)


async def ask_cognitive_load(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("🧠 سنگین (تمرکز بالا)", callback_data="cog:high"),
            InlineKeyboardButton("⚖️ متوسط", callback_data="cog:medium"),
            InlineKeyboardButton("😌 سبک / روتین", callback_data="cog:low"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "میزان بار شناختی و نیاز به تمرکز این کار چقدر است؟"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
        
    return ASKING_COGNITIVE_LOAD


async def receive_cognitive_load(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    val = query.data.split(":")[1]
    context.user_data['current_task']['cognitive_load'] = val
    
    context.user_data['tasks'].append(context.user_data['current_task'])
    del context.user_data['current_task']
    
    return await ask_task_name(update, context)


async def finish_planning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        
    user_id = update.effective_user.id
    mode = context.user_data.get('mode', 'auto')
    new_tasks = context.user_data.get('tasks', [])
    wake = context.user_data.get('wake_time', '07:00')
    sleep = context.user_data.get('sleep_time', '23:00')
    
    date_str = scheduler_engine.get_today_date_str(config.TIMEZONE)
    tz = config.TIMEZONE
    
    msg = update.message if update.message else update.callback_query.message
    
    try:
        # Load any recurring locked tasks from weekly schedule for today
        tz_obj = zoneinfo.ZoneInfo(config.TIMEZONE)
        now_dt = datetime.datetime.now(tz_obj)
        persian_weekday = (now_dt.weekday() + 2) % 7
        weekly_locked = await database.get_weekly_schedule(user_id, persian_weekday)
        
        all_tasks = []
        if weekly_locked:
            for wt in weekly_locked:
                all_tasks.append(dict(wt))
        all_tasks.extend(new_tasks)
        
        if not all_tasks:
            await msg.reply_text("هیچ وظیفه‌ای ثبت نشد. برنامه‌ریزی لغو گردید.")
            context.user_data.clear()
            return ConversationHandler.END
            
        if mode == 'auto':
            schedule = scheduler_engine.schedule_auto(all_tasks, wake, sleep, date_str, tz)
        else:
            schedule = scheduler_engine.schedule_manual(all_tasks)
            
        for task in schedule:
            await database.add_task(user_id, task, date_str)
            
        await database.update_user_settings(user_id, wake_time=wake, sleep_time=sleep)
        
        user_name = update.effective_user.first_name or "کاربر"
        poster = None
        try:
            poster = visual_engine.generate_daily_poster(schedule, user_name, date_str, wake, sleep, streak=0)
        except Exception as ve_err:
            logger.warning("Poster generation skipped: %s", ve_err)
            
        summary_lines = []
        for t in schedule:
            em = t.get('emoji') or '🔹'
            nm = t.get('task_name') or t.get('name') or 'وظیفه'
            st = t.get('scheduled_start', '--:--')
            en = t.get('scheduled_end', '--:--')
            summary_lines.append(f"{em} {nm}  ({st} - {en})")
            
        text_summary = f"🎉 *برنامه روزانه شما ثبت شد:*\n\n" + "\n".join(summary_lines)
        
        if poster:
            await msg.reply_photo(photo=poster, caption=text_summary, parse_mode="Markdown")
        else:
            await msg.reply_text(text_summary, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Error in finish_planning: {e}", exc_info=True)
        await msg.reply_text(f"⚠️ خطایی در نهایی‌سازی برنامه رخ داد: {e}\nلطفاً دوباره امتحان کنید.")
        
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_planning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ فرآیند برنامه‌ریزی لغو شد.")
    return ConversationHandler.END


async def bulk_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if text.startswith('/bulk '):
        text = text[6:]
        
    msg = await update.message.reply_text("🧠 در حال پردازش متن با هوش مصنوعی Gemini...")
    
    parsed_tasks = await nlp_engine.parse_tasks_from_text(text)
    if not parsed_tasks:
        await msg.edit_text("متاسفانه نتوانستم وظایفی از این متن استخراج کنم. لطفاً دوباره بنویسید.")
        return
        
    context.user_data['parsed_tasks'] = parsed_tasks
    
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید و زمان‌بندی", callback_data="confirm_bulk"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel_bulk")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    res = "\n".join([f"▫️ {t.get('emoji','')} {t.get('task_name', '')} ({t.get('estimated_minutes', 60)} دقیقه)" for t in parsed_tasks])
    await msg.edit_text(f"📋 *وظایف استخراج شده:*\n\n{res}\n\nآیا تایید می‌کنید؟", reply_markup=reply_markup, parse_mode="Markdown")


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("🎙 در حال گوش دادن و پردازش ویس با Gemini...")
    voice_file = await update.message.voice.get_file()
    audio_bytes = await voice_file.download_as_bytearray()
    
    parsed_tasks = await nlp_engine.parse_tasks_from_voice(bytes(audio_bytes))
    if not parsed_tasks:
        await msg.edit_text("متاسفانه صدایی واضح یا وظیفه‌ای تشخیص داده نشد.")
        return
        
    context.user_data['parsed_tasks'] = parsed_tasks
    
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید و زمان‌بندی", callback_data="confirm_bulk"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel_bulk")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    res = "\n".join([f"▫️ {t.get('emoji','')} {t.get('task_name', '')} ({t.get('estimated_minutes', 60)} دقیقه)" for t in parsed_tasks])
    await msg.edit_text(f"📋 *وظایف شنیده شده از ویس:*\n\n{res}\n\nآیا مایلید زمان‌بندی شوند؟", reply_markup=reply_markup, parse_mode="Markdown")


async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo intake: whiteboard, timetable, or todo note."""
    msg = await update.message.reply_text("👁 در حال خواندن تصویر و استخراج برنامه با بینایی هوش مصنوعی...")
    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    img_bytes = await photo_file.download_as_bytearray()
    
    # Try parsing as weekly schedule first (if it's a timetable grid)
    weekly_items = await nlp_engine.parse_weekly_schedule_from_image(bytes(img_bytes))
    if weekly_items and len(weekly_items) >= 2:
        user_id = update.effective_user.id
        added = 0
        for item in weekly_items:
            day = item.get("day_of_week", 0)
            await database.add_weekly_task(user_id, day, item)
            added += 1
            
        await msg.edit_text(
            f"🎓 تصویر برنامه هفتگی/کلاسی تشخیص داده شد!\n"
            f"✅ تعداد {added} کلاس و کار در برنامه هفتگی شما قفل شد.\n"
            f"برای مشاهده پوستر کل هفته دستور /weekly_view را بزنید."
        )
        return

    # Fallback to daily tasks list from photo
    daily_tasks = await nlp_engine.parse_tasks_from_image(bytes(img_bytes))
    if daily_tasks:
        context.user_data['parsed_tasks'] = daily_tasks
        keyboard = [
            [
                InlineKeyboardButton("✅ تایید و زمان‌بندی", callback_data="confirm_bulk"),
                InlineKeyboardButton("❌ لغو", callback_data="cancel_bulk")
            ]
        ]
        res = "\n".join([f"▫️ {t.get('emoji','')} {t.get('task_name', '')} ({t.get('estimated_minutes', 60)} دقیقه)" for t in daily_tasks])
        await msg.edit_text(f"📝 *وظایف خوانده شده از عکس:*\n\n{res}\n\nآیا ذخیره و زمان‌بندی شوند؟", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    await msg.edit_text("نتوانستم متن یا برنامه‌ای در این تصویر شناسایی کنم. لطفاً تصویر باکیفیت‌تری ارسال کنید.")


async def confirm_bulk_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    tasks = context.user_data.get('parsed_tasks', [])
    user_id = update.effective_user.id
    date_str = scheduler_engine.get_today_date_str(config.TIMEZONE)
    
    user = await database.get_user(user_id)
    wake = user.get("wake_time", "07:00") if user else "07:00"
    sleep = user.get("sleep_time", "23:00") if user else "23:00"
    
    scheduled = scheduler_engine.schedule_auto(tasks, wake, sleep, date_str, config.TIMEZONE)
    for t in scheduled:
        await database.add_task(user_id, t, date_str)
        
    await query.edit_message_text(f"✅ تعداد {len(scheduled)} وظیفه با موفقیت زمان‌بندی و ثبت شد!")
    context.user_data.clear()
