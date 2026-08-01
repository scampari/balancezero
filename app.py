import os

from flask import Flask
from flask_migrate import Migrate

from models import db

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "balancezero.db")
)

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)
migrate = Migrate(app, db)


@app.route("/")
def index():
    return "BalanceZero — scaffolding only, nothing built yet."


if __name__ == "__main__":
    app.run(port=5002, debug=True)
