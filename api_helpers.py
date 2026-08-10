from datetime import date

from flask_jwt_extended import get_jwt_identity


def current_user_id():
    return int(get_jwt_identity())


def parse_month(raw_month):
    try:
        return date.fromisoformat(raw_month)
    except (TypeError, ValueError):
        return None
