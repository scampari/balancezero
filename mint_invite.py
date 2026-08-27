"""Mint a single-use signup invite code.

    python3 mint_invite.py               # never expires
    python3 mint_invite.py --expires-days 7

Prints the code to stdout. There is deliberately no HTTP endpoint that
creates codes — the operator runs this. See spec/signup.md.
"""

import argparse
import secrets
from datetime import datetime, timedelta

from app import app
from models import InviteCode, db


def main():
    parser = argparse.ArgumentParser(description="Mint a single-use signup invite code.")
    parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        help="days until the code expires (default: never expires)",
    )
    args = parser.parse_args()

    code = secrets.token_urlsafe(12)
    expires_at = (
        datetime.utcnow() + timedelta(days=args.expires_days)
        if args.expires_days is not None
        else None
    )

    with app.app_context():
        db.session.add(InviteCode(code=code, expires_at=expires_at))
        db.session.commit()

    when = f"expires {expires_at.date().isoformat()}" if expires_at else "never expires"
    print(f"{code}  ({when})")


if __name__ == "__main__":
    main()
