"""
Tests for Step 7: Add Expense (GET/POST /expenses/add).

These tests exercise the route through Flask's test client only, using an
isolated temp SQLite database (never the shared dev `spendly.db`). They also
include a couple of direct unit tests for the `insert_expense` DB helper in
`database/queries.py`.
"""
import importlib
import sys

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


def login(client, app, email="test@example.com", user_id=None):
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


# ------------------------------------------------------------------ #
# 1. Unit tests for insert_expense                                    #
# ------------------------------------------------------------------ #

def test_insert_expense_valid_row_is_retrievable(app, db_module):
    from database.queries import insert_expense

    user_id = create_test_user(db_module)
    expense_id = insert_expense(user_id, 42.50, "Food", "2026-03-15", "Groceries")

    assert expense_id is not None

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == user_id
    assert row["amount"] == 42.50
    assert row["category"] == "Food"
    assert row["date"] == "2026-03-15"
    assert row["description"] == "Groceries"


def test_insert_expense_description_none_stores_null(app, db_module):
    from database.queries import insert_expense

    user_id = create_test_user(db_module)
    insert_expense(user_id, 10.0, "Transport", "2026-01-01", None)

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["description"] is None


# ------------------------------------------------------------------ #
# 2 & 4. Auth guard for GET and POST                                  #
# ------------------------------------------------------------------ #

def test_get_add_expense_requires_login(client, app):
    with app.test_request_context():
        from flask import url_for
        add_expense_url = url_for("add_expense")
        login_url = url_for("login")

    resp = client.get(add_expense_url)
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


def test_post_add_expense_requires_login(client, app):
    with app.test_request_context():
        from flask import url_for
        add_expense_url = url_for("add_expense")
        login_url = url_for("login")

    resp = client.post(
        add_expense_url,
        data={"amount": "10", "category": "Food", "date": "2026-01-01", "description": ""},
    )
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


# ------------------------------------------------------------------ #
# 3. GET authenticated                                                #
# ------------------------------------------------------------------ #

def test_get_add_expense_authenticated_renders_form(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/expenses/add")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "<form" in body
    assert 'method="POST"' in body

    assert '<select id="category" name="category"' in body
    for category in ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]:
        assert f'>{category}</option>' in body or f'value="{category}"' in body


# ------------------------------------------------------------------ #
# 5. POST valid data -> redirect + row inserted                       #
# ------------------------------------------------------------------ #

def test_post_add_expense_valid_data_redirects_and_inserts(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    with app.test_request_context():
        from flask import url_for
        profile_url = url_for("profile")

    resp = client.post(
        "/expenses/add",
        data={
            "amount": "25.75",
            "category": "Food",
            "date": "2026-03-15",
            "description": "Lunch",
        },
    )

    assert resp.status_code == 302
    assert profile_url in resp.headers["Location"]

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 25.75
    assert rows[0]["category"] == "Food"
    assert rows[0]["date"] == "2026-03-15"
    assert rows[0]["description"] == "Lunch"


# ------------------------------------------------------------------ #
# 6. POST invalid amount (missing / zero / non-numeric)               #
# ------------------------------------------------------------------ #

def test_post_add_expense_missing_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_zero_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "0", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_non_numeric_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "not-a-number", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_negative_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "-5", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


# ------------------------------------------------------------------ #
# 7. POST invalid category                                            #
# ------------------------------------------------------------------ #

def test_post_add_expense_invalid_category_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "NotACategory", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Select a valid category." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_missing_category_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Select a valid category." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


# ------------------------------------------------------------------ #
# 8. POST invalid date                                                #
# ------------------------------------------------------------------ #

def test_post_add_expense_invalid_date_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "Food", "date": "not-a-date", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid date." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


def test_post_add_expense_missing_date_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "Food", "date": "", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid date." in body
    assert fetch_expenses_for_user(db_module, user_id) == []


# ------------------------------------------------------------------ #
# 9. POST no description -> stored as NULL                            #
# ------------------------------------------------------------------ #

def test_post_add_expense_no_description_stores_null(client, app, db_module):
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


# ------------------------------------------------------------------ #
# Form value retention on validation failure                          #
# ------------------------------------------------------------------ #

def test_post_add_expense_invalid_amount_retains_other_field_values(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.post(
        "/expenses/add",
        data={
            "amount": "abc",
            "category": "Health",
            "date": "2026-05-05",
            "description": "Doctor visit",
        },
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'value="2026-05-05"' in body
    assert 'value="Doctor visit"' in body
    assert 'selected' in body
