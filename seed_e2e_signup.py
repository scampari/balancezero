"""Seeds one known, unused invite code for frontend/e2e/signup.spec.ts, and
clears any account left behind by a previous run so the spec can create it
fresh.

Additive: touches only the e2e signup user and the e2e invite codes. Run
only by that spec's beforeAll."""

from app import app
from models import InviteCode, User, db

E2E_INVITE_CODE = "E2E-INVITE-CODE"
E2E_SIGNUP_USERNAME = "e2e-signup-user"

with app.app_context():
    # Fresh, unused code every run — drop any prior e2e code first so a
    # half-completed previous run can't leave a "used" one behind.
    InviteCode.query.filter(InviteCode.code.like("E2E-%")).delete(synchronize_session=False)
    db.session.add(InviteCode(code=E2E_INVITE_CODE))

    leftover = User.query.filter_by(username=E2E_SIGNUP_USERNAME).first()
    if leftover is not None:
        db.session.delete(leftover)

    db.session.commit()
    print(f"Seeded e2e invite code {E2E_INVITE_CODE!r}; cleared any leftover {E2E_SIGNUP_USERNAME!r}.")
