"""
Analytics Handlers — Weekly & monthly productivity analytics, badges, personal stats.
"""

import logging
import datetime
import zoneinfo

from telegram import Update
from telegram.ext import ContextTypes

import database
import nlp_engine
import config

logger = logging.getLogger(__name__)

# Persian digit mapping for display
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _to_persian(n: float, decimals: int = 0) -> str:
    fmt = f"{n:.{decimals}f}"
    return fmt.translate(_PERSIAN_DIGITS)


BADGE_LABELS = {
    "streak_10": "🔥 نشان استمرار ۱۰ روزه",
    "streak_20": "🏆 نشان تعهد ۲۰ روزه",
    "streak_30": "💎 نشان الماس ۳۰ روزه",
}


def build_ascii_bar_chart(journals: list[dict]) -> str:
    """Build a weekly ASCII progress bar chart from daily journal records."""
    if not journals:
        return ""

    # Group by ISO week
    weeks: dict[tuple, list] = {}
    for j in journals:
        date_str = j.get("journal_date", "")
        try:
            d = datetime.date.fromisoformat(date_str)
            key = (d.isocalendar()[0], d.isocalendar()[1])  # (year, week)
        except (ValueError, AttributeError):
            continue
        weeks.setdefault(key, []).append(j)

    chart = ""
    for idx, (_, week_journals) in enumerate(sorted(weeks.items()), start=1):
        avg = sum(j.get("productivity_score", 0) for j in week_journals) / len(week_journals)
        filled = int(avg / 10)
        empty = 10 - filled
        bar = "▰" * filled + "▱" * empty
        chart += f"هفته {_to_persian(idx)}: {bar} {_to_persian(avg)}%\n"

    return chart


async def weekly_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats_week — Last 7 days productivity report."""
    user_id = update.effective_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    start_date = today - datetime.timedelta(days=7)

    journals = await database.get_journals_range(
        user_id, str(start_date), str(today)
    )

    if not journals:
        await update.message.reply_text(
            "📊 هنوز اطلاعاتی برای آمار هفتگی ثبت نشده.\n"
            "بعد از اتمام بررسی شبانه (/review) آمار ثبت می‌شود."
        )
        return

    avg_score = sum(j.get("productivity_score", 0) for j in journals) / len(journals)
    total_minutes = sum(j.get("completed_minutes", 0) for j in journals)
    total_hours = total_minutes / 60

    best_day = max(journals, key=lambda x: x.get("productivity_score", 0))
    worst_day = min(journals, key=lambda x: x.get("productivity_score", 0))

    # Trend: compare second-half avg vs first-half avg
    mid = len(journals) // 2
    if mid > 0:
        first_avg = sum(j.get("productivity_score", 0) for j in journals[:mid]) / mid
        second_avg = sum(j.get("productivity_score", 0) for j in journals[mid:]) / max(1, len(journals) - mid)
        trend = "📈 رو به بهبود" if second_avg >= first_avg else "📉 کاهشی"
    else:
        trend = "—"

    summary_text = (
        f"📊 *آمار هفتگی شما*\n\n"
        f"🎯 میانگین بهره‌وری: {_to_persian(avg_score, 1)}%\n"
        f"⏱ مجموع ساعات مفید: {_to_persian(total_hours, 1)} ساعت\n"
        f"🥇 بهترین روز: {best_day.get('journal_date','—')} ({_to_persian(best_day.get('productivity_score',0))}%)\n"
        f"🥉 ضعیف‌ترین روز: {worst_day.get('journal_date','—')} ({_to_persian(worst_day.get('productivity_score',0))}%)\n"
        f"📉 روند: {trend}\n"
    )

    try:
        insight = await nlp_engine.generate_weekly_summary_insight(journals)
        summary_text += f"\n🤖 *تحلیل هوش مصنوعی:*\n{insight}"
    except Exception as e:
        logger.warning("Could not generate weekly insight: %s", e)

    await update.message.reply_text(summary_text, parse_mode="Markdown")


async def monthly_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats_month — Last 30 days productivity report with ASCII bar chart."""
    user_id = update.effective_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    start_date = today - datetime.timedelta(days=30)

    journals = await database.get_journals_range(
        user_id, str(start_date), str(today)
    )

    if not journals:
        await update.message.reply_text(
            "📊 هنوز اطلاعاتی برای آمار ماهانه ثبت نشده.\n"
            "بعد از اتمام بررسی شبانه (/review) آمار ثبت می‌شود."
        )
        return

    avg_score = sum(j.get("productivity_score", 0) for j in journals) / len(journals)
    total_minutes = sum(j.get("completed_minutes", 0) for j in journals)
    total_hours = total_minutes / 60
    days_tracked = len(journals)
    good_days = sum(1 for j in journals if j.get("productivity_score", 0) >= 70)

    chart = build_ascii_bar_chart(journals)

    summary_text = (
        f"📅 *آمار ماهانه شما*\n\n"
        f"🗓 روزهای ثبت‌شده: {_to_persian(days_tracked)} روز\n"
        f"🎯 میانگین بهره‌وری: {_to_persian(avg_score, 1)}%\n"
        f"⏱ مجموع ساعات مفید: {_to_persian(total_hours, 1)} ساعت\n"
        f"✅ روزهای موفق (≥۷۰%): {_to_persian(good_days)} روز\n\n"
        f"📊 *نمودار هفتگی:*\n`{chart}`"
    )

    await update.message.reply_text(summary_text, parse_mode="Markdown")


