import re
from datetime import datetime


_MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}
_SHORT_MONTH_NAMES = {name[:3]: num for name, num in _MONTH_NAMES.items() if len(name) > 3}


def parse_date(date_str: str) -> str | None:
    """
    Parse a date string and return it in the format:
    -'Month Year'
    -'yyyy/mm/dd'
    -'mm/dd/yyyy'
    -'mm/yyyy'.
    -'mm/yy'
    Returns None if the date cannot be parsed.
    """
    date_str = date_str.lower().strip()
    # Check for 'Month Year' format
    for month_name, month_num in _MONTH_NAMES.items():  
        if month_name in date_str:
            year_match = re.search(r'\b(\d{4})\b', date_str)
            if year_match:
                year = year_match.group(1)
                return f"{month_num:02d}/{year}"        
    # Check for 'yyyy/mm/dd' format
    match = re.match(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', date_str)
    if match:
        year, month, day = match.groups()
        return f"{int(month):02d}/{year}"    
    # Check for 'mm/dd/yyyy' format
    match = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', date_str)
    if match:       
        month, day, year = match.groups()
        return f"{int(month):02d}/{year}"
    # Check for 'mm/yyyy' format
    match = re.match(r'(\d{1,2})[/-](\d{4})', date_str)
    if match:
        month, year = match.groups()
        return f"{int(month):02d}/{year}"   
    # Check for 'mm/yy' format
    match = re.match(r'(\d{1,2})[/-](\d{2})', date_str)
    if match:
        month, year = match.groups()
        return f"{int(month):02d}/{year}"
    return None

# Convert date from dd/mm/yyyy format to yyyy/mm/dd format with month +1
def increment_date(date_str):
    date_obj = datetime.strptime(date_str, '%d/%m/%Y')
    month = date_obj.month + 1
    year = date_obj.year
    day = date_obj.day
    if month > 12:
        month = 1
        year += 1
    return f"{year:04d}/{month:02d}/{day:02d}"

# Extract date from list format and return as mm/yyyy with month -1
def decrement_date(date_list):
    month_name = date_list[2]
    month_num = _MONTH_NAMES.get(month_name.lower(), 0) - 1
    year = date_list[3]
    year_num = int(year)
    if month_num < 1:
        month_num = 12
        year_num -= 1
    return f"{month_num:02d}/{year_num}"

def get_date(date_list):
    month_name = date_list[2]
    month_num = _MONTH_NAMES.get(month_name.lower(), 0)
    year = date_list[3]
    year_num = int(year)
    return f"{month_num:02d}/{year_num}"