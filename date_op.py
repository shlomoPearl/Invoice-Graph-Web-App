import re
from datetime import datetime


_MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def validate_day_by_month(day: int, month: int) -> bool:
    if month == 2:
        return 1 <= day <= 29  # Allowing for leap years
    elif month in {4, 6, 9, 11}:
        return 1 <= day <= 30
    else:
        return 1 <= day <= 31

def validate_month(month: int) -> bool:
    return 1 <= month <= 12

def validate_year(year: int) -> bool:
    return 1970 <= year <= 2100

def build_result(month: int, year: int, day: int | None = None) -> str:
    if not (validate_year(year) and validate_month(month) and (day is None or validate_day_by_month(day, month))):
        print(f"Invalid date components - Year: {year}, Month: {month}, Day: {day}")
        return None
    return f"{month:02d}/{year}"

def date_in_range(date_str: str, start_date: str, end_date: str) -> bool:
    try:
        date_obj = datetime.strptime(date_str, '%m/%Y')
        start_obj = datetime.strptime(start_date, '%m/%Y')
        end_obj = datetime.strptime(end_date, '%m/%Y')
        return start_obj <= date_obj <= end_obj
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        return False

def parse_date(date_str: str) -> str | None:
    """
    Parse a date string and return it in the format 'mm/yyyy'.
    Supports the following formats:
    -'Month Year'
    -'yyyy/mm/dd'
    -'mm/dd/yyyy'
    -'mm/yyyy'.
    -'mm/yy'
    Returns None if the date cannot be parsed.
    """
    print(f"Parsing date string: {date_str}")
    date_str = date_str.lower().strip()
    # Check for 'Month Year' or Month-Year or Month/Year format
    month_year_match = re.search(r'([a-zA-Z]+)[\s\-\/]+(\d{4})', date_str) 
    print(f"Month-Year match: {month_year_match}", f"Date string: {date_str}")
    if month_year_match:
        month_name, year = month_year_match.groups()
        month_num = _MONTH_NAMES.get(month_name.lower())
        if month_num:
            print(f"Format 'Month Year', extracted month: {month_num}, year: {year}")
            return build_result(month_num, int(year))
    # Check for 'yyyy/mm/dd' or 'yyyy-mm-dd' format
    ymd_match = re.fullmatch(r'(\d{4})[\-\/](\d{1,2})[\-\/](\d{1,2})', date_str)
    if ymd_match:       
        year, month, day = ymd_match.groups()
        print(f"Format 'yyyy/mm/dd', extracted month: {month}, year: {year}")
        return build_result(int(month), int(year), int(day))
    # Check for 'dd/mm/yyyy' or 'dd-mm-yyyy' or 'mm/dd/yyyy' or 'mm-dd-yyyy' format with priority to 'dd/mm/yyyy'
    mdy_match = re.fullmatch(r'(\d{1,2})[\-\/](\d{1,2})[\-\/](\d{4})', date_str)
    if mdy_match:
        month, day, year = mdy_match.groups()
        print(f"Format 'mm/dd/yyyy', extracted month: {month}, year: {year}")
        return build_result(int(day), int(year), int(month)) or build_result(int(month), int(year), int(day))
    # Check for 'dd/mm/yy' or 'dd-mm-yy' or 'mm/dd/yy' or 'mm-dd-yy' format with priority to 'dd/mm/yy'
    mdy_short_match = re.fullmatch(r'(\d{1,2})[\-\/](\d{1,2})[\-\/](\d{2})', date_str)
    if mdy_short_match:
        month, day, year = mdy_short_match.groups()
        year_full = f"20{year}"  # Assuming 21st century for two-digit years
        print(f"Format 'mm/dd/yy', extracted month: {month}, year: {year_full}")
        return build_result(int(day), int(year_full), int(month)) or build_result(int(month), int(year_full), int(day))   
    # Check for 'mm/yy' or 'mm-yy' format
    my_short_match = re.fullmatch(r'(\d{1,2})[\-\/](\d{2})', date_str)
    if my_short_match:
        month, year = my_short_match.groups()
        year_full = f"20{year}"  # Assuming 21st century for two-digit years
        print(f"Format 'mm/yy', extracted month: {month}, year: {year_full}")
        if build_result(int(month), int(year_full)):
            return build_result(int(month), int(year_full))
        # Check for yy/mm or yy-mm format if the previous format was not valid
        ym_short_match = re.fullmatch(r'(\d{2})[\-\/](\d{1,2})', date_str)
        if ym_short_match:
            year, month = ym_short_match.groups()
            year_full = f"20{year}"  # Assuming 21st century for two-digit years
            print(f"Format 'yy/mm', extracted month: {month}, year: {year_full}")
            return build_result(int(month), int(year_full))
    # Check for 'mm/yyyy' or 'mm-yyyy' format
    my_match = re.fullmatch(r'(\d{1,2})[\-\/](\d{4})', date_str)
    if my_match:
        month, year = my_match.groups()
        print(f"Format 'mm/yyyy', extracted month: {month}, year: {year}")
        return build_result(int(month), int(year))
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
    month_name = date_list[1]
    month_num = _MONTH_NAMES.get(month_name.lower(), 0) - 1
    year = date_list[2]
    year_num = int(year)
    if month_num == 0:
        month_num = 12
        year_num -= 1
    return f"{month_num:02d}/{year_num}"

def get_date(date_list):
    for i, part in enumerate(date_list):
        if _MONTH_NAMES.get(part.lower()):
            month_name = part
            month_num = _MONTH_NAMES[month_name.lower()]
            if i + 1 < len(date_list):
                year = date_list[i + 1]
                year_num = int(year)
                return f"{month_num:02d}/{year_num}"
    return None

print(parse_date("31/02/2024"))  # This will print None because February 31st is not a valid date.
print(parse_date("31/04/2023"))  # This will print None because April has only 30 days.