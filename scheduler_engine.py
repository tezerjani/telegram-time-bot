import datetime
import zoneinfo
import typing
import logging
import math

try:
    import config
except ImportError:
    config = None

# Key Constants
ULTRADIAN_WORK_BLOCK = 90  # minutes
ULTRADIAN_BREAK = 15  # minutes
BREAK_TASK_NAME = 'بریک / استراحت'
BREAK_EMOJI = '☕'
MIN_MORNING_BUFFER = 15  # minutes after wake
PRE_SLEEP_BUFFER = 30  # minutes before sleep for review


def get_today_date_str(tz: str = None) -> str:
    """Returns today's date as 'YYYY-MM-DD' in given timezone."""
    now = get_now(tz)
    return now.strftime('%Y-%m-%d')


def get_now(tz: str = None) -> datetime.datetime:
    """Returns current datetime in given timezone."""
    if tz:
        return datetime.datetime.now(zoneinfo.ZoneInfo(tz))
    return datetime.datetime.now()


def parse_time(time_str: str, date_str: str = None, tz: str = None) -> datetime.datetime:
    """Parse 'HH:MM' into timezone-aware datetime."""
    if date_str is None:
        date_str = get_today_date_str(tz)
    
    dt_str = f"{date_str} {time_str}"
    dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
    
    if tz:
        return dt.replace(tzinfo=zoneinfo.ZoneInfo(tz))
    return dt


def minutes_to_time_str(base_dt: datetime.datetime, minutes: int) -> str:
    """Add minutes to base_dt, return 'HH:MM' string."""
    new_dt = base_dt + datetime.timedelta(minutes=minutes)
    return new_dt.strftime('%H:%M')


def validate_time_collision(tasks: list[dict]) -> list[tuple]:
    """Checks for overlapping anchor tasks. Returns list of (task1_name, task2_name) collision tuples."""
    anchors = [t for t in tasks if t.get('anchor_start') and t.get('anchor_end')]
    
    # Convert string times to minute of day for easy comparison
    def time_to_mins(t_str):
        h, m = map(int, t_str.split(':'))
        return h * 60 + m

    anchors_sorted = sorted(anchors, key=lambda x: time_to_mins(x['anchor_start']))
    collisions = []
    
    for i in range(len(anchors_sorted)):
        for j in range(i + 1, len(anchors_sorted)):
            t1 = anchors_sorted[i]
            t2 = anchors_sorted[j]
            
            start1 = time_to_mins(t1['anchor_start'])
            end1 = time_to_mins(t1['anchor_end'])
            start2 = time_to_mins(t2['anchor_start'])
            end2 = time_to_mins(t2['anchor_end'])
            
            # If t2 starts before t1 ends, there's a collision
            if start2 < end1 and start1 < end2:
                collisions.append((t1.get('name', 'Task 1'), t2.get('name', 'Task 2')))
                
    return collisions


def validate_against_sleep(tasks: list[dict], sleep_time: str) -> list[str]:
    """Returns list of task names that would extend past sleep_time."""
    h_s, m_s = map(int, sleep_time.split(':'))
    sleep_mins = h_s * 60 + m_s
    
    # Handle overnight sleep times (e.g., 01:00) by shifting to next day
    if sleep_mins < 12 * 60:
        sleep_mins += 24 * 60
        
    exceeding_tasks = []
    
    for task in tasks:
        if task.get('scheduled_end'):
            h, m = map(int, task['scheduled_end'].split(':'))
            end_mins = h * 60 + m
            if end_mins < 12 * 60 and sleep_mins >= 24 * 60:
                end_mins += 24 * 60
                
            if end_mins > sleep_mins:
                exceeding_tasks.append(task.get('name', 'Unknown Task'))
                
    return exceeding_tasks


