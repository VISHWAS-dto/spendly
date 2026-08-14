import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    CATEGORIES,
    create_user,
    get_user_by_email,
    init_db,
    seed_db,
)
from database.queries import get_summary_stats
from database.queries import get_user_by_id as get_user_profile
from database.queries import get_recent_transactions
from database.queries import get_category_breakdown
from database.queries import insert_expense
from database.queries import get_daily_spending_trend
from database.queries import get_monthly_comparison
from database.queries import get_expense_by_id
from database.queries import update_expense

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _months_ago(months):
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) - months
    year, month = divmod(total_months, 12)
    month += 1
    day = min(today.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _filter_presets():
    today = date.today()
    return {
        "this_month": (today.replace(day=1).isoformat(), today.isoformat()),
        "last_3_months": (_months_ago(3).isoformat(), today.isoformat()),
        "last_6_months": (_months_ago(6).isoformat(), today.isoformat()),
        "all_time": (None, None),
    }


FILTER_PRESET_LABELS = [
    ("this_month", "This Month"),
    ("last_3_months", "Last 3 Months"),
    ("last_6_months", "Last 6 Months"),
    ("all_time", "All Time"),
]


def _analytics_filter_presets():
    today = date.today()
    return {
        "7_days": ((today - timedelta(days=6)).isoformat(), today.isoformat()),
        "30_days": ((today - timedelta(days=29)).isoformat(), today.isoformat()),
        "3_months": (_months_ago(3).isoformat(), today.isoformat()),
    }


ANALYTICS_FILTER_PRESET_LABELS = [
    ("7_days", "7 Days"),
    ("30_days", "30 Days"),
    ("3_months", "3 Months"),
]


def _parse_date_param(value):
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name or not email or not password or not confirm_password:
        flash("All fields are required.", "error")
        return render_template("register.html")

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return render_template("register.html")

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        flash("Email already registered.", "error")
        return render_template("register.html")

    flash("Account created successfully. Please sign in.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Invalid email or password.", "error")
        return render_template("login.html")

    user = get_user_by_email(email)

    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.", "error")
        return render_template("login.html")

    session["user_id"] = user["id"]
    return redirect(url_for("landing"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    user = get_user_profile(user_id)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    date_from = _parse_date_param(request.args.get("date_from"))
    date_to = _parse_date_param(request.args.get("date_to"))

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = None
        date_to = None

    summary = get_summary_stats(user_id, date_from=date_from, date_to=date_to)
    recent_expenses = get_recent_transactions(user_id, date_from=date_from, date_to=date_to)
    category_totals = get_category_breakdown(user_id, date_from=date_from, date_to=date_to)
    top_category = category_totals[0]["name"] if category_totals else None

    return render_template(
        "profile.html",
        user=user,
        summary=summary,
        recent_expenses=recent_expenses,
        category_totals=category_totals,
        top_category=top_category,
        nav_user=user,
        date_from=date_from,
        date_to=date_to,
        filter_presets=_filter_presets(),
        filter_preset_labels=FILTER_PRESET_LABELS,
    )


def _trend_chart_points(trend, width=600, height=200):
    if len(trend) < 2:
        return ""

    amounts = [day["amount"] for day in trend]
    max_amount = max(amounts)
    min_amount = min(amounts)
    span = max_amount - min_amount or 1
    step = width / (len(trend) - 1)

    points = []
    for i, day in enumerate(trend):
        x = round(i * step, 2)
        y = round(height - ((day["amount"] - min_amount) / span) * height, 2)
        points.append(f"{x},{y}")
    return " ".join(points)


@app.route("/analytics")
def analytics():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    user = get_user_profile(user_id)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    date_from = _parse_date_param(request.args.get("date_from"))
    date_to = _parse_date_param(request.args.get("date_to"))
    active_preset = request.args.get("preset")

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = None
        date_to = None

    presets = _analytics_filter_presets()
    if active_preset in presets:
        date_from, date_to = presets[active_preset]
    elif not date_from and not date_to:
        active_preset = "30_days"
        date_from, date_to = presets[active_preset]
    else:
        active_preset = None

    summary = get_summary_stats(user_id, date_from=date_from, date_to=date_to)
    this_month_summary = get_summary_stats(
        user_id,
        date_from=date.today().replace(day=1).isoformat(),
        date_to=date.today().isoformat(),
    )
    category_totals = get_category_breakdown(user_id, date_from=date_from, date_to=date_to)
    recent_expenses = get_recent_transactions(user_id, limit=5, date_from=date_from, date_to=date_to)
    trend = get_daily_spending_trend(user_id, date_from=date_from, date_to=date_to)
    monthly = get_monthly_comparison(user_id)

    max_monthly_amount = max((row["amount"] for row in monthly), default=0)
    for row in monthly:
        row["pct"] = round(row["amount"] / max_monthly_amount * 100) if max_monthly_amount else 0
        row["label"] = datetime.strptime(row["month"], "%Y-%m").strftime("%b")

    return render_template(
        "analytics.html",
        nav_user=user,
        summary=summary,
        this_month_total=this_month_summary["total_spent"],
        category_totals=category_totals,
        recent_expenses=recent_expenses,
        trend=trend,
        trend_points=_trend_chart_points(trend),
        monthly=monthly,
        date_from=date_from,
        date_to=date_to,
        filter_presets=presets,
        filter_preset_labels=ANALYTICS_FILTER_PRESET_LABELS,
        active_preset=active_preset,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if get_user_profile(user_id) is None:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            today=date.today().isoformat(),
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    form_values = {
        "amount": amount_raw,
        "category": category,
        "date": expense_date,
        "description": description or "",
    }

    try:
        amount = float(amount_raw)
    except ValueError:
        amount = None

    if amount is None or amount <= 0:
        flash("Enter a valid amount greater than 0.", "error")
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            today=date.today().isoformat(),
            form_values=form_values,
        )

    if category not in CATEGORIES:
        flash("Select a valid category.", "error")
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            today=date.today().isoformat(),
            form_values=form_values,
        )

    if not _parse_date_param(expense_date):
        flash("Enter a valid date.", "error")
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            today=date.today().isoformat(),
            form_values=form_values,
        )

    insert_expense(user_id, amount, category, expense_date, description)
    flash("Expense added.", "success")
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if get_user_profile(user_id) is None:
        session.clear()
        return redirect(url_for("login"))

    expense = get_expense_by_id(id, user_id)
    if expense is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    form_values = {
        "amount": amount_raw,
        "category": category,
        "date": expense_date,
        "description": description or "",
    }

    try:
        amount = float(amount_raw)
    except ValueError:
        amount = None

    if amount is None or amount <= 0:
        flash("Enter a valid amount greater than 0.", "error")
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form_values=form_values,
        )

    if category not in CATEGORIES:
        flash("Select a valid category.", "error")
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form_values=form_values,
        )

    if not _parse_date_param(expense_date):
        flash("Enter a valid date.", "error")
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form_values=form_values,
        )

    update_expense(id, user_id, amount, category, expense_date, description)
    flash("Expense updated.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
