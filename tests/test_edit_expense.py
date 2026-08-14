"""
Tests for Step 8: Edit Expense (GET/POST /expenses/<id>/edit).

These tests exercise the route through Flask's test client only, using an
isolated temp SQLite database (never the shared dev `spendly.db`). They also
include direct unit tests for the `get_expense_by_id` and `update_expense`
DB helpers in `database/queries.py`.
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

    for mod_name in ("app", "database.queries", "database.db"):
        sys.modules.pop(mod_name, None)

    import database.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))

    import app as app_module
    importlib.reload(app_module)

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


def seed_expense(db_module, user_id, amount=50.0, category="Food",
                  expense_date="2026-01-10", description="Original desc"):
    from database.queries import insert_expense
    return insert_expense(user_id, amount, category, expense_date, description)


# ------------------------------------------------------------------ #
# 1. Unit tests for get_expense_by_id                                 #
# ------------------------------------------------------------------ #

def test_get_expense_by_id_returns_row_for_owner(app, db_module):
    from database.queries import get_expense_by_id

    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)

    row = get_expense_by_id(expense_id, user_id)
    assert row is not None
    assert row["id"] == expense_id
    assert row["amount"] == 50.0
    assert row["category"] == "Food"
    assert row["date"] == "2026-01-10"
    assert row["description"] == "Original desc"


def test_get_expense_by_id_returns_none_for_wrong_user(app, db_module):
    from database.queries import get_expense_by_id

    owner_id = create_test_user(db_module, email="owner@example.com")
    other_id = create_test_user(db_module, email="other@example.com")
    expense_id = seed_expense(db_module, owner_id)

    assert get_expense_by_id(expense_id, other_id) is None


def test_get_expense_by_id_returns_none_for_nonexistent_id(app, db_module):
    from database.queries import get_expense_by_id

    user_id = create_test_user(db_module)
    assert get_expense_by_id(999999, user_id) is None


# ------------------------------------------------------------------ #
# 2. Unit tests for update_expense                                    #
# ------------------------------------------------------------------ #

def test_update_expense_updates_row_for_owner(app, db_module):
    from database.queries import update_expense

    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)

    update_expense(expense_id, user_id, 99.0, "Bills", "2026-02-01", "Updated")

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 99.0
    assert rows[0]["category"] == "Bills"
    assert rows[0]["date"] == "2026-02-01"
    assert rows[0]["description"] == "Updated"


def test_update_expense_wrong_user_does_not_modify_row(app, db_module):
    from database.queries import update_expense

    owner_id = create_test_user(db_module, email="owner@example.com")
    other_id = create_test_user(db_module, email="other@example.com")
    expense_id = seed_expense(db_module, owner_id)

    update_expense(expense_id, other_id, 99.0, "Bills", "2026-02-01", "Hacked")

    rows = fetch_expenses_for_user(db_module, owner_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 50.0
    assert rows[0]["category"] == "Food"
    assert rows[0]["date"] == "2026-01-10"
    assert rows[0]["description"] == "Original desc"


# ------------------------------------------------------------------ #
# 3. Auth guard for GET and POST                                      #
# ------------------------------------------------------------------ #

def test_get_edit_expense_requires_login(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)

    with app.test_request_context():
        from flask import url_for
        edit_url = url_for("edit_expense", id=expense_id)
        login_url = url_for("login")

    resp = client.get(edit_url)
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


def test_post_edit_expense_requires_login(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)

    with app.test_request_context():
        from flask import url_for
        edit_url = url_for("edit_expense", id=expense_id)
        login_url = url_for("login")

    resp = client.post(
        edit_url,
        data={"amount": "10", "category": "Food", "date": "2026-01-01", "description": ""},
    )
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


# ------------------------------------------------------------------ #
# 4. GET authenticated                                                #
# ------------------------------------------------------------------ #

def test_get_edit_expense_authenticated_owner_renders_prefilled_form(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id, amount=42.5, category="Health",
                               expense_date="2026-03-20", description="Pharmacy")
    login(client, app, user_id=user_id)

    resp = client.get(f"/expenses/{expense_id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "<form" in body
    assert 'method="POST"' in body
    assert 'value="42.5"' in body
    assert 'value="2026-03-20"' in body
    assert 'value="Pharmacy"' in body
    assert '<option value="Health" selected>' in body


def test_get_edit_expense_other_users_expense_returns_404(client, app, db_module):
    owner_id = create_test_user(db_module, email="owner@example.com")
    other_id = create_test_user(db_module, email="other@example.com")
    expense_id = seed_expense(db_module, owner_id)

    login(client, app, user_id=other_id)

    resp = client.get(f"/expenses/{expense_id}/edit")
    assert resp.status_code == 404


def test_get_edit_expense_nonexistent_id_returns_404(client, app, db_module):
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/expenses/999999/edit")
    assert resp.status_code == 404


# ------------------------------------------------------------------ #
# 5. POST valid data -> redirect + row updated                        #
# ------------------------------------------------------------------ #

def test_post_edit_expense_valid_data_redirects_and_updates(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    with app.test_request_context():
        from flask import url_for
        profile_url = url_for("profile")

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={
            "amount": "77.25",
            "category": "Shopping",
            "date": "2026-04-10",
            "description": "New shoes",
        },
    )

    assert resp.status_code == 302
    assert profile_url in resp.headers["Location"]

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 77.25
    assert rows[0]["category"] == "Shopping"
    assert rows[0]["date"] == "2026-04-10"
    assert rows[0]["description"] == "New shoes"


def test_post_edit_expense_other_users_expense_returns_404(client, app, db_module):
    owner_id = create_test_user(db_module, email="owner@example.com")
    other_id = create_test_user(db_module, email="other@example.com")
    expense_id = seed_expense(db_module, owner_id)

    login(client, app, user_id=other_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "999", "category": "Other", "date": "2026-01-01", "description": "Hacked"},
    )
    assert resp.status_code == 404

    rows = fetch_expenses_for_user(db_module, owner_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 50.0
    assert rows[0]["description"] == "Original desc"


# ------------------------------------------------------------------ #
# 6. POST invalid amount (missing / zero / non-numeric)               #
# ------------------------------------------------------------------ #

def test_post_edit_expense_missing_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id)[0]["amount"] == 50.0


def test_post_edit_expense_zero_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "0", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id)[0]["amount"] == 50.0


def test_post_edit_expense_non_numeric_amount_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "not-a-number", "category": "Food", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid amount greater than 0." in body
    assert fetch_expenses_for_user(db_module, user_id)[0]["amount"] == 50.0


# ------------------------------------------------------------------ #
# 7. POST invalid category                                            #
# ------------------------------------------------------------------ #

def test_post_edit_expense_invalid_category_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "10", "category": "NotACategory", "date": "2026-03-15", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Select a valid category." in body
    assert fetch_expenses_for_user(db_module, user_id)[0]["category"] == "Food"


# ------------------------------------------------------------------ #
# 8. POST invalid date                                                #
# ------------------------------------------------------------------ #

def test_post_edit_expense_invalid_date_rerenders_with_error(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "10", "category": "Food", "date": "not-a-date", "description": ""},
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Enter a valid date." in body
    assert fetch_expenses_for_user(db_module, user_id)[0]["date"] == "2026-01-10"


# ------------------------------------------------------------------ #
# 9. POST no description -> stored as NULL                            #
# ------------------------------------------------------------------ #

def test_post_edit_expense_missing_description_saves_null(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id)
    login(client, app, user_id=user_id)

    with app.test_request_context():
        from flask import url_for
        profile_url = url_for("profile")

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={"amount": "15", "category": "Bills", "date": "2026-04-01", "description": ""},
    )

    assert resp.status_code == 302
    assert profile_url in resp.headers["Location"]

    rows = fetch_expenses_for_user(db_module, user_id)
    assert len(rows) == 1
    assert rows[0]["description"] is None


# ------------------------------------------------------------------ #
# Form value retention on validation failure                          #
# ------------------------------------------------------------------ #

def test_post_edit_expense_validation_error_repopulates_submitted_values_not_original(client, app, db_module):
    user_id = create_test_user(db_module)
    expense_id = seed_expense(db_module, user_id, amount=50.0, category="Food",
                               expense_date="2026-01-10", description="Original desc")
    login(client, app, user_id=user_id)

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data={
            "amount": "123.45",
            "category": "NotACategory",
            "date": "2026-05-05",
            "description": "Resubmitted desc",
        },
    )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'value="123.45"' in body
    assert 'value="2026-05-05"' in body
    assert 'value="Resubmitted desc"' in body
    assert 'value="50.0"' not in body
    assert 'value="Original desc"' not in body
