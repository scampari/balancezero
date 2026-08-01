
from werkzeug.security import generate_password_hash

from app import app
from models import User, db

with app.app_context():
    if User.query.filter_by(username="test2").first() is None:
        db.session.add(User(username="test2", password_hash=generate_password_hash("test2-pw"), is_demo=False))
        db.session.commit()
        print("Created test2.")
    else:
        print("test2 already exists.")
