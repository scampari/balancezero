import os
from datetime import timedelta

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate

from auth_api import auth_bp, register_jwt_error_handlers
from budget_api import budget_bp
from models import db

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "balancezero.db")
)
app.config["JWT_SECRET_KEY"] = app.secret_key
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
# Origin allowed to make credentialed cross-origin requests to /api/* (the React dev
# server, and later the deployed frontend). Also used by auth_api's CSRF origin check.
app.config["ALLOWED_ORIGIN"] = os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173")

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)
register_jwt_error_handlers(jwt)
CORS(
    app,
    resources={r"/api/*": {"origins": app.config["ALLOWED_ORIGIN"]}},
    supports_credentials=True,
)

app.register_blueprint(auth_bp)
app.register_blueprint(budget_bp)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(port=5002, debug=debug)
