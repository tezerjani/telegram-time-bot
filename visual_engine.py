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
OVERLAY_OPACITY = 140       # ~55% dark overlay (lighter to show the beautiful background)
POSTER_SIZE = (1080, 1350)  # 4:5 ratio
WEEKLY_SIZE = (1920, 1080)  # 16:9 ratio
ACCENT_COLOR = (255, 170, 90)     # warm copper/gold
TEXT_COLOR = (245, 240, 235)      # warm near-white
SECONDARY_COLOR = (190, 175, 160) # warm light gray
BG_FALLBACK_COLOR = (25, 15, 10)  # dark brown/copper fallback
HEADER_COLOR = (255, 170, 90)     # warm copper/gold
GRID_LINE_COLOR = (255, 170, 90, 80) # Semi-transparent copper for grid lines
CARD_BG_COLOR = (20, 10, 5, 180)  # warm dark overlay for cards

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
    img = apply_dark_overlay(img, opacity=0)
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
    draw.rectangle([60, y_offset - 10, POSTER_SIZE[0] - 60, y_offset + 45], fill=None, outline=ACCENT_COLOR, width=2)

    col_time = reshape_text("TIME / ساعت")
    col_task = reshape_text("TASK / پارت / وظیفه")
    col_dur = reshape_text("DUR / مدت")

    draw.text((80, y_offset), col_time, font=small_font, fill=ACCENT_COLOR)
    draw.text((320, y_offset), col_task, font=small_font, fill=ACCENT_COLOR)
    draw.text((POSTER_SIZE[0] - 180, y_offset), col_dur, font=small_font, fill=ACCENT_COLOR)

    # 3. Task Rows (y=245)
    y_offset = 245
    total_minutes = 0
    row_height = 85

    for i, task in enumerate(tasks):
        is_break = task.get("is_break", False)
        t_color = SECONDARY_COLOR if is_break else TEXT_COLOR

        # No background fill for rows
        draw.rectangle([60, y_offset - 5, POSTER_SIZE[0] - 60, y_offset + row_height - 5], fill=None)
        
        # Bottom border for row
        draw.line([(60, y_offset + row_height - 5), (POSTER_SIZE[0] - 60, y_offset + row_height - 5)], fill=GRID_LINE_COLOR, width=1)

        # Scheduled Time
        start_time = task.get("scheduled_start") or "--:--"
        end_time = task.get("scheduled_end") or ""
        time_display = f"{start_time} - {end_time}" if end_time else start_time
        draw.text(
            (80, y_offset + 15),
            _to_persian(time_display),
            font=normal_font,
            fill=SECONDARY_COLOR if is_break else HEADER_COLOR,
        )

        # Vertical separator line
        draw.line([(290, y_offset), (290, y_offset + row_height - 10)], fill=GRID_LINE_COLOR, width=1)

        # Emoji + Task Name
        emoji = task.get("emoji") or ("☕" if is_break else "🔹")
        raw_name = task.get("task_name") or task.get("name") or ("استراحت" if is_break else "وظیفه")
        task_label = reshape_text(f"{emoji} {raw_name}")
        draw.text((320, y_offset + 15), task_label, font=normal_font, fill=t_color)

        # Vertical separator line
        draw.line([(POSTER_SIZE[0] - 210, y_offset), (POSTER_SIZE[0] - 210, y_offset + row_height - 10)], fill=GRID_LINE_COLOR, width=1)

        # Duration
        dur = task.get("estimated_minutes") or task.get("duration") or task.get("duration_minutes") or 0
        if not is_break:
            total_minutes += dur
        dur_str = f"{_to_persian(str(dur))}د" if dur > 0 else ""
        draw.text((POSTER_SIZE[0] - 180, y_offset + 15), reshape_text(dur_str), font=normal_font, fill=SECONDARY_COLOR)

        y_offset += row_height
        if y_offset > POSTER_SIZE[1] - 180:
            break

    # 4. Footer
    footer_y = POSTER_SIZE[1] - 120
    draw.rectangle([60, footer_y - 15, POSTER_SIZE[0] - 60, footer_y + 45], fill=None, outline=ACCENT_COLOR, width=2)

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


