import sys
sys.path.append('C:\\Users\\User\\Desktop\\telegram-assistant')
from visual_engine import generate_daily_poster, generate_weekly_grid
import datetime

tasks = [
    {'task_name': 'ورزش صبحگاهی', 'estimated_minutes': 30, 'scheduled_start': '07:00', 'scheduled_end': '07:30', 'emoji': '🏃‍♂️'},
    {'is_break': True, 'task_name': 'استراحت / صبحانه', 'estimated_minutes': 15, 'scheduled_start': '07:30', 'scheduled_end': '07:45'},
    {'task_name': 'کدنویسی و توسعه', 'estimated_minutes': 90, 'scheduled_start': '07:45', 'scheduled_end': '09:15', 'emoji': '💻'},
    {'task_name': 'کلاس دانشگاه', 'estimated_minutes': 120, 'scheduled_start': '10:00', 'scheduled_end': '12:00', 'emoji': '🏛️'},
]

weekly = {
    0: tasks,
    1: tasks,
    2: tasks
}

daily_bytes = generate_daily_poster(tasks, 'ابوالفضل', '۱۴۰۲/۰۷/۱۵', '06:00', '23:30', streak=12)
with open('test_daily.png', 'wb') as f:
    f.write(daily_bytes)

weekly_bytes = generate_weekly_grid(weekly, 'ابوالفضل')
with open('test_weekly.png', 'wb') as f:
    f.write(weekly_bytes)

print('Posters generated successfully.')
