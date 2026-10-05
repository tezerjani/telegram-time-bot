import re

PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
ENGLISH_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

PERSIAN_WORD_NUMBERS = {
    'صفر': 0, 'یک': 1, 'یه': 1, 'دو': 2, 'سه': 3, 'چهار': 4, 'پنج': 5, 'شش': 6, 'هفت': 7, 'هشت': 8, 'نه': 9, 'ده': 10,
    'یازده': 11, 'دوازده': 12, 'سیزده': 13, 'چهارده': 14, 'پانزده': 15, 'شانزده': 16, 'هفده': 17, 'هجده': 18, 'نوزده': 19,
    'بیست': 20, 'سی': 30, 'چهل': 40, 'پنجاه': 50, 'شصت': 60
}

def parse_duration_to_minutes(text: str) -> int | None:
    text = text.translate(PERSIAN_DIGITS).strip().lower()
    
    # Preprocess text to ensure spaces around keywords
    text = re.sub(r'(ساعت|دقیقه|min|minutes|m|hour|hours|h)', r' \1 ', text)
    text = ' '.join(text.split())

    # Half hour
    if re.search(r'نیم\s*ساعت', text):
        return 30
    
    # Quarter
    if re.search(r'(یه|یک)\s*ربع', text):
        return 15

    # Decimal hours
    m = re.match(r'^(\d+(?:\.\d+)?)$', text)
    if m:
        val = float(m.group(1))
        # Usually decimal numbers in this context (like 6.5, 1.25) mean hours
        if val < 24 and '.' in text:
            return int(val * 60)
        
    # HH:MM format
    m = re.match(r'^(\d+):(\d{2})$', text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    # Persian compound word format like "یک ساعت و نیم"
    m = re.match(r'^(.*?)\s*ساعت\s*و\s*(.*?)$', text)
    if m:
        hours_str = m.group(1).strip()
        minutes_str = m.group(2).strip()
        
        hours = 0
        if hours_str in PERSIAN_WORD_NUMBERS:
            hours = PERSIAN_WORD_NUMBERS[hours_str]
        elif hours_str.isdigit():
            hours = int(hours_str)
        
        minutes = 0
        if minutes_str == 'نیم':
            minutes = 30
        elif minutes_str == 'ربع':
            minutes = 15
        elif minutes_str in PERSIAN_WORD_NUMBERS:
            minutes = PERSIAN_WORD_NUMBERS[minutes_str]
        elif minutes_str.isdigit():
            minutes = int(minutes_str)
            
        if hours > 0 or minutes > 0:
            return hours * 60 + minutes

    # Extract all hour/minute combinations
    total_minutes = 0
    matched = False
    
    # Check for hours
    m_hours = re.search(r'(\d+|\w+)\s+(ساعت|hour|hours|h)\b', text)
    if m_hours:
        val_str = m_hours.group(1)
        if val_str in PERSIAN_WORD_NUMBERS:
            total_minutes += PERSIAN_WORD_NUMBERS[val_str] * 60
        elif val_str.isdigit():
            total_minutes += int(val_str) * 60
        matched = True
        
    # Check for minutes
    m_minutes = re.search(r'(\d+|\w+)\s+(دقیقه|min|minutes|m)\b', text)
    if m_minutes:
        val_str = m_minutes.group(1)
        if val_str in PERSIAN_WORD_NUMBERS:
            total_minutes += PERSIAN_WORD_NUMBERS[val_str]
        elif val_str.isdigit():
            total_minutes += int(val_str)
        matched = True

    if matched:
        return total_minutes
            
    return None

def format_duration(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} ساعت")
    if mins > 0:
        parts.append(f"{mins} دقیقه")
        
    result = " و ".join(parts)
    if not result:
        result = "0 دقیقه"
        
    return result.translate(ENGLISH_DIGITS)