async def badges_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/badges — Show all earned gamification badges."""
    user_id = update.effective_user.id
    badges = await database.get_badges(user_id)

    if not badges:
        await update.message.reply_text(
            "🏅 هنوز هیچ نشانی دریافت نکرده‌اید.\n\n"
            "برای دریافت نشان، بهره‌وری روزانه‌تان را بالای ۷۰٪ نگه دارید:\n"
            "🔥 ۱۰ روز پشت‌سرهم\n"
            "🏆 ۲۰ روز پشت‌سرهم\n"
            "💎 ۳۰ روز پشت‌سرهم\n\n"
            "به تلاش ادامه دهید! 💪"
        )
        return

    text = "🏅 *نشان‌های دریافتی شما:*\n\n"
    for b in badges:
        badge_type = b.get("badge_type", "")
        label = BADGE_LABELS.get(badge_type, f"🎖 {badge_type}")
        awarded = b.get("awarded_at", "")[:10] if b.get("awarded_at") else "—"
        text += f"{label}\n📅 تاریخ دریافت: {awarded}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mystats — Personal statistics dashboard."""
    user_id = update.effective_user.id
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    today = datetime.datetime.now(tz).date()

    # Fetch user record
    user = await database.get_user(user_id)
    if not user:
        await update.message.reply_text("کاربر یافت نشد.")
        return

    current_streak = user.get("streak_days", 0)
    total_productive_minutes = user.get("total_productive_minutes", 0)
    total_hours = total_productive_minutes / 60

    # Days tracked = count distinct journal dates (last 365 days)
    start_date = today - datetime.timedelta(days=365)
    journals = await database.get_journals_range(user_id, str(start_date), str(today))
    days_tracked = len(journals)

    # Best streak: compute from journals
    best_streak = 0
    run = 0
    prev_date = None
    for j in sorted(journals, key=lambda x: x.get("journal_date", "")):
        score = j.get("productivity_score", 0)
        jdate_str = j.get("journal_date", "")
        try:
            jdate = datetime.date.fromisoformat(jdate_str)
        except (ValueError, AttributeError):
            continue
        if score >= 70:
            if prev_date and (jdate - prev_date).days == 1:
                run += 1
            else:
                run = 1
            best_streak = max(best_streak, run)
        else:
            run = 0
        prev_date = jdate

    badges = await database.get_badges(user_id)
    badge_count = len(badges)

    # Build badge display
    badge_lines = ""
    if badges:
        for b in badges:
            label = BADGE_LABELS.get(b.get("badge_type", ""), "🎖")
            badge_lines += f"  {label}\n"
    else:
        badge_lines = "  هنوز نشانی ندارید\n"

    text = (
        f"👤 *پروفایل آماری من*\n\n"
        f"📅 روزهای ثبت‌شده: {_to_persian(days_tracked)} روز\n"
        f"⏱ کل ساعات مفید: {_to_persian(total_hours, 1)} ساعت\n"
        f"🔥 استریک فعلی: {_to_persian(current_streak)} روز\n"
        f"🏆 بهترین استریک: {_to_persian(best_streak)} روز\n"
        f"🏅 تعداد نشان‌ها: {_to_persian(badge_count)} عدد\n\n"
        f"*نشان‌های کسب‌شده:*\n{badge_lines}"
    )

    await update.message.reply_text(text, parse_mode="Markdown")
