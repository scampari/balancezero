import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate

# Load a project-root .env before reading os.environ below. Only fills vars
# that aren't already set, so an explicit `export` (dev.sh, CI, k8s Secret)
# still wins. .env is gitignored — it's where local/prod secrets live.
load_dotenv()

from accounts_api import accounts_bp
from auth_api import auth_bp, register_jwt_error_handlers
from budget_api import budget_bp
from models import db
from plaid_api import plaid_bp
from transactions_api import transactions_bp

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "balancezero.db")
)
app.config["JWT_SECRET_KEY"] = app.secret_key
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
# No defaults on purpose — these protect/authenticate real bank-access credentials.
app.config["PLAID_ENCRYPTION_KEY"] = os.environ["PLAID_ENCRYPTION_KEY"]
app.config["PLAID_CLIENT_ID"] = os.environ["PLAID_CLIENT_ID"]
app.config["PLAID_SECRET"] = os.environ["PLAID_SECRET"]
# Safe to default (unlike the secrets above) — "sandbox" is the conservative
# choice, and this slice's tests/contract only cover Sandbox. Set to
# "production" explicitly once real bank linking goes live.
app.config["PLAID_ENV"] = os.environ.get("PLAID_ENV", "sandbox")
# Required only for linking OAuth institutions (Chase, BofA, ...), which
# redirect the browser back to the app mid-Link-flow. Must match, exactly
# and minus query string, an "Allowed redirect URI" registered in the Plaid
# dashboard (Team Settings → API). Unset = non-OAuth / Sandbox linking,
# which completes entirely inside the Link widget with no redirect.
# Prod value: https://balancezero.<tailnet>.ts.net/accounts
app.config["PLAID_REDIRECT_URI"] = os.environ.get("PLAID_REDIRECT_URI")
# Origin allowed to make credentialed cross-origin requests to /api/* (the React dev
# server, and later the deployed frontend). Also used by auth_api's CSRF origin check.
app.config["ALLOWED_ORIGIN"] = os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173")
# Number of trusted reverse proxies in front of the app. Behind the
# k3s/Tailscale ingress the auth rate limiter would otherwise key every
# request to the ingress pod's IP. Default 0 = no proxy (local dev, tests):
# request.remote_addr is the direct peer, unchanged from before.
app.config["TRUSTED_PROXY_COUNT"] = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))

os.makedirs(app.instance_path, exist_ok=True)
if app.config["TRUSTED_PROXY_COUNT"] > 0:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config["TRUSTED_PROXY_COUNT"])
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
app.register_blueprint(transactions_bp)
app.register_blueprint(plaid_bp)
app.register_blueprint(accounts_bp)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(port=5002, debug=debug)
