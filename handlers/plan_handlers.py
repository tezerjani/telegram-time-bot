import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
import database
import config
import scheduler_engine
import nlp_engine
import duration_parser
import visual_engine
import message_cleaner

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

async def new_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("06:00", callback_data="wake:06:00"),
            InlineKeyboardButton("07:00", callback_data="wake:07:00"),
            InlineKeyboardButton("08:00", callback_data="wake:08:00"),
            InlineKeyboardButton("09:00", callback_data="wake:09:00"),
        ],
        [InlineKeyboardButton("⌨️ دلخواه", callback_data="wake:custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("ساعت بیداری را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_WAKE_TIME

async def set_wake_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("wake:"):
        context.user_data['wake_time'] = ":".join(query.data.split(":")[1:])
    
    keyboard = [
        [
            InlineKeyboardButton("22:00", callback_data="sleep:22:00"),
            InlineKeyboardButton("23:00", callback_data="sleep:23:00"),
            InlineKeyboardButton("00:00", callback_data="sleep:00:00"),
        ],
        [InlineKeyboardButton("⌨️ دلخواه", callback_data="sleep:custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("ساعت خواب را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_SLEEP_TIME

async def set_sleep_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("sleep:"):
        context.user_data['sleep_time'] = ":".join(query.data.split(":")[1:])
    
    keyboard = [
        [
            InlineKeyboardButton("🤖 خودکار (پیشنهادی)", callback_data="mode:auto"),
            InlineKeyboardButton("✏️ دستی", callback_data="mode:manual")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("حالت برنامه‌ریزی را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_MODE

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['mode'] = query.data.split(":")[1]
    context.user_data['tasks'] = []
    
    return await ask_task_name(update, context)

async def ask_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = []
    if len(context.user_data.get('tasks', [])) > 0:
        keyboard.append([InlineKeyboardButton("✅ اتمام برنامه‌ریزی", callback_data="finish_planning")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    text = "نام پارت/وظیفه را وارد کنید:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
        
    return ASKING_TASK_NAME

async def receive_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query and update.callback_query.data == "finish_planning":
        return await finish_planning(update, context)
        
    context.user_data['current_task'] = {'task_name': update.message.text, 'emoji': ''}
    
    keyboard = [
        [
            InlineKeyboardButton("1:00", callback_data="dur:60"),
            InlineKeyboardButton("1:15", callback_data="dur:75"),
            InlineKeyboardButton("1:30", callback_data="dur:90"),
            InlineKeyboardButton("1:45", callback_data="dur:105"),
            InlineKeyboardButton("2:00", callback_data="dur:120"),
        ],
        [
            InlineKeyboardButton("2:30", callback_data="dur:150"),
            InlineKeyboardButton("3:00", callback_data="dur:180"),
            InlineKeyboardButton("3:30", callback_data="dur:210"),
            InlineKeyboardButton("4:00", callback_data="dur:240"),
            InlineKeyboardButton("سایر ⏱", callback_data="dur:custom"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("مدت زمان را انتخاب کنید:", reply_markup=reply_markup)
    return ASKING_DURATION

async def receive_duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    val = query.data.split(":")[1]
    if val == "custom":
        await query.edit_message_text("مدت زمان دلخواه را وارد کنید (دقیقه):")
        return ASKING_CUSTOM_DURATION
        
    context.user_data['current_task']['estimated_minutes'] = int(val)
    return await ask_anchor(update, context)

async def receive_custom_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    duration = duration_parser.parse_duration_to_minutes(update.message.text)
    if duration is None:
        await update.message.reply_text("فرمت نامعتبر. لطفاً دوباره وارد کنید:")
        return ASKING_CUSTOM_DURATION
        
    context.user_data['current_task']['estimated_minutes'] = duration
    return await ask_anchor(update, context)

async def ask_anchor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("⚓ بله، زمان ثابت دارد", callback_data="anchor:yes"),
            InlineKeyboardButton("🔄 خیر، شناور است", callback_data="anchor:no")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "آیا این کار زمان ثابتی دارد؟"
    
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
        await query.edit_message_text("بازه زمانی را وارد کنید (مثال 09:00 - 11:00):")
        return ASKING_ANCHOR_TIME
    
    context.user_data['current_task']['is_anchor'] = False
    context.user_data['current_task']['anchor_start'] = None
    context.user_data['current_task']['anchor_end'] = None
    return await ask_cognitive_load(update, context)

async def receive_anchor_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    parts = text.replace(" ", "").split("-")
    if len(parts) == 2:
        context.user_data['current_task']['is_anchor'] = True
        context.user_data['current_task']['anchor_start'] = parts[0]
        context.user_data['current_task']['anchor_end'] = parts[1]
    else:
        await update.message.reply_text("فرمت نامعتبر است. بازه زمانی را دوباره وارد کنید:")
        return ASKING_ANCHOR_TIME
        
    return await ask_cognitive_load(update, context)

async def ask_cognitive_load(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("🧠 سنگین", callback_data="cog:high"),
            InlineKeyboardButton("⚖️ متوسط", callback_data="cog:medium"),
            InlineKeyboardButton("😌 سبک", callback_data="cog:low"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "بار شناختی این وظیفه چقدر است؟"
    
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
    tasks = context.user_data.get('tasks', [])
    wake = context.user_data.get('wake_time', '07:00')
    sleep = context.user_data.get('sleep_time', '23:00')
    
    date_str = scheduler_engine.get_today_date_str(config.TIMEZONE)
    tz = config.TIMEZONE
    
    if mode == 'auto':
        schedule = scheduler_engine.schedule_auto(tasks, wake, sleep, date_str, tz)
    else:
        schedule = scheduler_engine.schedule_manual(tasks)
        
    for task in schedule:
        await database.add_task(user_id, task, date_str)
        
    await database.update_user_settings(user_id, wake_time=wake, sleep_time=sleep)
    
    user_name = update.effective_user.first_name or "کاربر"
    poster = visual_engine.generate_daily_poster(schedule, user_name, date_str, wake, sleep, streak=0)
    msg = update.message if update.message else update.callback_query.message
    
    summary = "\n".join([f"🔹 {t.get('task_name', t.get('name', ''))}" for t in schedule])
    text_summary = f"برنامه شما آماده شد!\n\n{summary}"
    
    if poster:
        await msg.reply_photo(photo=poster, caption=text_summary)
    else:
        await msg.reply_text(text_summary)
        
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_planning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("برنامه‌ریزی لغو شد.")
    return ConversationHandler.END

async def bulk_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if text.startswith('/bulk '):
        text = text[6:]
        
    msg = await update.message.reply_text("در حال پردازش...")
    
    parsed_tasks = await nlp_engine.parse_tasks_from_text(text)
    context.user_data['parsed_tasks'] = parsed_tasks
    
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید و زمان‌بندی", callback_data="confirm_bulk"),
            InlineKeyboardButton("✏️ ویرایش", callback_data="edit_bulk")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    res = "\n".join([f"{t.get('task_name', t.get('name', ''))} - {t.get('estimated_minutes', t.get('duration', 0))}m" for t in parsed_tasks])
    await msg.edit_text(f"وظایف یافت شده:\n{res}", reply_markup=reply_markup)

async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("در حال پردازش صوت...")
    voice_file = await update.message.voice.get_file()
    audio_bytes = await voice_file.download_as_bytearray()
    
    parsed_tasks = await nlp_engine.parse_tasks_from_voice(bytes(audio_bytes))
    context.user_data['parsed_tasks'] = parsed_tasks
    
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید و زمان‌بندی", callback_data="confirm_bulk"),
            InlineKeyboardButton("✏️ ویرایش", callback_data="edit_bulk")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    res = "\n".join([f"{t.get('task_name', t.get('name', ''))} - {t.get('estimated_minutes', t.get('duration', 0))}m" for t in parsed_tasks])
    await msg.edit_text(f"وظایف یافت شده:\n{res}", reply_markup=reply_markup)

async def confirm_bulk_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    tasks = context.user_data.get('parsed_tasks', [])
    user_id = update.effective_user.id
    date_str = scheduler_engine.get_today_date_str(config.TIMEZONE)
    
    for t in tasks:
        await database.add_task(user_id, t, date_str)
        
    await query.edit_message_text("وظایف با موفقیت زمان‌بندی و ذخیره شدند!")
    context.user_data.clear()
