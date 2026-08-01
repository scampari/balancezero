
import os
from functools import wraps

from flask import Flask, abort, jsonify, request, session
from flask_migrate import Migrate
from werkzeug.security import check_password_hash

from models import User, db

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "balancezero.db")
)

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)
migrate = Migrate(app, db)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            abort(401)
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return "BalanceZero — scaffolding only, nothing built yet."


@app.route("/login", methods=["POST"])
def login():
    user = User.query.filter_by(username=request.form["username"]).first()
    if user is None or not check_password_hash(user.password_hash, request.form["password"]):
        abort(401)
    session["user_id"] = user.id
    return jsonify(logged_in_as=user.username)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(logged_out=True)


@app.route("/dashboard")
@login_required
def dashboard():
    user = db.session.get(User, session["user_id"])
    return jsonify(username=user.username, is_demo=user.is_demo)


if __name__ == "__main__":
    app.run(port=5002, debug=True)
