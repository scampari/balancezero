
import getpass

from werkzeug.security import generate_password_hash

from app import app
from models import User, db

with app.app_context():
    username = input("Choose a username for your real account: ")
    password = getpass.getpass("Choose a password (hidden as you type): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords didn't match — nothing saved. Run again.")

    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, is_demo=False)
        db.session.add(user)
    user.password_hash = generate_password_hash(password)
    db.session.commit()
    print(f"Saved. '{username}' (is_demo=False) now has a password hash on file.")
