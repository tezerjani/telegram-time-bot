"""
NLP Engine — Gemini 2.5 Flash AI client with full exponential backoff retry.
All Gemini API calls are async via asyncio.to_thread and wrapped with tenacity retry.
"""

import asyncio
import base64
import json
import logging
import re
from typing import Optional

import google.generativeai as genai
from tenacity import (
    retry,
    retry_if_exception_type,
    wait_exponential,
    wait_random,
    stop_after_attempt,
    before_sleep_log,
)

import config

logger = logging.getLogger(__name__)

# Lazy initialization — configure on first use
_model: Optional[genai.GenerativeModel] = None


def _get_model() -> genai.GenerativeModel:
    """Return (and lazily initialize) the Gemini model."""
    global _model
    if _model is None:
        genai.configure(api_key=config.GEMINI_API_KEY)
        _model = genai.GenerativeModel(config.GEMINI_MODEL)
    return _model


# ---------------------------------------------------------------------------
# Retry-wrapped Gemini call
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=config.BASE_BACKOFF, min=1, max=config.MAX_BACKOFF)
    + wait_random(0, 2),
    stop=stop_after_attempt(config.MAX_RETRIES),
    reraise=True,
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def _call_gemini(contents, generation_config=None) -> str:
    """Execute a Gemini generate_content call in a thread pool with retry."""
    model = _get_model()
    if generation_config is not None:
        response = await asyncio.to_thread(
            model.generate_content, contents, generation_config=generation_config
        )
    else:
        response = await asyncio.to_thread(model.generate_content, contents)
    return response.text


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def _safe_parse_json(raw: str) -> list[dict]:
    """
    Attempt to parse JSON from Gemini output.
    Gemini sometimes wraps JSON in markdown fences — strip them first.
    """
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return []
    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini JSON response: %s", text[:200])
        return []


# ---------------------------------------------------------------------------
# Task parsing — text
# ---------------------------------------------------------------------------

_TASK_SCHEMA_PROMPT = """\
Return ONLY a valid JSON array (no markdown, no explanations).
Each element must have exactly these keys:
- "task_name": string — task description
- "emoji": string — ONLY assign if highly obvious match:
    👨🏻‍💻 coding/programming, 📚 reading/study, 🏃🏻‍♂️ running/cardio,
    🎯 goals/planning, 💪 gym/workout, 🍽️ eating/meal, 😴 sleep,
    🚿 shower/hygiene, 📝 writing, 📞 call/meeting.
    Use "" (empty string) if no clear match.
- "estimated_minutes": integer — default 60 if not specified
- "is_anchor": boolean — true only if user specifies a fixed/exact time
- "anchor_start": string "HH:MM" or null
- "anchor_end": string "HH:MM" or null
- "cognitive_load": string — "high" (deep focus work), "medium" (moderate), "low" (routine/light)
"""