import datetime

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
    # The user requested ABSOLUTELY NO dark overlay, so we set opacity to 0 or very low (just 20 for slight contrast if needed, but 0 is what they asked)
    img = apply_dark_overlay(img, opacity=0) 
    draw = ImageDraw.Draw(img)

    title_font = load_font(35)
    subtitle_font = load_font(20)
    normal_font = load_font(20)
    small_font = load_font(16)
    tiny_font = load_font(18)

    # Bot ID top right
    bot_id = "@VoltaTaskBot"
    try:
        bw = draw.textlength(bot_id, font=tiny_font)
    except Exception:
        bw = 100
    draw.text((WEEKLY_SIZE[0] - bw - 40, 20), bot_id, font=tiny_font, fill=SECONDARY_COLOR)

    # Date info
    date_str = ""
    try:
        import jdatetime
        today = jdatetime.date.today()
        sat = today - jdatetime.timedelta(days=today.weekday())
        fri = sat + jdatetime.timedelta(days=6)
        date_str = f"از {sat.day} {sat.j_months_fa[sat.month-1]} تا {fri.day} {fri.j_months_fa[fri.month-1]} {fri.year}"
        date_str = _to_persian(date_str)
    except Exception:
        date_str = _to_persian("هفته جاری")

    # Title (Top Left)
    title_text = reshape_text("برنامه هفتگی")
    draw.text((30, 20), title_text, font=title_font, fill=ACCENT_COLOR)

    # Subtitle (Date Info - Top Left under Title)
    date_text = reshape_text(date_str)
    draw.text((30, 65), date_text, font=subtitle_font, fill=TEXT_COLOR)

    # 7 Days: Saturday=0 to Friday=6
    days = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
    margin_x = 70  # Shifted slightly right to give hour text more room
    avail_w = WEEKLY_SIZE[0] - margin_x - 30
    col_w = avail_w // 7
    start_y = 100  # Shifted up to give more room for the grid
    col_bottom = WEEKLY_SIZE[1] - 30
    
    # Draw Main Grid Boundary (Completely Transparent, NO FILL)
    draw.rectangle([margin_x, start_y, margin_x + avail_w, col_bottom], fill=None, outline=ACCENT_COLOR, width=3)

    # Draw vertical column lines
    glass_line_color = (255, 170, 90, 150)
    for i in range(1, 7):
        vx = margin_x + i * col_w
        draw.line([(vx, start_y), (vx, col_bottom)], fill=ACCENT_COLOR, width=2)

    # Header Row Line
    header_h = 50
    draw.line([(margin_x, start_y + header_h), (margin_x + avail_w, start_y + header_h)], fill=ACCENT_COLOR, width=2)

    # Fixed Time Range for Dynamic Google Calendar Style (05:00 to 24:00)
    min_time = 5 * 60
    max_time = 24 * 60
    total_mins = max_time - min_time
    calendar_h = col_bottom - (start_y + header_h)

    def parse_time_mins(t_str):
        try:
            h, m = map(int, t_str.split(':'))
            return h * 60 + m
        except:
            return None

    # Draw Hour Lines
    for h in range(min_time // 60, (max_time // 60) + 1):
        mins = h * 60
        y = start_y + header_h + ((mins - min_time) / total_mins) * calendar_h
        draw.line([(margin_x, y), (margin_x + avail_w, y)], fill=glass_line_color, width=1)
        
        # Draw hour text on the left margin
        hour_str = _to_persian(f"{h:02d}:00")
        draw.text((15, y - 8), hour_str, font=small_font, fill=ACCENT_COLOR)

    for i, day_name in enumerate(days):
        x = margin_x + (i * col_w)

        # Day Header
        reshaped_day = reshape_text(day_name)
        try:
            dw = draw.textlength(reshaped_day, font=subtitle_font)
        except Exception:
            dw = 60
        draw.text((x + (col_w - dw) // 2, start_y + 10), reshaped_day, font=subtitle_font, fill=ACCENT_COLOR)

        # Day Tasks (Dynamic Blocks)
        tasks = weekly_data.get(i, [])
        for task in tasks:
            s_str = task.get("anchor_start") or task.get("scheduled_start") or ""
            e_str = task.get("anchor_end") or task.get("scheduled_end") or ""
            dur = task.get("estimated_minutes") or task.get("duration") or 60
            
            start_m = parse_time_mins(s_str)
            end_m = parse_time_mins(e_str)
            
            if start_m is None:
                continue # Skip if no start time can be determined
                
            if end_m is None:
                end_m = start_m + dur

            task_y = start_y + header_h + ((start_m - min_time) / total_mins) * calendar_h
            task_h = ((end_m - start_m) / total_mins) * calendar_h
            
            # Ensure minimum height for visibility
            if task_h < 30: task_h = 30
            
            # Draw block (slightly more opaque so black text is readable on dark backgrounds)
            block_color = (255, 170, 90, 140) if not task.get("is_break") else (180, 180, 180, 140)
            outline_color = ACCENT_COLOR if not task.get("is_break") else SECONDARY_COLOR
            draw.rounded_rectangle([x + 2, task_y + 2, x + col_w - 2, task_y + task_h - 2], radius=8, fill=block_color, outline=outline_color, width=1)

            emoji = task.get("emoji") or "🔹"
            raw_name = task.get("task_name") or task.get("name") or "وظیفه"
            
            # Text fitting
            task_line = reshape_text(f"{emoji} {raw_name}")
            try:
                while draw.textlength(task_line, font=normal_font) > col_w - 15:
                    if len(raw_name) <= 2: break
                    raw_name = raw_name[:-2] + "…"
                    task_line = reshape_text(f"{emoji} {raw_name}")
            except:
                pass

            dur_line = reshape_text(_to_persian(f"{s_str} - {e_str}" if e_str else s_str))

            # Draw text if there's enough height - USING BLACK AS REQUESTED
            task_text_color = (0, 0, 0)
            task_time_color = (30, 30, 30)
            
            if task_h > 45:
                draw.text((x + 8, task_y + 5), task_line, font=normal_font, fill=task_text_color)
                draw.text((x + 8, task_y + 28), dur_line, font=small_font, fill=task_time_color)
            else:
                draw.text((x + 8, task_y + (task_h - 25)//2), task_line, font=normal_font, fill=task_text_color)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
