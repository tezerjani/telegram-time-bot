import aiohttp
import json
from datetime import datetime
from typing import Any, List, Dict, Optional
import config

def _format_args(args: List[Any]) -> List[Dict[str, Any]]:
    """Format Python arguments into Turso pipeline argument format."""
    formatted = []
    for arg in args:
        if arg is None:
            formatted.append({"type": "null"})
        elif isinstance(arg, bool):
            formatted.append({"type": "integer", "value": "1" if arg else "0"})
        elif isinstance(arg, int):
            formatted.append({"type": "integer", "value": str(arg)})
        elif isinstance(arg, float):
            formatted.append({"type": "float", "value": str(arg)})
        else:
            formatted.append({"type": "text", "value": str(arg)})
    return formatted

def _rows_to_dicts(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert Turso row results into a list of dictionaries."""
    try:
        # Extract from response structure: response['results'][0]['response']['result']
        res = result.get('results', [])[0].get('response', {}).get('result', {})
        cols = [col.get('name') for col in res.get('cols', [])]
        rows = res.get('rows', [])
        
        final_results = []
        for row in rows:
            row_dict = {}
            for i, col_name in enumerate(cols):
                val_obj = row[i]
                val_type = val_obj.get("type")
                val = val_obj.get("value")
                
                if val_type == "null":
                    row_dict[col_name] = None
                elif val_type == "integer":
                    row_dict[col_name] = int(val)
                elif val_type in ("float", "real"):
                    row_dict[col_name] = float(val)
                else:
                    row_dict[col_name] = val
            final_results.append(row_dict)
        return final_results
    except (IndexError, KeyError, TypeError, ValueError, AttributeError):
        return []

async def execute(sql: str, args: List[Any] = None) -> Dict[str, Any]:
    """Execute a single SQL statement on the Turso database."""
    url = f"{config.TURSO_DATABASE_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {config.TURSO_AUTH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    stmt: Dict[str, Any] = {"sql": sql}
    if args is not None:
        stmt["args"] = _format_args(args)
        
    payload = {
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

async def execute_many(statements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Execute multiple SQL statements in a single Turso pipeline batch."""
    url = f"{config.TURSO_DATABASE_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {config.TURSO_AUTH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    requests = []
    for stmt_data in statements:
        stmt = {"sql": stmt_data["sql"]}
        if "args" in stmt_data and stmt_data["args"] is not None:
            stmt["args"] = _format_args(stmt_data["args"])
        requests.append({"type": "execute", "stmt": stmt})
    
    requests.append({"type": "close"})
    payload = {"requests": requests}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

async def init_db() -> None:
    """Creates all tables if they do not exist."""
    tables_sql = [
        """
        CREATE TABLE IF NOT EXISTS users (
          user_id INTEGER PRIMARY KEY,
          username TEXT,
          full_name TEXT,
          status TEXT DEFAULT 'pending',
          wake_time TEXT DEFAULT '07:00',
          sleep_time TEXT DEFAULT '23:00',
          scheduling_mode TEXT DEFAULT 'auto',
          streak_days INTEGER DEFAULT 0,
          total_productive_minutes INTEGER DEFAULT 0,
          created_at TEXT,
          approved_at TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS daily_tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          task_name TEXT,
          emoji TEXT DEFAULT '',
          estimated_minutes INTEGER,
          actual_minutes INTEGER DEFAULT 0,
          start_time TEXT,
          end_time TEXT,
          is_anchor INTEGER DEFAULT 0,
          anchor_start TEXT,
          anchor_end TEXT,
          cognitive_load TEXT DEFAULT 'medium',
          status TEXT DEFAULT 'pending',
          task_date TEXT,
          scheduled_start TEXT,
          scheduled_end TEXT,
          sort_order INTEGER DEFAULT 0,
          created_at TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS weekly_schedules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          day_of_week INTEGER,
          task_name TEXT,
          emoji TEXT DEFAULT '',
          estimated_minutes INTEGER,
          is_anchor INTEGER DEFAULT 0,
          anchor_start TEXT,
          anchor_end TEXT,
          cognitive_load TEXT DEFAULT 'medium',
          is_active INTEGER DEFAULT 1,
          sort_order INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS badges (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          badge_type TEXT,
          awarded_at TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS daily_journals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          journal_date TEXT,
          note TEXT,
          productivity_score REAL DEFAULT 0.0,
          planned_minutes INTEGER DEFAULT 0,
          completed_minutes INTEGER DEFAULT 0,
          created_at TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS ephemeral_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          chat_id INTEGER,
          message_id INTEGER,
          delete_at TEXT,
          created_at TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS progress_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          chat_id INTEGER,
          message_id INTEGER,
          task_id INTEGER,
          last_updated TEXT
        );
        """
    ]
    
    statements = [{"sql": sql} for sql in tables_sql]
    await execute_many(statements)

# --- User functions ---

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM users WHERE user_id = ?"
    result = await execute(sql, [user_id])
    rows = _rows_to_dicts(result)
    return rows[0] if rows else None

async def create_user(user_id: int, username: str, full_name: str) -> None:
    sql = """
        INSERT INTO users (user_id, username, full_name, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            username = excluded.username,
            full_name = excluded.full_name
    """
    now = datetime.utcnow().isoformat()
    await execute(sql, [user_id, username, full_name, now])

async def update_user_status(user_id: int, status: str) -> None:
    sql = "UPDATE users SET status = ?"
    args = [status]
    if status == 'active':
        sql += ", approved_at = ?"
        args.append(datetime.utcnow().isoformat())
    sql += " WHERE user_id = ?"
    args.append(user_id)
    await execute(sql, args)

async def update_user_settings(user_id: int, **kwargs) -> None:
    if not kwargs:
        return
    valid_keys = {'wake_time', 'sleep_time', 'scheduling_mode'}
    updates = []
    args = []
    for k, v in kwargs.items():
        if k in valid_keys:
            updates.append(f"{k} = ?")
            args.append(v)
    
    if not updates:
        return
        
    sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
    args.append(user_id)
    await execute(sql, args)

async def get_all_active_users() -> List[Dict[str, Any]]:
    sql = "SELECT * FROM users WHERE status = 'active'"
    result = await execute(sql)
    return _rows_to_dicts(result)

async def get_pending_users() -> List[Dict[str, Any]]:
    sql = "SELECT * FROM users WHERE status = 'pending'"
    result = await execute(sql)
    return _rows_to_dicts(result)

async def increment_streak(user_id: int) -> None:
    sql = "UPDATE users SET streak_days = streak_days + 1 WHERE user_id = ?"
    await execute(sql, [user_id])

async def reset_streak(user_id: int) -> None:
    sql = "UPDATE users SET streak_days = 0 WHERE user_id = ?"
    await execute(sql, [user_id])

async def add_productive_minutes(user_id: int, minutes: int) -> None:
    sql = "UPDATE users SET total_productive_minutes = total_productive_minutes + ? WHERE user_id = ?"
    await execute(sql, [minutes, user_id])

# --- Task functions ---

async def add_task(user_id: int, task_data: Dict[str, Any], task_date: str) -> int:
    sql = """
        INSERT INTO daily_tasks (
            user_id, task_name, emoji, estimated_minutes, is_anchor, 
            anchor_start, anchor_end, cognitive_load, task_date, 
            scheduled_start, scheduled_end, sort_order, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """
    args = [
        user_id,
        task_data.get('task_name'),
        task_data.get('emoji', ''),
        task_data.get('estimated_minutes', 0),
        1 if task_data.get('is_anchor') else 0,
        task_data.get('anchor_start'),
        task_data.get('anchor_end'),
        task_data.get('cognitive_load', 'medium'),
        task_date,
        task_data.get('scheduled_start'),
        task_data.get('scheduled_end'),
        task_data.get('sort_order', 0),
        datetime.utcnow().isoformat()
    ]
    result = await execute(sql, args)
    rows = _rows_to_dicts(result)
    return rows[0]['id'] if rows else 0

async def get_tasks_for_date(user_id: int, task_date: str) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM daily_tasks WHERE user_id = ? AND task_date = ? ORDER BY sort_order ASC, scheduled_start ASC"
    result = await execute(sql, [user_id, task_date])
    return _rows_to_dicts(result)

async def update_task_status(task_id: int, status: str) -> None:
    sql = "UPDATE daily_tasks SET status = ?"
    args = [status]
    if status == 'active':
        sql += ", start_time = ?"
        args.append(datetime.utcnow().isoformat())
    elif status == 'done':
        sql += ", end_time = ?"
        args.append(datetime.utcnow().isoformat())
    
    sql += " WHERE id = ?"
    args.append(task_id)
    await execute(sql, args)

async def update_task_scheduled_times(task_id: int, scheduled_start: str, scheduled_end: str) -> None:
    sql = "UPDATE daily_tasks SET scheduled_start = ?, scheduled_end = ? WHERE id = ?"
    await execute(sql, [scheduled_start, scheduled_end, task_id])

async def update_task_actual_minutes(task_id: int, actual_minutes: int) -> None:
    sql = "UPDATE daily_tasks SET actual_minutes = ? WHERE id = ?"
    await execute(sql, [actual_minutes, task_id])

async def delete_task(task_id: int) -> None:
    sql = "DELETE FROM daily_tasks WHERE id = ?"
    await execute(sql, [task_id])

async def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM daily_tasks WHERE id = ?"
    result = await execute(sql, [task_id])
    rows = _rows_to_dicts(result)
    return rows[0] if rows else None

async def get_active_task(user_id: int, task_date: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM daily_tasks WHERE user_id = ? AND task_date = ? AND status = 'active' LIMIT 1"
    result = await execute(sql, [user_id, task_date])
    rows = _rows_to_dicts(result)
    return rows[0] if rows else None

# --- Weekly schedule functions ---

async def add_weekly_task(user_id: int, day: int, task_data: Dict[str, Any]) -> int:
    sql = """
        INSERT INTO weekly_schedules (
            user_id, day_of_week, task_name, emoji, estimated_minutes, 
            is_anchor, anchor_start, anchor_end, cognitive_load, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """
    args = [
        user_id,
        day,
        task_data.get('task_name'),
        task_data.get('emoji', ''),
        task_data.get('estimated_minutes', 0),
        1 if task_data.get('is_anchor') else 0,
        task_data.get('anchor_start'),
        task_data.get('anchor_end'),
        task_data.get('cognitive_load', 'medium'),
        task_data.get('sort_order', 0)
    ]
    result = await execute(sql, args)
    rows = _rows_to_dicts(result)
    return rows[0]['id'] if rows else 0

async def get_weekly_schedule(user_id: int, day: int) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM weekly_schedules WHERE user_id = ? AND day_of_week = ? AND is_active = 1 ORDER BY sort_order ASC"
    result = await execute(sql, [user_id, day])
    return _rows_to_dicts(result)

async def get_full_weekly_schedule(user_id: int) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM weekly_schedules WHERE user_id = ? AND is_active = 1 ORDER BY day_of_week ASC, sort_order ASC"
    result = await execute(sql, [user_id])
    return _rows_to_dicts(result)

async def clone_day_to_days(user_id: int, source_day: int, target_days: List[int]) -> None:
    source_tasks = await get_weekly_schedule(user_id, source_day)
    if not source_tasks:
        return
        
    statements = []
    for t_day in target_days:
        # First clear the target day
        statements.append({
            "sql": "DELETE FROM weekly_schedules WHERE user_id = ? AND day_of_week = ?",
            "args": [user_id, t_day]
        })
        # Then insert clones
        for task in source_tasks:
            statements.append({
                "sql": """
                    INSERT INTO weekly_schedules (
                        user_id, day_of_week, task_name, emoji, estimated_minutes, 
                        is_anchor, anchor_start, anchor_end, cognitive_load, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                "args": [
                    user_id, t_day, task['task_name'], task['emoji'], task['estimated_minutes'],
                    task['is_anchor'], task['anchor_start'], task['anchor_end'], 
                    task['cognitive_load'], task['sort_order']
                ]
            })
    if statements:
        await execute_many(statements)

async def clear_weekly_day(user_id: int, day: int) -> None:
    sql = "DELETE FROM weekly_schedules WHERE user_id = ? AND day_of_week = ?"
    await execute(sql, [user_id, day])

# --- Badge & journal functions ---

async def award_badge(user_id: int, badge_type: str) -> None:
    sql = "INSERT INTO badges (user_id, badge_type, awarded_at) VALUES (?, ?, ?)"
    await execute(sql, [user_id, badge_type, datetime.utcnow().isoformat()])

async def get_badges(user_id: int) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM badges WHERE user_id = ? ORDER BY awarded_at DESC"
    result = await execute(sql, [user_id])
    return _rows_to_dicts(result)

async def has_badge(user_id: int, badge_type: str) -> bool:
    sql = "SELECT id FROM badges WHERE user_id = ? AND badge_type = ? LIMIT 1"
    result = await execute(sql, [user_id, badge_type])
    return len(_rows_to_dicts(result)) > 0

async def save_journal(user_id: int, journal_date: str, note: str, score: float, planned: int, completed: int) -> None:
    sql = """
        INSERT INTO daily_journals (user_id, journal_date, note, productivity_score, planned_minutes, completed_minutes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    await execute(sql, [user_id, journal_date, note, score, planned, completed, datetime.utcnow().isoformat()])

async def get_journal(user_id: int, journal_date: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM daily_journals WHERE user_id = ? AND journal_date = ? LIMIT 1"
    result = await execute(sql, [user_id, journal_date])
    rows = _rows_to_dicts(result)
    return rows[0] if rows else None

async def get_journals_range(user_id: int, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM daily_journals WHERE user_id = ? AND journal_date >= ? AND journal_date <= ? ORDER BY journal_date ASC"
    result = await execute(sql, [user_id, start_date, end_date])
    return _rows_to_dicts(result)

# --- Ephemeral & progress message tracking ---

async def track_ephemeral(user_id: int, chat_id: int, message_id: int, delete_at: str) -> None:
    sql = "INSERT INTO ephemeral_messages (user_id, chat_id, message_id, delete_at, created_at) VALUES (?, ?, ?, ?, ?)"
    await execute(sql, [user_id, chat_id, message_id, delete_at, datetime.utcnow().isoformat()])

async def get_expired_ephemerals(current_time: str) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM ephemeral_messages WHERE delete_at <= ?"
    result = await execute(sql, [current_time])
    return _rows_to_dicts(result)

async def delete_ephemeral_record(record_id: int) -> None:
    sql = "DELETE FROM ephemeral_messages WHERE id = ?"
    await execute(sql, [record_id])

async def save_progress_message(user_id: int, chat_id: int, message_id: int, task_id: int) -> None:
    sql = """
        INSERT INTO progress_messages (user_id, chat_id, message_id, task_id, last_updated)
        VALUES (?, ?, ?, ?, ?)
    """
    await execute(sql, [user_id, chat_id, message_id, task_id, datetime.utcnow().isoformat()])

async def get_progress_message(user_id: int) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM progress_messages WHERE user_id = ? LIMIT 1"
    result = await execute(sql, [user_id])
    rows = _rows_to_dicts(result)
    return rows[0] if rows else None

async def update_progress_message_time(record_id: int, last_updated: str) -> None:
    sql = "UPDATE progress_messages SET last_updated = ? WHERE id = ?"
    await execute(sql, [last_updated, record_id])

async def delete_progress_message(user_id: int) -> None:
    sql = "DELETE FROM progress_messages WHERE user_id = ?"
    await execute(sql, [user_id])
