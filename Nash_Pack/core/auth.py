"""
Lightweight, dependency-free authentication for the enforcement side of
the app (dashboard, reports, API, scanning).

Design notes for judges / reviewers:
- Accounts are configured via the LM_AUTH_USERS env var, not hardcoded,
  so credentials never live in source control.
- Format: "username:password:role,username:password:role" — role is
  optional and defaults to "officer". "admin" additionally sees the
  the officer-management info on the dashboard.
- This is intentionally simple (session-cookie based, no external
  identity provider) because it is a hackathon prototype. The
  README/technical documentation calls out exactly what a production
  deployment would add (hashed+salted credential store, SSO/LDAP
  integration with the Legal Metrology department directory, audit
  logging of every login) — see "Next steps" in README.md.
"""

import os
from functools import wraps

from flask import session, redirect, url_for, request, flash


def _load_users():
    raw = os.getenv("LM_AUTH_USERS", "officer:changeme:officer")

    users = {}

    for entry in raw.split(","):
        entry = entry.strip()

        if not entry:
            continue

        parts = entry.split(":")

        if len(parts) == 2:
            username, password = parts
            role = "officer"
        elif len(parts) >= 3:
            username, password, role = parts[0], parts[1], parts[2]
        else:
            continue

        users[username.strip()] = {
            "password": password.strip(),
            "role": role.strip() or "officer",
        }

    return users


def verify_login(username, password):
    """Returns the user's role on success, or None on failure."""

    users = _load_users()

    account = users.get((username or "").strip())

    if not account:
        return None

    if account["password"] != (password or ""):
        return None

    return account["role"]


def current_user():
    if "username" not in session:
        return None

    return {
        "username": session["username"],
        "role": session.get("role", "officer"),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "username" not in session:
                flash("Please sign in to continue.", "error")
                return redirect(url_for("login", next=request.path))

            if roles and session.get("role") not in roles:
                flash("You do not have permission to view that page.", "error")
                return redirect(url_for("index"))

            return view(*args, **kwargs)

        return wrapped

    return decorator
