from datetime import datetime
import pytz


HK_TZ = pytz.timezone("Asia/Hong_Kong")
UTC_TZ = pytz.timezone("UTC")

def get_this_day():
    """Get current date in Hong Kong timezone"""
    return datetime.now(HK_TZ).date()

def get_this_moment():
    """Get current datetime in Hong Kong timezone"""
    return datetime.now(HK_TZ)

# For backward compatibility
this_day = get_this_day()
this_moment = get_this_moment()
