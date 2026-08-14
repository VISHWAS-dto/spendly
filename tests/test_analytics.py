"""
Tests for the Analytics dashboard page.

These tests exercise `GET /analytics` and the navbar's conditional
"Analytics" link through Flask's test client only, using an isolated temp
SQLite database (never the shared dev `spendly.db`).
"""
import importlib
import sys
from datetime import date, timedelta

import pytest


# ------------------------------------------------------------------ #
# Fixtures: isolated DB + Flask app/test client                       #
# ------------------------------------------------------------------ #

@pytest.fixture()
def app(tmp_path, monkeypatch):
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
    import database.db as db_mod
    return db_mod


# ------------------------------------------------------------------ #
# Data helpers                                                        #
# ------------------------------------------------------------------ #

def create_test_user(db_module, name="Test User", email="test@example.com", password="password123"):
    return db_module.create_user(name, email, password)


def insert_expense(db_module, user_id, amount, category, expense_date, description=""):
    conn = db_module.get_db()
    try:
        conn.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
    finally:
        conn.close()


def login(client, app, email="test@example.com", user_id=None):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

def test_analytics_requires_login(client, app):
    """Unauthenticated GET /analytics redirects to login."""
    with app.test_request_context():
        from flask import url_for
        analytics_url = url_for("analytics")
        login_url = url_for("login")

    resp = client.get(analytics_url)
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


def test_analytics_accessible_when_logged_in(client, app, db_module):
    """Authenticated GET /analytics renders the page successfully."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/analytics")
    assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Navbar visibility and active state                                  #
# ------------------------------------------------------------------ #

def test_analytics_link_hidden_when_logged_out(client, app):
    """The Analytics nav item must not appear for anonymous visitors."""
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "Analytics</a>" not in body


def test_analytics_link_visible_when_logged_in(client, app, db_module):
    """The Analytics nav item appears for authenticated users."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/profile")
    body = resp.get_data(as_text=True)
    assert "Analytics</a>" in body


def test_analytics_nav_item_active_on_analytics_page(client, app, db_module):
    """The Analytics nav link carries the active-state class on /analytics."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/analytics")
    body = resp.get_data(as_text=True)
    assert "nav-link-active" in body


def test_analytics_nav_item_not_active_elsewhere(client, app, db_module):
    """The Analytics nav link is not marked active on other pages."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/profile")
    body = resp.get_data(as_text=True)
    assert "nav-link-active" not in body


# ------------------------------------------------------------------ #
# Real data rendering                                                 #
# ------------------------------------------------------------------ #

def test_analytics_shows_total_spending_from_real_expenses(client, app, db_module):
    """KPI cards reflect actual expense data for the logged-in user, not placeholders."""
    user_id = create_test_user(db_module)
    today = date.today()
    insert_expense(db_module, user_id, 100.00, "Food", today.isoformat())
    insert_expense(db_module, user_id, 50.00, "Transport", today.isoformat())
    login(client, app, user_id=user_id)

    resp = client.get("/analytics?preset=30_days")
    body = resp.get_data(as_text=True)
    assert "150.00" in body


def test_analytics_empty_state_for_new_user(client, app, db_module):
    """A user with no expenses sees empty-state messaging, not broken charts."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/analytics")
    body = resp.get_data(as_text=True)
    assert "empty-state" in body
    assert "0.00" in body


def test_analytics_recent_spending_lists_real_transactions(client, app, db_module):
    """Recent spending section reflects actual DB rows for the user."""
    user_id = create_test_user(db_module)
    today = date.today()
    insert_expense(db_module, user_id, 42.50, "Shopping", today.isoformat(), description="New shoes")
    login(client, app, user_id=user_id)

    resp = client.get("/analytics?preset=30_days")
    body = resp.get_data(as_text=True)
    assert "New shoes" in body
    assert "42.50" in body


# ------------------------------------------------------------------ #
# Date filter behavior                                                #
# ------------------------------------------------------------------ #

def test_analytics_default_preset_is_30_days(client, app, db_module):
    """With no query params, the 30-day preset is applied and marked active."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/analytics")
    body = resp.get_data(as_text=True)
    assert 'filter-preset active">30 Days' in body


