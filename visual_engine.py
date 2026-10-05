"""
Visual Engine — Aesthetic Pillow-based schedule poster generator.
Renders daily schedule posters (1080x1350) and weekly timetable grids (1920x1080)
with dark Nikola Tesla aesthetic and Persian RTL typography.
"""

import io
import logging
import pathlib
from typing import Union
from PIL import Image, ImageDraw, ImageFont

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_BIDI = True
except ImportError:
    HAS_BIDI = False

import config

logger = logging.getLogger(__name__)

# Constants
OVERLAY_OPACITY = 178       # ~70% dark overlay
POSTER_SIZE = (1080, 1350)  # 4:5 ratio
WEEKLY_SIZE = (1920, 1080)  # 16:9 ratio
ACCENT_COLOR = (255, 200, 80)    # golden yellow
TEXT_COLOR = (240, 240, 240)      # near-white
SECONDARY_COLOR = (180, 180, 180) # light gray
BG_FALLBACK_COLOR = (15, 15, 25)  # dark navy
HEADER_COLOR = (255, 200, 80)

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _to_persian(s: str) -> str:
    return str(s).translate(_PERSIAN_DIGITS)


def reshape_text(text: str) -> str:
    """Reshape and apply BiDi algorithm for proper Persian RTL display."""
    if not text:
        return ""
    if HAS_BIDI:
        try:
            reshaped = arabic_reshaper.reshape(str(text))
            return get_display(reshaped)
        except Exception as e:
            logger.warning("Text reshaping failed for '%s': %s", text, e)
            return str(text)
    return str(text)


def load_font(size: int) -> Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]:
    """Load Persian TTF font from FONT_PATH, fallback to default font."""
    font_path = getattr(config, "FONT_PATH", "assets/font.ttf")
    try:
        p = pathlib.Path(font_path)
        if p.exists() and p.stat().st_size > 1000:
            return ImageFont.truetype(str(p), size)
    except Exception as e:
        logger.warning("Could not load font from %s: %s", font_path, e)
    return ImageFont.load_default()


def load_background(size: tuple[int, int]) -> Image.Image:
    """Load and resize background image, fallback to dark solid color."""
    bg_path = getattr(config, "DAILY_POSTER_BG", "assets/background.jpg")
    try:
        p = pathlib.Path(bg_path)
        if p.exists() and p.stat().st_size > 1000:
            img = Image.open(str(p)).convert("RGBA")
            return img.resize(size, Image.Resampling.LANCZOS)
    except Exception as e:
        logger.warning("Could not load background from %s: %s", bg_path, e)
    return Image.new("RGBA", size, BG_FALLBACK_COLOR + (255,))


