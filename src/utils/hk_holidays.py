from datetime import date, time, datetime
from typing import List, Dict
from src.models.user_model import WorkType
import holidays


def get_hk_bank_holidays_with_sunday(year: int, month: int, day: int) -> List[date]:
    hk_holidays = holidays.HK(years=[year])
    bank_holidays = list(hk_holidays.keys())
    
    # Add all bank holidays
    bank_holidays_with_sunday = bank_holidays.copy()
    
    # Add all Sundays of the year
    for month_num in range(1, 13):
        for day_num in range(1, 32):
            try:
                current_date = date(year, month_num, day_num)
                if current_date.weekday() == 6:  # Sunday
                    bank_holidays_with_sunday.append(current_date)
            except ValueError:
                # Invalid date (e.g., Feb 30)
                continue
    
    return sorted(set(bank_holidays_with_sunday))


def get_hk_labour_holidays_with_sunday(year: int, month: int, day: int) -> List[date]:
    hk_labour_holidays = []

    # 1. The first day of January
    hk_labour_holidays.append(date(year, 1, 1))

    # 2. Lunar New Year holidays (first, second, third days)
    hk_lny = holidays.HK(years=[year])
    for d, name in hk_lny.items():
        if "Lunar New Year" in name:
            hk_labour_holidays.append(d)

    # 3. Ching Ming Festival
    for d, name in hk_lny.items():
        if "Ching Ming Festival" in name:
            hk_labour_holidays.append(d)

    # 4. Labour Day
    hk_labour_holidays.append(date(year, 5, 1))

    # 5. Tuen Ng Festival (Dragon Boat Festival)
    for d, name in hk_lny.items():
        if "Tuen Ng Festival" in name:
            hk_labour_holidays.append(d)

    # 6. Hong Kong Special Administrative Region Establishment Day
    hk_labour_holidays.append(date(year, 7, 1))

    # 7. National Day
    hk_labour_holidays.append(date(year, 10, 1))

    # 8. Chinese Mid-Autumn Festival (the day after)
    for d, name in hk_lny.items():
        if "Day after Mid-Autumn Festival" in name:
            hk_labour_holidays.append(d)

    # 9. Chung Yeung Festival
    for d, name in hk_lny.items():
        if "Chung Yeung Festival" in name:
            hk_labour_holidays.append(d)

    # Add all Sundays of the year
    for month_num in range(1, 13):
        for day_num in range(1, 32):
            try:
                current_date = date(year, month_num, day_num)
                if current_date.weekday() == 6:  # Sunday
                    hk_labour_holidays.append(current_date)
            except ValueError:
                # Invalid date (e.g., Feb 30)
                continue

    # Remove duplicates and sort
    hk_labour_holidays = sorted(set(hk_labour_holidays))

    return hk_labour_holidays


def is_holiday_with_sunday(year: int, month: int, day: int, work_type: WorkType) -> bool:
    if work_type in [WorkType.office_ft, WorkType.office_pt]:
        return date(year, month, day) in get_hk_bank_holidays_with_sunday(year, month, day)
    elif work_type in [WorkType.wh, WorkType.site]:
        return date(year, month, day) in get_hk_labour_holidays_with_sunday(year, month, day)
    else:
        return False

