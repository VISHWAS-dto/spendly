"""
Tests for Step 7: Add Expense (GET/POST /expenses/add).

Spec: .claude/specs/07-add-expense.md

These tests exercise `GET/POST /expenses/add` through Flask's test client
only, using an isolated temp SQLite database (never the shared dev
`spendly.db`). Test logic is derived strictly from the spec's stated
behaviour (routes, validation rules, response codes, redirect targets, DB
side effects) — not by reading `app.py`'s implementation and reverse
engineering assertions from it. In particular, assertions about error
messages check only that *some* user-visible error text is shown (the spec
does not mandate exact wording), rather than hardcoding the current
implementation's literal strings.

Note: this file is intentionally separate from the pre-existing
`tests/test_add_expense.py` and does not modify or replace it.
"""
import importlib
import sys
from datetime import date

import pytest


# ------------------------------------------------------------------ #
# Fixtures: isolated DB + Flask app/test client                       #
# ------------------------------------------------------------------ #

@pytest.fixture()
def app(tmp_path, monkeypatch):
    """
    Build a fresh Flask app instance backed by a temp SQLite file.

    database.db.DB_PATH is monkeypatched *before* app.py is imported so that
    the module-level `init_db()` / `seed_db()` calls in app.py operate on the
    isolated test database rather than the shared dev spendly.db.
    """
    test_db_path = tmp_path / "test_spendly.db"

    # Drop any previously-imported copies of these modules so the patched
    # DB_PATH is honored when they are (re)imported fresh for this test.
    for mod_name in ("app", "database.queries", "database.db"):
        sys.modules.pop(mod_name, None)

    import database.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))

    import app as app_module
    importlib.reload(app_module)

    # seed_db() inserts a demo user with expenses; wipe it so each test
    # starts from a known, empty dataset.
    conn = db_module.get_db()
    conn.execute("DELETE FROM expenses")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()

    app_module.app.config.update(TESTING=True)

    yield app_module.app

    for mod_name in ("app", "database.queries", "database.db"):
        sys.modules.pop(mod_name, None)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_module(app):
    """Return the (already patched/reloaded) database.db module."""
    import database.db as db_mod
    return db_mod


# ------------------------------------------------------------------ #
# Data helpers                                                        #
# ------------------------------------------------------------------ #

def create_test_user(db_module, name="Test User", email="test@example.com", password="password123"):
    user_id = db_module.create_user(name, email, password)
    return user_id


def login(client, app, user_id=None):
    """Log a user in by setting the session directly (bypasses password form)."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def fetch_expenses_for_user(db_module, user_id):
    conn = db_module.get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


FIXED_CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]

VALID_PAYLOAD = {
    "amount": "50.0",
    "category": "Food",
    "date": "2026-03-20",
    "description": "Lunch",
}


# ------------------------------------------------------------------ #
# Auth guards                                                         #
# ------------------------------------------------------------------ #

def test_get_add_expense_unauthenticated_redirects_to_login(client, app):
    with app.test_request_context():
        from flask import url_for
        add_expense_url = url_for("add_expense")
        login_url = url_for("login")

    resp = client.get(add_expense_url)
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


def test_post_add_expense_unauthenticated_redirects_to_login(client, app, db_module):
    with app.test_request_context():
        from flask import url_for
        add_expense_url = url_for("add_expense")
        login_url = url_for("login")

    resp = client.post(add_expense_url, data=VALID_PAYLOAD)
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]

    # No row should be created as a side effect of an unauthenticated POST.
    conn = db_module.get_db()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM expenses").fetchone()["c"]
    finally:
        conn.close()
    assert count == 0


# ------------------------------------------------------------------ #
# GET authenticated — happy path                                      #
# ------------------------------------------------------------------ #

def test_get_add_expense_authenticated_returns_200(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/expenses/add")
    assert resp.status_code == 200


def test_get_add_expense_authenticated_shows_form_with_post_method(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/expenses/add")
    body = resp.get_data(as_text=True)

    assert "<form" in body
    assert "POST" in body.upper()


def test_get_add_expense_shows_all_seven_categories(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/expenses/add")
    body = resp.get_data(as_text=True)

    for category in FIXED_CATEGORIES:
        assert category in body


# ------------------------------------------------------------------ #
# POST authenticated, valid data — happy path                         #
# ------------------------------------------------------------------ #

def test_post_add_expense_valid_data_redirects_to_profile(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    with app.test_request_context():
        from flask import url_for
        profile_url = url_for("profile")

    resp = client.post("/expenses/add", data=VALID_PAYLOAD)

    assert resp.status_code == 302
    assert profile_url in resp.headers["Location"]


def test_post_add_expense_valid_data_creates_db_row_with_matching_fields(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post("/expenses/add", data=VALID_PAYLOAD)
    assert resp.status_code == 302

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == user_id
    assert row["amount"] == 50.0
    assert row["category"] == "Food"
    assert row["date"] == "2026-03-20"
    assert row["description"] == "Lunch"


def test_post_add_expense_valid_data_increments_expense_count_and_total(client, app, db_module):
    """
    Per the spec's Definition of Done: a valid submission must result in the
    new expense appearing in the user's transaction list / totals.
    """
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    # Baseline: zero expenses for this user before submission.
    assert fetch_expenses_for_user(db_module, user_id) == []

    resp = client.post(
        "/expenses/add",
        data={"amount": "75.25", "category": "Transport", "date": "2026-04-01", "description": "Cab"},
    )
    assert resp.status_code == 302

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 75.25

    # A second valid submission increments the count further and the sum
    # of amounts reflects both rows.
    resp2 = client.post(
        "/expenses/add",
        data={"amount": "24.75", "category": "Food", "date": "2026-04-02", "description": ""},
    )
    assert resp2.status_code == 302

    rows_after = fetch_expenses_for_user(db_module, user_id)
    assert len(rows_after) == 2
    total = sum(r["amount"] for r in rows_after)
    assert total == pytest.approx(100.0)


def test_post_add_expense_valid_data_appears_on_profile_page(client, app, db_module):
    """Per spec DoD: 'the new expense appears in the transaction list' on /profile."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "33.00", "category": "Entertainment", "date": "2026-05-05", "description": "Concert"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Concert" in body