def apply_dark_overlay(img: Image.Image, opacity: int = OVERLAY_OPACITY) -> Image.Image:
    """Composite a dark semi-transparent overlay over the background."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, opacity))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def generate_daily_poster(
    tasks: list[dict],
    user_name: str,
    date_str: str,
    wake_time: str,
    sleep_time: str,
    streak: int = 0,
) -> bytes:
    """
    Generate a 1080x1350 dark aesthetic daily schedule poster.
    Returns PNG bytes.
    """
    img = load_background(POSTER_SIZE)
    img = apply_dark_overlay(img)
    draw = ImageDraw.Draw(img)

    title_font = load_font(60)
    subtitle_font = load_font(32)
    normal_font = load_font(26)
    small_font = load_font(20)

    # 1. Header — Date (left) and Title (right)
    draw.text((80, 50), reshape_text(_to_persian(date_str)), font=subtitle_font, fill=TEXT_COLOR)

    title_text = reshape_text("برنامه روزانه")
    try:
        t_w = draw.textlength(title_text, font=title_font)
    except Exception:
        t_w = 250
    draw.text((POSTER_SIZE[0] - 80 - t_w, 40), title_text, font=title_font, fill=HEADER_COLOR)

    user_text = reshape_text(user_name)
    try:
        u_w = draw.textlength(user_text, font=subtitle_font)
    except Exception:
        u_w = 150
    draw.text((POSTER_SIZE[0] - 80 - u_w, 115), user_text, font=subtitle_font, fill=SECONDARY_COLOR)

    if streak > 0:
        streak_text = reshape_text(f"🔥 {_to_persian(str(streak))} روز در تناوب !")
        draw.text((80, 105), streak_text, font=normal_font, fill=ACCENT_COLOR)

    # 2. Table Column Headers (y=190)
    y_offset = 190
    draw.line([(80, y_offset + 35), (POSTER_SIZE[0] - 80, y_offset + 35)], fill=SECONDARY_COLOR, width=2)

    col_time = reshape_text("TIME")
    col_task = reshape_text("وظیفه / پارت")
    col_dur = reshape_text("مدت")

    draw.text((80, y_offset), col_time, font=small_font, fill=SECONDARY_COLOR)
    draw.text((230, y_offset), col_task, font=small_font, fill=SECONDARY_COLOR)
    draw.text((POSTER_SIZE[0] - 180, y_offset), col_dur, font=small_font, fill=SECONDARY_COLOR)

    # 3. Task Rows (y=245)
    y_offset = 245
    total_minutes = 0
    row_height = 80

    for task in tasks:
        is_break = task.get("is_break", False)
        t_color = SECONDARY_COLOR if is_break else TEXT_COLOR

        # Scheduled Time
        start_time = task.get("scheduled_start") or "--:--"
        end_time = task.get("scheduled_end") or ""
        time_display = f"{start_time} - {end_time}" if end_time else start_time
        draw.text(
            (80, y_offset),
            _to_persian(time_display),
            font=normal_font,
            fill=SECONDARY_COLOR if is_break else ACCENT_COLOR,
        )

        # Emoji + Task Name
        emoji = task.get("emoji") or ("☕" if is_break else "🔹")
        raw_name = task.get("task_name") or task.get("name") or ("استراحت" if is_break else "وظیفه")
        task_label = reshape_text(f"{emoji} {raw_name}")
        draw.text((230, y_offset), task_label, font=normal_font, fill=t_color)

        # Duration
        dur = task.get("estimated_minutes") or task.get("duration") or task.get("duration_minutes") or 0
        if not is_break:
            total_minutes += dur
        dur_str = f"{_to_persian(str(dur))}د" if dur > 0 else ""
        draw.text((POSTER_SIZE[0] - 180, y_offset), reshape_text(dur_str), font=normal_font, fill=SECONDARY_COLOR)

        y_offset += row_height
        if y_offset > POSTER_SIZE[1] - 160:
            break

    # 4. Footer
    footer_y = POSTER_SIZE[1] - 110
    draw.line([(80, footer_y - 20), (POSTER_SIZE[0] - 80, footer_y - 20)], fill=SECONDARY_COLOR, width=2)

    total_h = total_minutes // 60
    total_m = total_minutes % 60
    footer_info = (
        f"بیداری: {_to_persian(wake_time)} | خواب: {_to_persian(sleep_time)} | "
        f"کار مفید: {_to_persian(str(total_h))} ساعت و {_to_persian(str(total_m))} دقیقه"
    )
    draw.text((80, footer_y), reshape_text(footer_info), font=subtitle_font, fill=ACCENT_COLOR)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def generate_weekly_grid(
    weekly_data: dict[int, list[dict]],
    user_name: str,
) -> bytes:
    """
    Generate a 1920x1080 weekly timetable grid poster.
    weekly_data maps day_of_week int (0=Saturday..6=Friday) to list of task dicts.
    Returns PNG bytes.
    """
    img = load_background(WEEKLY_SIZE)
    img = apply_dark_overlay(img, opacity=200)
    draw = ImageDraw.Draw(img)

    title_font = load_font(60)
    subtitle_font = load_font(30)
    normal_font = load_font(20)
    small_font = load_font(16)

    # Title
    title_text = reshape_text("برنامه هفتگی")
    try:
        tw = draw.textlength(title_text, font=title_font)
    except Exception:
        tw = 200
    draw.text(((WEEKLY_SIZE[0] - tw) // 2, 35), title_text, font=title_font, fill=ACCENT_COLOR)

    user_text = reshape_text(user_name)
    try:
        uw = draw.textlength(user_text, font=subtitle_font)
    except Exception:
        uw = 150
    draw.text(((WEEKLY_SIZE[0] - uw) // 2, 105), user_text, font=subtitle_font, fill=TEXT_COLOR)

    # 7 Days: Saturday=0 to Friday=6
    days = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
    margin_x = 40
    avail_w = WEEKLY_SIZE[0] - (2 * margin_x)
    col_w = avail_w // 7
    start_y = 175
    col_bottom = WEEKLY_SIZE[1] - 50

    for i, day_name in enumerate(days):
        x = margin_x + (i * col_w)

        # Alternating column tint
        col_bg = (30, 30, 48, 190) if i % 2 == 0 else (20, 20, 36, 190)
        draw.rectangle([x, start_y, x + col_w - 8, col_bottom], fill=col_bg)

        # Day Header
        reshaped_day = reshape_text(day_name)
        try:
            dw = draw.textlength(reshaped_day, font=subtitle_font)
        except Exception:
            dw = 60
        draw.text((x + (col_w - dw) // 2, start_y + 12), reshaped_day, font=subtitle_font, fill=ACCENT_COLOR)
        draw.line([(x + 10, start_y + 55), (x + col_w - 18, start_y + 55)], fill=SECONDARY_COLOR, width=1)

        # Day Tasks
        tasks = weekly_data.get(i, [])
        t_y = start_y + 68

        for task in tasks:
            if t_y > col_bottom - 60:
                draw.text((x + 12, t_y), reshape_text("..."), font=small_font, fill=SECONDARY_COLOR)
                break

            emoji = task.get("emoji") or "🔹"
            raw_name = task.get("task_name") or task.get("name") or "وظیفه"
            dur = task.get("estimated_minutes") or task.get("duration") or 0

            task_line = reshape_text(f"{emoji} {raw_name}")
            dur_line = reshape_text(f"{_to_persian(str(dur))}د") if dur else ""

            draw.text((x + 12, t_y), task_line, font=normal_font, fill=TEXT_COLOR)
            if dur_line:
                draw.text((x + 12, t_y + 26), dur_line, font=small_font, fill=SECONDARY_COLOR)

            t_y += 62

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
