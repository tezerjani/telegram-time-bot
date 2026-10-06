import asyncio
import logging
import os
import signal
import aiohttp.web
from telegram.ext import (
    Application, ApplicationBuilder, JobQueue, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ConversationHandler
)
from telegram import Bot

import config
import database
import message_cleaner
import progress_tracker

from handlers import (
    auth_handlers,
    plan_handlers,
    weekly_handlers,
    review_handlers,
    analytics_handlers,
    live_deck_handlers
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def health_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    return aiohttp.web.Response(text='OK', status=200)

async def start_health_server(port: int) -> aiohttp.web.AppRunner:
    app = aiohttp.web.Application()
    app.router.add_get('/', health_handler)
    app.router.add_get('/healthz', health_handler)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    return runner

async def build_application() -> Application:
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Auth handlers
    app.add_handler(CommandHandler('start', auth_handlers.start_command))
    app.add_handler(CallbackQueryHandler(auth_handlers.approve_user_callback, pattern='^approve_user:'))
    app.add_handler(CallbackQueryHandler(auth_handlers.reject_user_callback, pattern='^reject_user:'))
    app.add_handler(CallbackQueryHandler(auth_handlers.revoke_user_callback, pattern='^revoke_user:'))
    app.add_handler(CallbackQueryHandler(auth_handlers.resend_request_callback, pattern='^resend_request:'))
    app.add_handler(CommandHandler('admin', auth_handlers.admin_command))
    app.add_handler(CommandHandler('broadcast', auth_handlers.broadcast_command))

    # Plan ConversationHandler
    plan_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('plan', plan_handlers.new_plan_command),
            CommandHandler('bulk', plan_handlers.bulk_text_command),
        ],
        states={
            plan_handlers.ASKING_WAKE_TIME: [CallbackQueryHandler(plan_handlers.set_wake_time)],
            plan_handlers.ASKING_SLEEP_TIME: [CallbackQueryHandler(plan_handlers.set_sleep_time)],
            plan_handlers.ASKING_MODE: [CallbackQueryHandler(plan_handlers.set_mode)],
            plan_handlers.ASKING_TASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, plan_handlers.receive_task_name),
                CallbackQueryHandler(plan_handlers.finish_planning, pattern='^finish_planning$'),
            ],
            plan_handlers.ASKING_DURATION: [CallbackQueryHandler(plan_handlers.receive_duration_selection)],
            plan_handlers.ASKING_CUSTOM_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_handlers.receive_custom_duration)],
            plan_handlers.ASKING_ANCHOR: [CallbackQueryHandler(plan_handlers.receive_anchor_choice)],
            plan_handlers.ASKING_ANCHOR_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_handlers.receive_anchor_time)],
            plan_handlers.ASKING_COGNITIVE_LOAD: [CallbackQueryHandler(plan_handlers.receive_cognitive_load)],
            plan_handlers.CONFIRMING_PLAN: [CallbackQueryHandler(plan_handlers.finish_planning, pattern='^finish_planning$')],
        },
        fallbacks=[CommandHandler('cancel', plan_handlers.cancel_planning)],
        per_message=False,
        allow_reentry=True,
    )
    app.add_handler(plan_conv_handler)

    # Weekly ConversationHandler
    weekly_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('weekly', weekly_handlers.weekly_command)],
        states={
            weekly_handlers.SELECTING_DAY: [
                CallbackQueryHandler(weekly_handlers.select_day, pattern='^week_day:'),
            ],
            weekly_handlers.ADDING_WEEKLY_TASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_handlers.receive_weekly_task_name),
            ],
            weekly_handlers.ADDING_WEEKLY_DURATION: [
                CallbackQueryHandler(weekly_handlers.receive_weekly_duration, pattern='^wdur:'),
            ],
            weekly_handlers.ADDING_WEEKLY_ANCHOR: [
                CallbackQueryHandler(weekly_handlers.receive_weekly_anchor, pattern='^wanchor:'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_handlers.receive_weekly_anchor),
            ],
            weekly_handlers.CLONING_SELECT_TARGET: [
                CallbackQueryHandler(weekly_handlers.execute_clone, pattern='^execute_clone$'),
                CallbackQueryHandler(weekly_handlers.clone_day_command, pattern='^clone_target:'),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', plan_handlers.cancel_planning),
            CallbackQueryHandler(plan_handlers.cancel_planning, pattern='^cancel$'),
        ],
        per_message=False,
        allow_reentry=True,
    )
    app.add_handler(weekly_conv_handler)

    # Weekly clone command (separate entry)
    app.add_handler(CommandHandler('clone_day', weekly_handlers.clone_day_command))

    # Review ConversationHandler
    review_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('review', review_handlers.nightly_review_command)],
        states={
            review_handlers.CHECKLIST_STATE: [
                CallbackQueryHandler(review_handlers.mark_task_done, pattern='^mark_done:'),
                CallbackQueryHandler(review_handlers.mark_task_missed, pattern='^mark_missed:'),
                CallbackQueryHandler(review_handlers.complete_review, pattern='^complete_review$'),
            ],
            review_handlers.JOURNAL_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, review_handlers.receive_journal),
            ],
            review_handlers.ROLLOVER_CONFIRM: [
                CallbackQueryHandler(review_handlers.confirm_rollover, pattern='^rollover:'),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', plan_handlers.cancel_planning),
        ],
        per_message=False,
        allow_reentry=True,
    )
    app.add_handler(review_conv_handler)

    # Weekly callback handlers (outside conversation)
    app.add_handler(CallbackQueryHandler(weekly_handlers.clear_day_callback, pattern='^clear_week_day:'))
    app.add_handler(CallbackQueryHandler(weekly_handlers.view_weekly_grid, pattern='^view_weekly_grid$'))

    # Live deck handlers
    app.add_handler(CommandHandler('deck', live_deck_handlers.send_live_deck))
    app.add_handler(CallbackQueryHandler(live_deck_handlers.extend_task_callback, pattern='^extend:'))
    app.add_handler(CallbackQueryHandler(live_deck_handlers.emergency_pause_callback, pattern='^emergency_pause$'))
    app.add_handler(CallbackQueryHandler(live_deck_handlers.confirm_pause_callback, pattern='^pause_for:'))
    app.add_handler(CallbackQueryHandler(live_deck_handlers.skip_task_callback, pattern='^skip_task$'))
    app.add_handler(CallbackQueryHandler(live_deck_handlers.refresh_progress_callback, pattern='^refresh_progress:'))
    app.add_handler(CallbackQueryHandler(live_deck_handlers.show_overview_callback, pattern='^show_overview$'))

    # Analytics handlers
    app.add_handler(CommandHandler('stats_week', analytics_handlers.weekly_stats_command))
    app.add_handler(CommandHandler('stats_month', analytics_handlers.monthly_stats_command))
    app.add_handler(CommandHandler('badges', analytics_handlers.badges_command))
    app.add_handler(CommandHandler('mystats', analytics_handlers.my_stats_command))

    # Voice & Photo message handlers
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, plan_handlers.voice_message_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, plan_handlers.photo_message_handler))

    # Weekly commands & callbacks
    app.add_handler(CommandHandler('weekly_view', weekly_handlers.view_weekly_grid))
    app.add_handler(CommandHandler('apply_weekly', weekly_handlers.apply_weekly_to_today))
    app.add_handler(CommandHandler('set_term', weekly_handlers.set_term_text_command))
    app.add_handler(CallbackQueryHandler(weekly_handlers.clear_all_weekly_callback, pattern='^clear_all_weekly$'))
    app.add_handler(CallbackQueryHandler(plan_handlers.confirm_bulk_plan, pattern='^confirm_bulk$'))
    app.add_handler(CallbackQueryHandler(plan_handlers.cancel_planning, pattern='^cancel_bulk$'))

    # Register JobQueue jobs
    if app.job_queue:
        app.job_queue.run_repeating(message_cleaner.cleanup_job, interval=60, first=10)
        app.job_queue.run_repeating(review_handlers.nightly_review_job, interval=60, first=30)

    return app

