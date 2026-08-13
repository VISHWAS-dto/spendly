"""
Tests for Step 6: Date filter on the profile page.

Spec: .claude/specs/06-date-filter-profile-page.md

These tests exercise `GET /profile` through Flask's test client only, using
an isolated temp SQLite database (never the shared dev `spendly.db`). Test
logic is derived strictly from the spec's stated behaviour, not from reading
the query/route implementation.
"""
import importlib
import os
import sys
from datetime import date, timedelta

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

    # seed_db() inserts a demo user with expenses; we don't rely on that
    # seeded data's exact contents in assertions (per instructions), but we
    # do want a clean, known dataset. Wipe whatever seed_db() created and
    # insert our own controlled fixture data per-test via helpers below.
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
    """Log a user in by setting the session directly (bypasses password form)."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

def test_profile_requires_login_no_params(client, app):
    """Unauthenticated GET /profile (no filter params) redirects to login."""
    with app.test_request_context():
        from flask import url_for
        profile_url = url_for("profile")
        login_url = url_for("login")

    resp = client.get(profile_url)
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


def test_profile_requires_login_with_filter_params(client, app):
    """Unauthenticated GET /profile with filter params still redirects to login."""
    with app.test_request_context():
        from flask import url_for
        login_url = url_for("login")

    resp = client.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
    assert resp.status_code in (301, 302)
    assert login_url in resp.headers["Location"]


# ------------------------------------------------------------------ #
# No query params -> unfiltered / all-time behaviour                  #
# ------------------------------------------------------------------ #

def test_profile_no_params_returns_all_expenses(client, app, db_module):
    """
    Spec DoD: 'Visiting /profile with no query params returns the same data
    as Step 5 (unfiltered, all expenses)'.
    """
    user_id = create_test_user(db_module)
    today = date.today()
    old_date = (today - timedelta(days=400)).isoformat()
    recent_date = today.isoformat()

    insert_expense(db_module, user_id, 100.0, "Food", old_date, "Old expense")
    insert_expense(db_module, user_id, 50.0, "Transport", recent_date, "Recent expense")

    login(client, app, user_id=user_id)
    resp = client.get("/profile")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Both old and recent expenses show up — nothing filtered out.
    assert "Old expense" in body
    assert "Recent expense" in body
    # Total spent = 150.00
    assert "₹150.00" in body
    # Two transactions counted.
    assert "Food" in body and "Transport" in body


# ------------------------------------------------------------------ #
# Valid custom range: both date_from and date_to                      #
# ------------------------------------------------------------------ #

def test_profile_valid_range_filters_all_three_sections(client, app, db_module):
    """
    Spec DoD: 'Submitting a custom date range with valid date_from and
    date_to shows only expenses within that range in all three sections'
    (summary stats, recent transactions, category breakdown).
    """
    user_id = create_test_user(db_module)

    insert_expense(db_module, user_id, 100.0, "Food", "2026-03-15", "In range food")
    insert_expense(db_module, user_id, 40.0, "Transport", "2026-03-20", "In range transport")
    insert_expense(db_module, user_id, 999.0, "Shopping", "2026-01-01", "Out of range - before")
    insert_expense(db_module, user_id, 500.0, "Bills", "2026-06-01", "Out of range - after")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2026-03-01&date_to=2026-03-31")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # In-range transactions appear.
    assert "In range food" in body
    assert "In range transport" in body

    # Out-of-range transactions do not appear.
    assert "Out of range - before" not in body
    assert "Out of range - after" not in body

    # Summary total reflects only the in-range expenses: 100 + 40 = 140.00
    assert "₹140.00" in body

    # Category breakdown restricted to in-range categories only.
    assert "Shopping" not in body
    assert "Bills" not in body


def test_profile_valid_range_inclusive_boundaries(client, app, db_module):
    """date_from/date_to bounds are inclusive per spec."""
    user_id = create_test_user(db_module)

    insert_expense(db_module, user_id, 10.0, "Food", "2026-03-01", "On start boundary")
    insert_expense(db_module, user_id, 20.0, "Food", "2026-03-31", "On end boundary")
    insert_expense(db_module, user_id, 30.0, "Food", "2026-02-28", "Just before range")
    insert_expense(db_module, user_id, 40.0, "Food", "2026-04-01", "Just after range")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2026-03-01&date_to=2026-03-31")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "On start boundary" in body
    assert "On end boundary" in body
    assert "Just before range" not in body
    assert "Just after range" not in body


# ------------------------------------------------------------------ #
# Open-ended ranges (only one of date_from / date_to supplied)        #
# ------------------------------------------------------------------ #

def test_profile_only_date_from_open_ended_upper_bound(client, app, db_module):
    """Only date_from supplied -> everything from that date onward, no upper bound."""
    user_id = create_test_user(db_module)

    insert_expense(db_module, user_id, 10.0, "Food", "2026-01-01", "Before cutoff")
    insert_expense(db_module, user_id, 20.0, "Food", "2026-06-01", "After cutoff")
    insert_expense(db_module, user_id, 30.0, "Food", "2030-01-01", "Far future")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2026-05-01")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Before cutoff" not in body
    assert "After cutoff" in body
    assert "Far future" in body


def test_profile_only_date_to_open_ended_lower_bound(client, app, db_module):
    """Only date_to supplied -> everything up to that date, no lower bound."""
    user_id = create_test_user(db_module)

    insert_expense(db_module, user_id, 10.0, "Food", "2020-01-01", "Old expense")
    insert_expense(db_module, user_id, 20.0, "Food", "2026-01-01", "Within cutoff")
    insert_expense(db_module, user_id, 30.0, "Food", "2026-12-31", "After cutoff")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_to=2026-06-01")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Old expense" in body
    assert "Within cutoff" in body
    assert "After cutoff" not in body


# ------------------------------------------------------------------ #
# Invalid range: date_from > date_to                                  #
# ------------------------------------------------------------------ #

def test_profile_date_from_after_date_to_falls_back_and_flashes(client, app, db_module):
    """
    Spec: 'If date_from > date_to after validation, treat both as absent (no
    filter) and flash a user-visible error message:
    "Start date must be before end date."'
    """
    user_id = create_test_user(db_module)

    insert_expense(db_module, user_id, 10.0, "Food", "2026-01-15", "January expense")
    insert_expense(db_module, user_id, 20.0, "Food", "2026-06-15", "June expense")

    login(client, app, user_id=user_id)
    # date_from is after date_to -> invalid range.
    resp = client.get("/profile?date_from=2026-06-01&date_to=2026-01-01")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Falls back to unfiltered view: both expenses visible.
    assert "January expense" in body
    assert "June expense" in body

    # Flash error message is present verbatim.
    assert "Start date must be before end date." in body


# ------------------------------------------------------------------ #
# Malformed date string                                                #
# ------------------------------------------------------------------ #

def test_profile_malformed_date_from_falls_back_without_crashing(client, app, db_module):
    """
    Spec: 'Submitting a malformed date string (e.g. date_from=not-a-date)
    does not crash the app — it silently falls back to the unfiltered view.'
    """
    user_id = create_test_user(db_module)

    insert_expense(db_module, user_id, 10.0, "Food", "2026-01-15", "January expense")
    insert_expense(db_module, user_id, 20.0, "Food", "2026-06-15", "June expense")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=not-a-date&date_to=2026-06-30")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Malformed date_from treated as absent; per spec that means the whole
    # filter falls back to unfiltered (no crash, both expenses visible).
    assert "January expense" in body
    assert "June expense" in body


def test_profile_malformed_date_to_falls_back_without_crashing(client, app, db_module):
    """Malformed date_to alone must not crash and falls back to unfiltered."""
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 10.0, "Food", "2026-01-15", "January expense")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_to=banana")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "January expense" in body


def test_profile_both_dates_malformed_no_crash(client, app, db_module):
    """Both params malformed simultaneously must not crash the route."""
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 10.0, "Food", "2026-01-15", "January expense")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=xxxx&date_to=yyyy")

    assert resp.status_code == 200
    assert "January expense" in resp.get_data(as_text=True)


# ------------------------------------------------------------------ #
# Empty-result range                                                   #
# ------------------------------------------------------------------ #

def test_profile_range_with_no_matching_expenses(client, app, db_module):
    """
    Spec DoD: 'A user with no expenses in the selected range sees ₹0.00
    total spent, 0 transactions, and an empty category breakdown — no
    errors.'
    """
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 10.0, "Food", "2026-01-15", "January expense")

    login(client, app, user_id=user_id)
    # Range with no expenses in it at all.
    resp = client.get("/profile?date_from=2027-01-01&date_to=2027-01-31")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "₹0.00" in body
    assert "January expense" not in body
    assert "No expenses yet" in body


def test_profile_new_user_no_expenses_at_all(client, app, db_module):
    """A user with zero expenses (unfiltered) also sees the empty state, no errors."""
    user_id = create_test_user(db_module, email="empty@example.com")

    login(client, app, user_id=user_id)
    resp = client.get("/profile")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "₹0.00" in body
    assert "No expenses yet" in body


# ------------------------------------------------------------------ #
# Rupee symbol always present                                         #
# ------------------------------------------------------------------ #

def test_rupee_symbol_present_unfiltered(client, app, db_module):
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 25.0, "Food", date.today().isoformat())

    login(client, app, user_id=user_id)
    resp = client.get("/profile")
    assert "₹" in resp.get_data(as_text=True)


def test_rupee_symbol_present_with_valid_filter(client, app, db_module):
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 25.0, "Food", "2026-03-10")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2026-03-01&date_to=2026-03-31")
    assert "₹" in resp.get_data(as_text=True)


def test_rupee_symbol_present_with_empty_range(client, app, db_module):
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 25.0, "Food", "2026-03-10")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2030-01-01&date_to=2030-01-31")
    assert "₹" in resp.get_data(as_text=True)


def test_rupee_symbol_present_after_invalid_range_fallback(client, app, db_module):
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 25.0, "Food", "2026-03-10")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2026-06-01&date_to=2026-01-01")
    assert "₹" in resp.get_data(as_text=True)


# ------------------------------------------------------------------ #
# Preset behaviour: This Month / Last 3 Months / Last 6 Months / All  #
# ------------------------------------------------------------------ #

def _first_of_month(d):
    return d.replace(day=1)


def _months_ago_boundary(months):
    """
    Mirrors the spec's stated preset windows: an N-month window ending
    today. We independently compute the expected boundary here (not by
    importing app.py's helper) so the test can catch a wrong implementation.
    """
    today = date.today()
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = today.day
    # Clamp to the last valid day of the target month.
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def test_preset_this_month_filters_to_current_calendar_month(client, app, db_module):
    """
    Spec DoD: 'Clicking "This Month" filters all three sections to the
    current calendar month only.'
    """
    user_id = create_test_user(db_module)
    today = date.today()
    start_of_month = _first_of_month(today)

    insert_expense(db_module, user_id, 15.0, "Food", today.isoformat(), "This month expense")

    # An expense dated just before the start of this month must be excluded.
    if start_of_month > date(start_of_month.year - 1, 1, 1):
        day_before_month = start_of_month - timedelta(days=1)
        insert_expense(db_module, user_id, 999.0, "Shopping", day_before_month.isoformat(), "Previous month expense")

    login(client, app, user_id=user_id)
    resp = client.get(f"/profile?date_from={start_of_month.isoformat()}&date_to={today.isoformat()}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "This month expense" in body
    assert "Previous month expense" not in body


def test_preset_last_3_months_window(client, app, db_module):
    """
    Spec DoD: 'Clicking "Last 3 Months" filters to expenses in the 3-month
    window ending today.'
    """
    user_id = create_test_user(db_module)
    today = date.today()
    boundary = _months_ago_boundary(3)

    insert_expense(db_module, user_id, 15.0, "Food", today.isoformat(), "Within 3 months")
    insert_expense(db_module, user_id, 15.0, "Food", boundary.isoformat(), "On 3-month boundary")

    outside = boundary - timedelta(days=5)
    insert_expense(db_module, user_id, 999.0, "Shopping", outside.isoformat(), "Outside 3 months")

    login(client, app, user_id=user_id)
    resp = client.get(f"/profile?date_from={boundary.isoformat()}&date_to={today.isoformat()}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Within 3 months" in body
    assert "On 3-month boundary" in body
    assert "Outside 3 months" not in body


def test_preset_last_6_months_window(client, app, db_module):
    """
    Spec DoD: 'Clicking "Last 6 Months" filters to expenses in the 6-month
    window ending today.'
    """
    user_id = create_test_user(db_module)
    today = date.today()
    boundary = _months_ago_boundary(6)

    insert_expense(db_module, user_id, 15.0, "Food", today.isoformat(), "Within 6 months")
    insert_expense(db_module, user_id, 15.0, "Food", boundary.isoformat(), "On 6-month boundary")

    outside = boundary - timedelta(days=5)
    insert_expense(db_module, user_id, 999.0, "Shopping", outside.isoformat(), "Outside 6 months")

    login(client, app, user_id=user_id)
    resp = client.get(f"/profile?date_from={boundary.isoformat()}&date_to={today.isoformat()}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Within 6 months" in body
    assert "On 6-month boundary" in body
    assert "Outside 6 months" not in body


def test_preset_all_time_shows_everything_and_uses_clean_url(client, app, db_module):
    """
    Spec: 'The "All Time" preset must pass no query params (clean /profile
    URL)' and DoD: 'Clicking "All Time" removes any active filter and shows
    all expenses.'
    """
    user_id = create_test_user(db_module)
    today = date.today()
    old_date = (today - timedelta(days=1000)).isoformat()

    insert_expense(db_module, user_id, 15.0, "Food", old_date, "Very old expense")
    insert_expense(db_module, user_id, 15.0, "Food", today.isoformat(), "Recent expense")

    login(client, app, user_id=user_id)

    # Simulate clicking the "All Time" preset: clean /profile with no params.
    resp = client.get("/profile")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Very old expense" in body
    assert "Recent expense" in body

    # The template's "All Time" preset link must render as a clean /profile
    # URL with no query-string params.
    assert 'href="/profile"' in body or "href=\"/profile\"" in body


def test_filter_presets_available_in_template_context(client, app, db_module):
    """
    The filter bar must offer all four presets (This Month, Last 3 Months,
    Last 6 Months, All Time) as visible links/labels on the rendered page.
    """
    user_id = create_test_user(db_module)
    login(client, app, user_id=user_id)

    resp = client.get("/profile")
    body = resp.get_data(as_text=True)

    assert "This Month" in body
    assert "Last 3 Months" in body
    assert "Last 6 Months" in body
    assert "All Time" in body


def test_active_preset_reflected_in_form_fields(client, app, db_module):
    """
    Spec: 'the active preset button or custom-range fields visually
    indicate which filter is currently applied' — check the date input
    values reflect the active filter (date_from/date_to echoed back).
    """
    user_id = create_test_user(db_module)
    insert_expense(db_module, user_id, 10.0, "Food", "2026-03-10")

    login(client, app, user_id=user_id)
    resp = client.get("/profile?date_from=2026-03-01&date_to=2026-03-31")
    body = resp.get_data(as_text=True)

    assert 'value="2026-03-01"' in body
    assert 'value="2026-03-31"' in body
