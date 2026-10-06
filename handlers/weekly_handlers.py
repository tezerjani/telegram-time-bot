import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import datetime
import zoneinfo

import database
import config
import scheduler_engine
import nlp_engine
import duration_parser
import visual_engine
from handlers.auth_handlers import check_authorization

logger = logging.getLogger(__name__)

DAY_NAMES = {0: 'شنبه', 1: 'یکشنبه', 2: 'دوشنبه', 3: 'سه‌شنبه', 4: 'چهارشنبه', 5: 'پنجشنبه', 6: 'جمعه'}

SELECTING_DAY = 1
ADDING_WEEKLY_TASK_NAME = 2
ADDING_WEEKLY_DURATION = 3
ADDING_WEEKLY_ANCHOR = 4
CLONING_SELECT_TARGET = 5

async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_authorization(update, context):
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    
    keyboard = []
    for day_idx, day_name in DAY_NAMES.items():
        tasks = await database.get_weekly_schedule(user_id, day_idx)
        task_count = len(tasks)
        text = f"{day_name} ({task_count} وظیفه)"
        keyboard.append([InlineKeyboardButton(text, callback_data=f'week_day:{day_idx}')])
    
    keyboard.append([InlineKeyboardButton("🗑 پاک‌سازی کل برنامه هفتگی (ریست ترم)", callback_data='clear_all_weekly')])
    keyboard.append([InlineKeyboardButton("بازگشت", callback_data='cancel_weekly')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📅 *مدیریت برنامه هفتگی و زمان‌های قفل‌شده:*\n\n"
        "▫️ روز مورد نظر را برای تنظیم یا مشاهده انتخاب کنید.\n"
        "▫️ یا می‌توانید مستقیماً **عکس برنامه درسی/کاری** خود را بفرستید تا خودکار ثبت شود!\n"
        "▫️ همچنین می‌توانید با دستور `/set_term` متن برنامه خود را یکجا بنویسید.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return SELECTING_DAY

async def select_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == 'cancel_weekly':
        await query.edit_message_text("عملیات لغو شد.")
        return ConversationHandler.END
        
    day_idx = int(data.split(':')[1])
    context.user_data['selected_day'] = day_idx
    
    user_id = update.effective_user.id
    tasks = await database.get_weekly_schedule(user_id, day_idx)
    
    text = f"برنامه روز {DAY_NAMES[day_idx]}:\n\n"
    if not tasks:
        text += "وظیفه‌ای ثبت نشده است."
    else:
        for t in tasks:
            text += f"▪️ {t.get('task_name', 'بدون نام')} - {t.get('estimated_minutes', 0)} دقیقه"
            if t.get('is_anchor'):
                text += " ⚓️"
            text += "\n"
            
    keyboard = [
        [InlineKeyboardButton("➕ افزودن وظیفه", callback_data='add_weekly_task')],
        [InlineKeyboardButton("📋 مشاهده برنامه", callback_data='view_schedule')],
        [InlineKeyboardButton("📸 پوستر هفتگی", callback_data='weekly_poster')],
        [InlineKeyboardButton("🗑 پاک کردن روز", callback_data=f'clear_week_day:{day_idx}')],
        [InlineKeyboardButton("↩️ بازگشت", callback_data='weekly_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)
    return SELECTING_DAY

async def add_weekly_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("نام وظیفه را وارد کنید:")
    return ADDING_WEEKLY_TASK_NAME

async def receive_weekly_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_task_name'] = update.message.text.strip()
    
    keyboard = [
        ['15 دقیقه', '30 دقیقه', '45 دقیقه'],
        ['1 ساعت', '1.5 ساعت', '2 ساعت']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("مدت زمان انجام این وظیفه چقدر است؟ (می‌توانید دستی هم وارد کنید)", reply_markup=reply_markup)
    return ADDING_WEEKLY_DURATION

async def receive_weekly_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    duration_text = update.message.text
    duration_minutes = duration_parser.parse_duration_to_minutes(duration_text)
    
    if duration_minutes is None:
        await update.message.reply_text("فرمت زمان نامعتبر است. لطفاً مجددا وارد کنید (مثلا: 30 دقیقه، 1 ساعت):")
        return ADDING_WEEKLY_DURATION
        
    context.user_data['temp_task_duration'] = duration_minutes
    
    keyboard = [
        [InlineKeyboardButton("بله (Anchor)", callback_data='anchor_yes')],
        [InlineKeyboardButton("خیر (شناور)", callback_data='anchor_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("آیا این وظیفه زمان ثابت و مشخصی در روز دارد (Anchor)؟", reply_markup=reply_markup)
    return ADDING_WEEKLY_ANCHOR

async def receive_weekly_anchor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    is_anchor = (query.data == 'anchor_yes')
    user_id = update.effective_user.id
    day_idx = context.user_data['selected_day']
    name = context.user_data['temp_task_name']
    duration = context.user_data['temp_task_duration']
    
    task_data_dict = {
        'task_name': name,
        'emoji': '',
        'estimated_minutes': duration,
        'is_anchor': is_anchor,
        'anchor_start': None,
        'anchor_end': None,
        'cognitive_load': 'medium'
    }
    
    await database.add_weekly_task(user_id, day_idx, task_data_dict)
    
    await query.edit_message_text(f"وظیفه '{name}' با موفقیت به {DAY_NAMES[day_idx]} اضافه شد.")
    
    for k in ['temp_task_name', 'temp_task_duration']:
        context.user_data.pop(k, None)
        
    return ConversationHandler.END

async def view_weekly_grid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        if not await check_authorization(update, context):
            return
            
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "کاربر"
    full_schedule = await database.get_full_weekly_schedule(user_id)
    user = await database.get_user(user_id)
    wake = user.get("wake_time", "07:00") if user else "07:00"
    sleep = user.get("sleep_time", "23:00") if user else "23:00"
    
    weekly_data = {i: [] for i in range(7)}
    for day_idx in range(7):
        day_tasks = [t for t in full_schedule if t.get('day_of_week') == day_idx]
        scheduled_day = scheduler_engine.schedule_auto(day_tasks, wake, sleep, '2023-01-01', config.TIMEZONE)
        weekly_data[day_idx] = scheduled_day
        
    summary_text = "برنامه کل هفته شما:\n"
    for day_idx in range(7):
        tasks = weekly_data[day_idx]
        summary_text += f"{DAY_NAMES[day_idx]}: {len(tasks)} وظیفه\n"
        
    image_bytes = visual_engine.generate_weekly_grid(weekly_data, user_name)
    
    if update.callback_query:
        await update.callback_query.answer()
        await context.bot.send_photo(chat_id=user_id, photo=image_bytes, caption=summary_text)
    else:
        await update.message.reply_photo(photo=image_bytes, caption=summary_text)

async def clone_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_authorization(update, context):
        return ConversationHandler.END
        
    keyboard = []
    for day_idx, day_name in DAY_NAMES.items():
        keyboard.append([InlineKeyboardButton(day_name, callback_data=f'clone_src:{day_idx}')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("روزی که می‌خواهید برنامه آن را کپی کنید (مبدأ) انتخاب کنید:", reply_markup=reply_markup)
    return CLONING_SELECT_TARGET

async def execute_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('clone_src:'):
        src_day = int(query.data.split(':')[1])
        context.user_data['clone_src_day'] = src_day
        context.user_data['clone_targets'] = set()
        
        keyboard = []
        for day_idx, day_name in DAY_NAMES.items():
            if day_idx != src_day:
                keyboard.append([InlineKeyboardButton(f"⬜️ {day_name}", callback_data=f'clone_target:{day_idx}')])
        keyboard.append([InlineKeyboardButton("✅ کپی کردن", callback_data='execute_clone')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"روز مبدأ: {DAY_NAMES[src_day]}\n\nروزهای مقصد را انتخاب کنید:", reply_markup=reply_markup)
        
    elif query.data.startswith('clone_target:'):
        target_day = int(query.data.split(':')[1])
        targets = context.user_data.get('clone_targets', set())
        
        if target_day in targets:
            targets.remove(target_day)
        else:
            targets.add(target_day)
            
        src_day = context.user_data.get('clone_src_day')
        
        keyboard = []
        for day_idx, day_name in DAY_NAMES.items():
            if day_idx != src_day:
                prefix = "✅" if day_idx in targets else "⬜️"
                keyboard.append([InlineKeyboardButton(f"{prefix} {day_name}", callback_data=f'clone_target:{day_idx}')])
        keyboard.append([InlineKeyboardButton("✅ کپی کردن", callback_data='execute_clone')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        
    elif query.data == 'execute_clone':
        user_id = update.effective_user.id
        src_day = context.user_data.get('clone_src_day')
        targets = context.user_data.get('clone_targets', set())
        
        if not targets:
            await query.edit_message_text("هیچ روز مقصدی انتخاب نشد. عملیات لغو شد.")
            return ConversationHandler.END
            
        await database.clone_day_to_days(user_id, src_day, list(targets))
        
        target_names = [DAY_NAMES[d] for d in targets]
        await query.edit_message_text(f"برنامه {DAY_NAMES[src_day]} با موفقیت به روزهای {'، '.join(target_names)} کپی شد.")
        return ConversationHandler.END

async def clear_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    day_idx = int(query.data.split(':')[1])
    user_id = update.effective_user.id
    
    await database.clear_weekly_day(user_id, day_idx)
    await query.edit_message_text(f"برنامه روز {DAY_NAMES[day_idx]} با موفقیت پاک شد.")

async def apply_weekly_to_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update, context):
        return
        
    user_id = update.effective_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    now = datetime.datetime.now(tz)
    weekday = (now.weekday() + 2) % 7
    
    today_date_str = scheduler_engine.get_today_date_str(config.TIMEZONE)
    
    weekly_tasks = await database.get_weekly_schedule(user_id, weekday)
    
    if not weekly_tasks:
        await update.message.reply_text(f"شما در روز {DAY_NAMES[weekday]} هیچ وظیفه‌ای در برنامه هفتگی ندارید.")
        return
        
    user = await database.get_user(user_id)
    wake_time = user.get("wake_time", "07:00") if user else "07:00"
    sleep_time = user.get("sleep_time", "23:00") if user else "23:00"
    scheduled_tasks = scheduler_engine.schedule_auto(
        weekly_tasks, wake_time, sleep_time, today_date_str, config.TIMEZONE
    )
    
    for task in scheduled_tasks:
        await database.add_task(user_id, task, today_date_str)
        
    await update.message.reply_text(f"وظایف هفتگی مربوط به {DAY_NAMES[weekday]} به برنامه امروز اضافه شد و برنامه‌ریزی خودکار اعمال گردید.")


async def clear_all_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    await database.clear_all_weekly_schedule(user_id)
    await query.edit_message_text("🗑 برنامه کل هفته و ترم با موفقیت پاک‌سازی شد. اکنون می‌توانید برنامه جدید وارد کنید.")


async def set_term_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Natural language weekly plan input e.g. /set_term شنبه‌ها ۸ تا ۱۲ دانشگاه..."""
    text = update.message.text
    if text.startswith('/set_term'):
        text = text[9:].strip()
        
    if not text:
        await update.message.reply_text(
            "لطفاً برنامه هفتگی خود را جلوی دستور بنویسید:\n"
            "مثال:\n"
            "`/set_term شنبه‌ها ۸ تا ۱۲ کلاس ریاضی، دوشنبه‌ها ۹ تا ۱۷ سر کار`",
            parse_mode="Markdown"
        )
        return
        
    msg = await update.message.reply_text("🧠 در حال استخراج و قفل کردن زمان‌های ثابت هفتگی با هوش مصنوعی...")
    weekly_items = await nlp_engine.parse_weekly_schedule_from_text(text)
    
    if not weekly_items:
        await msg.edit_text("نتوانستم روزها و ساعت‌ها را به درستی تشخیص دهم. لطفاً روزها و ساعت‌ها را مشخص‌تر بنویسید.")
        return
        
    user_id = update.effective_user.id
    for item in weekly_items:
        day = item.get("day_of_week", 0)
        await database.add_weekly_task(user_id, day, item)
        
    lines = [f"▫️ {DAY_NAMES.get(i.get('day_of_week', 0), '')}: {i.get('emoji','')} {i.get('task_name')} ({i.get('anchor_start')} تا {i.get('anchor_end')})" for i in weekly_items]
    await msg.edit_text(
        f"✅ برنامه ثابت هفتگی شما با موفقیت قفل شد:\n\n" + "\n".join(lines) + "\n\n"
        f"از این پس هر زمان برنامه‌ریزی روزانه انجام دهید، این زمان‌ها به عنوان زمان‌های ثابت حفظ می‌شوند."
    )