def test_analytics_7_day_preset_excludes_older_expenses(client, app, db_module):
    """Selecting the 7-day preset filters out expenses older than 7 days."""
    user_id = create_test_user(db_module)
    today = date.today()
    old_date = (today - timedelta(days=20)).isoformat()
    recent_date = today.isoformat()
    insert_expense(db_module, user_id, 999.00, "Bills", old_date, description="Old expense")
    insert_expense(db_module, user_id, 10.00, "Food", recent_date, description="Recent expense")
    login(client, app, user_id=user_id)

    resp = client.get("/analytics?preset=7_days")
    body = resp.get_data(as_text=True)
    assert "Recent expense" in body
    assert "Old expense" not in body
    assert 'filter-preset active">7 Days' in body


def test_analytics_7_day_range_includes_start_and_end_date_inclusive(client, app, db_module):
    """
    Regression test for a reported bug where /analytics appeared to show
    ₹0.00 for a 7-day window that should have included several expenses.

    Root cause turned out to be a user-data mismatch (the logged-in account
    had no expenses), not a query defect — but this test pins down the
    exact reported scenario: a today-anchored 7-day window whose expenses
    fall exactly on the start date and the end date must both be included,
    and the total must match precisely.
    """
    user_id = create_test_user(db_module)
    today = date.today()

    # Mirrors the reported dataset, shifted to be relative to "today" so
    # the test is stable regardless of when it runs. Two expenses fall
    # outside the 7-day window (before day 6, and 2 days in the future);
    # three fall inside it, including exactly on both boundary dates.
    insert_expense(db_module, user_id, 45.50, "Food", (today - timedelta(days=12)).isoformat())
    insert_expense(db_module, user_id, 30.00, "Transport", (today - timedelta(days=10)).isoformat())
    insert_expense(db_module, user_id, 12.00, "Food", (today - timedelta(days=8)).isoformat())
    insert_expense(db_module, user_id, 89.99, "Bills", (today - timedelta(days=6)).isoformat(), description="Electricity bill")
    insert_expense(db_module, user_id, 20.00, "Health", (today - timedelta(days=3)).isoformat(), description="Pharmacy")
    insert_expense(db_module, user_id, 15.75, "Entertainment", today.isoformat(), description="Movie tickets")
    insert_expense(db_module, user_id, 60.00, "Shopping", (today + timedelta(days=2)).isoformat())
    login(client, app, user_id=user_id)

    resp = client.get("/analytics?preset=7_days")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    # Boundary dates included: (today - 6 days) is the window start, today is the end.
    assert "Electricity bill" in body
    assert "Pharmacy" in body
    assert "Movie tickets" in body
    # Outside the window on either side.
    assert "60.00" not in body
    # Exact total for the three in-window expenses: 89.99 + 20.00 + 15.75
    assert "₹125.74" in body


def test_analytics_custom_date_range_filters_data(client, app, db_module):
    """A custom date_from/date_to range is honored and reflected in the totals."""
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 20.00, "Food", "2026-01-15")
    insert_expense(db_module, user_id, 500.00, "Bills", "2026-06-01")
    login(client, app, user_id=user_id)

    resp = client.get("/analytics?date_from=2026-01-01&date_to=2026-01-31")
    body = resp.get_data(as_text=True)
    assert "20.00" in body
    assert "500.00" not in body


def test_analytics_invalid_custom_range_shows_error(client, app, db_module):
    """A date_from after date_to triggers a flash error rather than broken output."""
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/analytics?date_from=2026-08-13&date_to=2026-01-01")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Start date must be before end date." in body
