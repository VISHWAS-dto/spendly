# Spec: Profile Page

## Overview
Implement the logged-in user's profile page. This converts the `/profile` stub into a route that requires authentication and renders the current user's account details (name, email, member-since date) along with a summary of their expense activity (e.g. total spent, number of expenses recorded). This is the first "logged-in only" page in Spendly and establishes the pattern for guarding routes that require `session["user_id"]`, which later expense-management steps will reuse.

## Depends on
- Step 01 — Database Setup (`users` and `expenses` tables, `get_db()`)
- Step 02 — Registration (`users` rows exist to view)
- Step 03 — Login and Logout (`session["user_id"]` is set on login; nav already links to `url_for('profile')`)

## Routes
- `GET /profile` — render the logged-in user's profile with account info and expense summary — logged-in only (redirect to `/login` if not authenticated)

## Database changes
No new tables or columns. The existing `users` table (id, name, email, password_hash, created_at) and `expenses` table (id, user_id, amount, category, date, description, created_at) cover all requirements.

New DB helpers needed in `database/db.py`:
- `get_user_by_id(user_id)` — returns a single user row by `id`, or `None`
- `get_expense_summary(user_id)` — returns aggregate stats for a user (total amount spent, count of expenses), computed with `SUM()` / `COUNT()` in SQL rather than in Python

## Templates
- **Create:** `templates/profile.html` — displays name, email, member-since date (formatted from `created_at`), and the expense summary (total spent, number of expenses); extends `base.html`
- **Modify:** None required beyond the new template. `base.html` nav already links to `url_for('profile')`.

## Files to change
- `app.py` — replace the `profile()` stub with a real handler: check `session.get("user_id")`, redirect to `login` if absent, otherwise fetch user + summary and render `profile.html`
- `database/db.py` — add `get_user_by_id()` and `get_expense_summary()` helpers

## Files to create
- `templates/profile.html`
- `static/css/profile.css` — page-specific styles (per CLAUDE.md: page-specific styles get their own CSS file, not inline `<style>` tags)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use raw `sqlite3` via `get_db()`
- Parameterised queries only — never use f-strings in SQL
- Passwords hashed with werkzeug (no change needed here, but never select/display `password_hash` in the template)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use `url_for()` for every internal link — never hardcode paths
- If `session.get("user_id")` is missing, redirect to `url_for("login")` — do not render the profile page to guests
- `get_user_by_id` and `get_expense_summary` belong in `database/db.py`, not inline in the route
- The route function should only: check auth, fetch data, render template — no query logic inline
- If the session references a `user_id` that no longer exists in the DB (edge case), clear the session and redirect to `login` rather than erroring

## Definition of done
- [ ] Visiting `GET /profile` while logged out redirects to `/login`
- [ ] Visiting `GET /profile` while logged in (e.g. demo@spendly.com / demo123) renders the profile page with the user's name, email, and member-since date
- [ ] The profile page shows the correct total amount spent and expense count for the logged-in demo user, matching the seeded data
- [ ] The `/profile` route no longer returns the raw stub string
- [ ] `password_hash` is never rendered anywhere in `profile.html`
- [ ] The "My account" nav link in `base.html` correctly navigates to the working profile page