def schedule_auto(
    tasks: list[dict],
    wake_time: str,
    sleep_time: str,
    date_str: str,
    tz: str
) -> list[dict]:
    """
    Full auto-scheduling algorithm:
    1. Sort tasks: anchors first (by anchor_start), then by cognitive_load (high→morning, low→afternoon).
    2. Schedule anchors at their exact times.
    3. Fill gaps between anchors with non-anchor tasks.
    4. Insert 15-minute Ultradian breaks after every 90 minutes of work.
    5. Leave PRE_SLEEP_BUFFER before sleep_time.
    6. Return list of tasks with scheduled_start and scheduled_end fields added.
    """
    def time_to_mins(t_str):
        if not t_str:
            return 0
        import duration_parser
        norm = duration_parser.normalize_time_str(t_str)
        if norm:
            h, m = map(int, norm.split(':'))
            return h * 60 + m
        return 0
        
    def mins_to_time(mins):
        h = (mins // 60) % 24
        m = mins % 60
        return f"{h:02d}:{m:02d}"

    wake_mins = time_to_mins(wake_time)
    sleep_mins = time_to_mins(sleep_time)
    if sleep_mins < wake_mins:
        sleep_mins += 24 * 60
        
    # Base start time
    current_time = wake_mins + MIN_MORNING_BUFFER
    
    # If scheduling for today, don't schedule floating tasks in the past
    import datetime
    import zoneinfo
    tz_obj = zoneinfo.ZoneInfo(tz) if tz else datetime.timezone.utc
    now = datetime.datetime.now(tz_obj)
    if date_str == now.strftime('%Y-%m-%d'):
        now_mins = now.hour * 60 + now.minute
        # If we are already past the base start time, schedule from now
        if now_mins > current_time:
            current_time = now_mins + 5 # Add 5 min buffer from now
    
    anchors = []
    floating = []
    
    for t in tasks:
        # Create a copy so we don't mutate original yet
        t_copy = dict(t)
        if t_copy.get('anchor_start') and t_copy.get('anchor_end'):
            anchors.append(t_copy)
        else:
            floating.append(t_copy)
            
    # Sort anchors by start time
    anchors.sort(key=lambda x: time_to_mins(x['anchor_start']))
    
    # Sort floating by cognitive load (assuming high=3, med=2, low=1)
    # Highest first
    floating.sort(key=lambda x: x.get('cognitive_load', 1), reverse=True)
    
    scheduled_tasks = []
    consecutive_work = 0
    sort_idx = 0
    
    def insert_break(start_min):
        nonlocal sort_idx
        b_task = {
            'name': BREAK_TASK_NAME,
            'emoji': BREAK_EMOJI,
            'duration': ULTRADIAN_BREAK,
            'scheduled_start': mins_to_time(start_min),
            'scheduled_end': mins_to_time(start_min + ULTRADIAN_BREAK),
            'sort_order': sort_idx,
            'is_break': True
        }
        scheduled_tasks.append(b_task)
        sort_idx += 1
        return start_min + ULTRADIAN_BREAK

    # We need to interleave floating tasks between anchors
    floating_idx = 0
    anchor_idx = 0
    
    while floating_idx < len(floating) or anchor_idx < len(anchors):
        next_anchor_start = time_to_mins(anchors[anchor_idx]['anchor_start']) if anchor_idx < len(anchors) else float('inf')
        
        # If we reached an anchor
        if current_time >= next_anchor_start:
            a_task = anchors[anchor_idx]
            # Reset consecutive work when an anchor starts
            consecutive_work = 0 
            
            start = time_to_mins(a_task['anchor_start'])
            end = time_to_mins(a_task['anchor_end'])
            
            # If current_time has passed start, we just stick to anchor's fixed time anyway
            a_task['scheduled_start'] = a_task['anchor_start']
            a_task['scheduled_end'] = a_task['anchor_end']
            a_task['sort_order'] = sort_idx
            
            scheduled_tasks.append(a_task)
            sort_idx += 1
            current_time = max(current_time, end)
            anchor_idx += 1
            continue
            
        # Try to schedule a floating task
        if floating_idx < len(floating):
            f_task = floating[floating_idx]
            duration = f_task.get('duration', 30)
            
            # Check if it fits before next anchor
            if current_time + duration <= next_anchor_start:
                # Check for ultradian break
                if consecutive_work + duration > ULTRADIAN_WORK_BLOCK:
                    # Time for a break! Let's insert it if it fits before anchor
                    if current_time + ULTRADIAN_BREAK <= next_anchor_start:
                        current_time = insert_break(current_time)
                        consecutive_work = 0
                    else:
                        # Break doesn't fit before anchor, wait for anchor
                        current_time = next_anchor_start
                        continue
                        
                f_task['scheduled_start'] = mins_to_time(current_time)
                current_time += duration
                f_task['scheduled_end'] = mins_to_time(current_time)
                f_task['sort_order'] = sort_idx
                
                scheduled_tasks.append(f_task)
                sort_idx += 1
                consecutive_work += duration
                floating_idx += 1
            else:
                # Doesn't fit, skip to anchor
                current_time = next_anchor_start
        else:
            # No more floating, just jump to next anchor
            current_time = next_anchor_start

    return scheduled_tasks


def schedule_manual(tasks: list[dict]) -> list[dict]:
    """
    For manual mode: tasks already have anchor_start/anchor_end.
    Just sort by anchor_start, add scheduled_start=anchor_start, scheduled_end=anchor_end.
    Detect and return with collision info in each task dict.
    """
    def time_to_mins(t_str):
        if not t_str: return 0
        h, m = map(int, t_str.split(':'))
        return h * 60 + m
        
    tasks_copy = [dict(t) for t in tasks]
    
    # Sort
    tasks_copy.sort(key=lambda x: time_to_mins(x.get('anchor_start', '00:00')))
    
    # Find collisions
    for i, t in enumerate(tasks_copy):
        t['scheduled_start'] = t.get('anchor_start')
        t['scheduled_end'] = t.get('anchor_end')
        t['sort_order'] = i
        t['has_collision'] = False
        t['collision_with'] = []
        
    for i in range(len(tasks_copy)):
        for j in range(i + 1, len(tasks_copy)):
            t1 = tasks_copy[i]
            t2 = tasks_copy[j]
            
            if not (t1.get('scheduled_start') and t1.get('scheduled_end') and t2.get('scheduled_start') and t2.get('scheduled_end')):
                continue
                
            start1 = time_to_mins(t1['scheduled_start'])
            end1 = time_to_mins(t1['scheduled_end'])
            start2 = time_to_mins(t2['scheduled_start'])
            end2 = time_to_mins(t2['scheduled_end'])
            
            if start2 < end1 and start1 < end2:
                t1['has_collision'] = True
                t1['collision_with'].append(t2.get('name'))
                t2['has_collision'] = True
                t2['collision_with'].append(t1.get('name'))
                
    return tasks_copy


def extend_task(tasks: list[dict], task_id: int, extra_minutes: int) -> list[dict]:
    """Adds extra_minutes to the given task and cascades the delay to all subsequent floating (non-anchor) tasks."""
    # Note: In a real implementation we would identify by a real ID. Here we use 'id' field.
    def time_to_mins(t_str):
        h, m = map(int, t_str.split(':'))
        return h * 60 + m
        
    def mins_to_time(mins):
        h = (mins // 60) % 24
        m = mins % 60
        return f"{h:02d}:{m:02d}"

    tasks_copy = [dict(t) for t in tasks]
    delay = 0
    
    for i, t in enumerate(tasks_copy):
        if t.get('id') == task_id:
            delay = extra_minutes
            
            # Extend this task
            end = time_to_mins(t['scheduled_end']) + delay
            t['scheduled_end'] = mins_to_time(end)
            if 'duration' in t:
                t['duration'] += delay
            continue
            
        if delay > 0:
            # If it's an anchor, we cannot shift it. Delay is either absorbed or it collides.
            # Simplified cascade: shift floating tasks, skip anchors.
            if t.get('anchor_start'):
                # delay absorbed or we stop cascading
                # naive approach: zero out delay if we hit an anchor, or just leave it
                pass 
            else:
                start = time_to_mins(t['scheduled_start']) + delay
                end = time_to_mins(t['scheduled_end']) + delay
                t['scheduled_start'] = mins_to_time(start)
                t['scheduled_end'] = mins_to_time(end)

    return tasks_copy


def skip_task(tasks: list[dict], task_id: int) -> list[dict]:
    """Marks the given task as 'skipped' and moves its time to the next task (or leaves a gap)."""
    tasks_copy = [dict(t) for t in tasks]
    for t in tasks_copy:
        if t.get('id') == task_id:
            t['status'] = 'skipped'
            
    # For now, simply marking as skipped. 
    # Recalculating whole schedule would require `schedule_auto` again.
    return tasks_copy


def emergency_pause(tasks: list[dict], task_id: int, pause_until: str) -> list[dict]:
    """Inserts a break block from now until pause_until, recalculates remaining schedule."""
    # Placeholder for full recalc
    tasks_copy = [dict(t) for t in tasks]
    # In a full impl, we'd slice tasks into "done" and "todo", inject break, re-run auto-schedule.
    return tasks_copy


def calculate_productivity_score(tasks: list[dict]) -> tuple[float, int, int]:
    """Returns (score_pct, completed_minutes, planned_minutes). Score = completed/planned * 100."""
    completed = 0
    planned = 0
    
    def time_to_mins(t_str):
        h, m = map(int, t_str.split(':'))
        return h * 60 + m
        
    for t in tasks:
        if t.get('is_break'):
            continue
            
        dur = t.get('duration')
        if not dur and t.get('scheduled_start') and t.get('scheduled_end'):
            dur = time_to_mins(t['scheduled_end']) - time_to_mins(t['scheduled_start'])
            if dur < 0: dur += 24*60
            
        if dur:
            planned += dur
            if t.get('status') == 'completed':
                completed += dur
                
    score = (completed / planned * 100) if planned > 0 else 0.0
    return (score, completed, planned)


def get_reminders(tasks: list[dict], wake_time: str, sleep_time: str, tz: str) -> list[dict]:
    """Returns list of reminder dicts: {type: 'morning'/'pre_task'/'review', time: HH:MM, task_id: int|None, message: str}."""
    reminders = []
    
    def time_to_mins(t_str):
        if not t_str: return 0
        h, m = map(int, t_str.split(':'))
        return h * 60 + m
        
    def mins_to_time(mins):
        h = (mins // 60) % 24
        m = mins % 60
        return f"{h:02d}:{m:02d}"

    # Morning
    reminders.append({
        'type': 'morning',
        'time': wake_time,
        'task_id': None,
        'message': 'صبح بخیر! برنامه امروزت رو چک کن.'
    })
    
    # Pre-task (5 mins before)
    for t in tasks:
        if t.get('scheduled_start') and not t.get('is_break'):
            start_mins = time_to_mins(t['scheduled_start'])
            reminders.append({
                'type': 'pre_task',
                'time': mins_to_time(start_mins - 5),
                'task_id': t.get('id'),
                'message': f"۵ دقیقه دیگه نوبت: {t.get('name')} {t.get('emoji', '')}"
            })
            
    # Review
    sleep_mins = time_to_mins(sleep_time)
    reminders.append({
        'type': 'review',
        'time': mins_to_time(sleep_mins - PRE_SLEEP_BUFFER),
        'task_id': None,
        'message': 'وقت مرور کارهای امروزه!'
    })
    
    return reminders