# ------------------------------------------------------------------ #
# POST authenticated — invalid / missing amount                       #
# ------------------------------------------------------------------ #

def test_post_add_expense_missing_amount_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    # Some user-visible error indication is present (spec doesn't mandate exact wording).
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_zero_amount_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "0", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_negative_amount_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "-10", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_non_numeric_amount_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "not-a-number", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


# ------------------------------------------------------------------ #
# POST authenticated — invalid category                               #
# ------------------------------------------------------------------ #

def test_post_add_expense_invalid_category_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "NotARealCategory", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_missing_category_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


# ------------------------------------------------------------------ #
# POST authenticated — invalid date                                   #
# ------------------------------------------------------------------ #

def test_post_add_expense_invalid_date_string_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "Food", "date": "not-a-date", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_missing_date_rerenders_form_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "Food", "date": "", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_malformed_date_format_rerenders_form_with_error(client, app, db_module):
    """Spec requires strict YYYY-MM-DD parsing via datetime.strptime — a
    differently-formatted but plausible date string must be rejected."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "Food", "date": "20-03-2026", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<form" in body
    assert "error" in body.lower() or "invalid" in body.lower() or "valid" in body.lower()
    assert fetch_expenses_for_user(db_module, user_id) == []


# ------------------------------------------------------------------ #
# Validation errors must re-populate previously submitted values       #
# ------------------------------------------------------------------ #

def test_validation_error_repopulates_previously_submitted_values(client, app, db_module):
    """Spec: 'On any validation error, re-render the form with the error
    message and the previously submitted values pre-filled.'"""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={
            "amount": "not-a-number",
            "category": "Health",
            "date": "2026-05-05",
            "description": "Doctor visit",
        },
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-05-05" in body
    assert "Doctor visit" in body


# ------------------------------------------------------------------ #
# POST authenticated — description optional / blank -> NULL            #
# ------------------------------------------------------------------ #

def test_post_add_expense_no_description_redirects_and_stores_null(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    with app.test_request_context():
        from flask import url_for
        profile_url = url_for("profile")

    resp = client.post(
        "/expenses/add",
        data={"amount": "15", "category": "Bills", "date": "2026-04-01", "description": ""},
    )

    assert resp.status_code == 302
    assert profile_url in resp.headers["Location"]

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["description"] is None


def test_post_add_expense_whitespace_only_description_stores_null(client, app, db_module):
    """Spec: description is stripped of whitespace; blank -> NULL."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "15", "category": "Bills", "date": "2026-04-01", "description": "   "},
    )

    assert resp.status_code == 302

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["description"] is None


def test_post_add_expense_missing_description_field_entirely_stores_null(client, app, db_module):
    """The description field is optional per spec; omitting it from the
    POST body entirely must not error and must store NULL."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "15", "category": "Bills", "date": "2026-04-01"},
    )

    assert resp.status_code == 302

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["description"] is None


def test_post_add_expense_with_description_stores_stripped_value(client, app, db_module):
    """A non-blank description with surrounding whitespace is stripped before storage."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "15", "category": "Bills", "date": "2026-04-01", "description": "  Rent  "},
    )

    assert resp.status_code == 302

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["description"] == "Rent"