async def parse_tasks_from_text(
    text: str, wake_time: str = "07:00", sleep_time: str = "23:00"
) -> list[dict]:
    """
    Parse a bulk Persian/English task text into structured task dicts.
    Returns list of task dicts ready for the scheduler.
    """
    prompt = f"""{_TASK_SCHEMA_PROMPT}

Context:
- Wake time: {wake_time}
- Sleep time: {sleep_time}
- Text to parse (may be Persian, English, or mixed):

{text}
"""
    generation_config = genai.GenerationConfig(response_mime_type="application/json")
    try:
        raw = await _call_gemini(prompt, generation_config=generation_config)
        return _safe_parse_json(raw)
    except Exception as exc:
        logger.error("parse_tasks_from_text failed after retries: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Task parsing — voice/audio
# ---------------------------------------------------------------------------

async def parse_tasks_from_voice(
    audio_bytes: bytes, mime_type: str = "audio/ogg; codecs=opus"
) -> list[dict]:
    """
    Parse tasks from a voice note (audio bytes).
    Falls back to audio/ogg if the primary mime_type is rejected.
    """
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    prompt_text = (
        f"{_TASK_SCHEMA_PROMPT}\n\n"
        "The audio is in Persian or English (or mixed). "
        "Listen carefully, identify all mentioned tasks/activities, "
        "and return the JSON array."
    )
    generation_config = genai.GenerationConfig(response_mime_type="application/json")

    def _build_contents(mt: str) -> list:
        return [
            {
                "parts": [
                    {"inline_data": {"mime_type": mt, "data": audio_b64}},
                    {"text": prompt_text},
                ]
            }
        ]

    for attempt_mime in [mime_type, "audio/ogg", "audio/mp4"]:
        try:
            raw = await _call_gemini(
                _build_contents(attempt_mime), generation_config=generation_config
            )
            result = _safe_parse_json(raw)
            if result:
                return result
        except Exception as exc:
            logger.warning(
                "parse_tasks_from_voice failed with mime_type=%s: %s", attempt_mime, exc
            )
    return []


# ---------------------------------------------------------------------------
# Simple transcription
# ---------------------------------------------------------------------------

async def transcribe_audio(
    audio_bytes: bytes, mime_type: str = "audio/ogg; codecs=opus"
) -> str:
    """Transcribe audio to text (Persian/English)."""
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    contents = [
        {
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": audio_b64}},
                {
                    "text": (
                        "Transcribe the audio accurately. "
                        "The language may be Persian or English or mixed. "
                        "Return only the transcription text."
                    )
                },
            ]
        }
    ]
    for attempt_mime in [mime_type, "audio/ogg"]:
        try:
            contents[0]["parts"][0]["inline_data"]["mime_type"] = attempt_mime
            return await _call_gemini(contents)
        except Exception as exc:
            logger.warning("transcribe_audio failed with mime_type=%s: %s", attempt_mime, exc)
    return ""


# ---------------------------------------------------------------------------
# Productivity insight
# ---------------------------------------------------------------------------

async def generate_productivity_insight(
    score: float,
    completed: int,
    planned: int,
    streak: int,
    journal_note: str = "",
) -> str:
    """
    Generate a short motivational Persian message (2-3 sentences)
    based on the user's daily productivity data.
    """
    prompt = f"""\
شما یک دستیار انگیزشی هوشمند هستید. یک پیام کوتاه فارسی (۲ تا ۳ جمله) بنویسید که:
- برای امتیاز بهره‌وری {score:.0f}% مناسب باشد
- {completed} دقیقه از {planned} دقیقه برنامه‌ریزی‌شده تکمیل شده
- کاربر {streak} روز پشت سر هم موفق بوده
- یادداشت روزانه: "{journal_note}"
پیام باید صادقانه، گرم و انگیزه‌دهنده باشد. فقط متن فارسی برگردانید.
"""
    try:
        return await _call_gemini(prompt)
    except Exception as exc:
        logger.error("generate_productivity_insight failed: %s", exc)
        if score >= 70:
            return "عالی بود! به این روند ادامه بده. 🌟"
        return "امروز تلاش کردی. فردا بهتر خواهی شد. 💪"


# ---------------------------------------------------------------------------
# Weekly summary insight
# ---------------------------------------------------------------------------

async def generate_weekly_summary_insight(week_data: list[dict]) -> str:
    """
    Generate a 3-4 sentence Persian weekly summary with encouragement
    based on the user's daily journal data for the past week.
    """
    if not week_data:
        return "داده‌ای برای این هفته یافت نشد."

    avg_score = sum(d.get("productivity_score", 0) for d in week_data) / len(week_data)
    total_minutes = sum(d.get("completed_minutes", 0) for d in week_data)

    prompt = f"""\
شما یک مربی بهره‌وری هوشمند هستید. یک خلاصه هفتگی فارسی (۳ تا ۴ جمله) بنویسید:
- میانگین امتیاز هفته: {avg_score:.0f}%
- مجموع دقایق مفید: {total_minutes} دقیقه
- داده‌های روزانه: {json.dumps(week_data, ensure_ascii=False)}
خلاصه باید تحلیل‌گرانه، دلسوزانه و انگیزه‌دهنده باشد. فقط متن فارسی برگردانید.
"""
    try:
        return await _call_gemini(prompt)
    except Exception as exc:
        logger.error("generate_weekly_summary_insight failed: %s", exc)
        return f"میانگین بهره‌وری این هفته: {avg_score:.0f}%. مجموع {total_minutes} دقیقه کار مفید. 📊"
