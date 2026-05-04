def is_empty(value):
    return value is None or str(value).strip() == "" or str(value).lower() == "none"
