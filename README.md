# Telegram Time-Management Assistant

A comprehensive daily/weekly time management and personal assistant Telegram bot built with `python-telegram-bot` and `google-generativeai`.

## Architecture
```
User -> Telegram API -> main.py (Bot + Health Server) -> Handlers (Auth, Plan, Deck, Analytics) -> Database (Turso SQLite)
```

## Setup Instructions

### Prerequisites
- Python 3.11+
- ffmpeg installed on your system
- Turso Database Account (libsql)
- Gemini API Key
- Telegram Bot Token (from BotFather)

### Installation
1. Clone the repository.
2. Copy `.env.example` to `.env` and configure the required variables.
3. Ensure you have `assets/background.jpg` and `assets/font.ttf` configured if you are generating posters/images.
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Run the bot:
   ```bash
   python main.py
   ```

### Docker Deployment (Koyeb / Render)
1. Build the image:
   ```bash
   docker build -t tg-assistant .
   ```
2. Run the image, passing your environment variables.
3. When deploying to Koyeb/Render, make sure to set the correct environment variables and expose port 8000 for the health check.

## Commands

| Command | Description |
|---|---|
| `/start` | Start bot & request access |
| `/plan` | Interactive daily task planner |
| `/bulk` | Bulk text task import |
| `/deck` | Live control deck |
| `/review` | Nightly review & journaling |
| `/weekly` | Weekly schedule manager |
| `/weekly_view` | View weekly grid poster |
| `/apply_weekly` | Apply weekly template to today |
| `/stats_week` | Weekly analytics |
| `/stats_month` | Monthly analytics |
| `/badges` | View earned badges |
| `/mystats` | Personal stats dashboard |
| `/admin` | Admin panel (admin only) |
| `/broadcast` | Broadcast message (admin only) |
| `/cancel` | Cancel current operation |

## Environment Variables
- `BOT_TOKEN`: Your Telegram Bot API token.
- `GEMINI_API_KEY`: API Key for Google Generative AI.
- `TURSO_DATABASE_URL`: Turso Database URL.
- `TURSO_AUTH_TOKEN`: Auth token for Turso.
- `ADMIN_ID`: Telegram User ID of the administrator.
- `TIMEZONE`: (Optional) Your timezone, defaults to Asia/Tehran.
- `PORT`: (Optional) Health check server port, defaults to 8000.

## Tech Stack
- python-telegram-bot (v21.6)
- aiohttp
- google-generativeai
- Turso / libsql
- Pillow (Image generation)
- pydub (Audio handling)