async def main() -> None:
    config.validate_config()
    await database.init_db()
    
    # Start health server
    runner = await start_health_server(config.PORT)
    
    # Build and start bot
    app = await build_application()

    # Instantiate the progress tracker and share it via bot_data
    tracker = progress_tracker.TaskProgressTracker(app.bot)
    app.bot_data["progress_tracker"] = tracker
    
    async with app:
        await app.start()
        
        # Set bot commands for the UI menu
        from telegram import BotCommand
        commands = [
            BotCommand("start", "شروع و مشاهده دستورات"),
            BotCommand("plan", "برنامه‌ریزی هوشمند روزانه"),
            BotCommand("deck", "دک کنترل زنده (وضعیت فعلی)"),
            BotCommand("review", "بررسی و یادداشت شبانه"),
            BotCommand("weekly", "مدیریت برنامه هفتگی"),
            BotCommand("weekly_view", "مشاهده تصویر برنامه هفتگی"),
            BotCommand("mystats", "آمار کلی من"),
            BotCommand("badges", "افتخارات من"),
            BotCommand("stats_week", "گزارش هفتگی"),
            BotCommand("stats_month", "گزارش ماهانه"),
            BotCommand("cancel", "لغو عملیات فعلی")
        ]
        try:
            await app.bot.set_my_commands(commands)
        except Exception as e:
            logger.warning(f"Failed to set bot commands: {e}")

        await app.updater.start_polling(drop_pending_updates=True)
        logger.info('Bot started successfully')
        
        # Keep running until interrupted
        stop_event = asyncio.Event()
        
        def handle_signal():
            stop_event.set()
        
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                pass  # Windows doesn't support add_signal_handler
        
        try:
            await stop_event.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        
        await app.updater.stop()
        await app.stop()
    
    await runner.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted")
