from database.db import get_db


def get_user_by_id(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None

        created_at = row["created_at"]
        member_since = _format_member_since(created_at)

        return {
            "name": row["name"],
            "email": row["email"],
            "member_since": member_since,
        }
    finally:
        conn.close()


def _format_member_since(created_at):
    # created_at is stored as "YYYY-MM-DD HH:MM:SS" (SQLite datetime('now'))
    date_part = created_at.split(" ")[0]
    year, month, _ = date_part.split("-")
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    return f"{month_names[int(month) - 1]} {year}"


def _date_range_clause(date_from, date_to):
    clause = ""
    params = []
    if date_from:
        clause += " AND date >= ?"
        params.append(date_from)
    if date_to:
        clause += " AND date <= ?"
        params.append(date_to)
    return clause, params


def get_summary_stats(user_id, date_from=None, date_to=None):
    conn = get_db()
    try:
        range_clause, range_params = _date_range_clause(date_from, date_to)

        summary_row = conn.execute(
            f"""
            SELECT COUNT(*) AS transaction_count,
                   COALESCE(SUM(amount), 0) AS total_spent
            FROM expenses
            WHERE user_id = ?{range_clause}
            """,
            (user_id, *range_params),
        ).fetchone()

        top_category_row = conn.execute(
            f"""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE user_id = ?{range_clause}
            GROUP BY category
            ORDER BY total DESC
            LIMIT 1
            """,
            (user_id, *range_params),
        ).fetchone()

        transaction_count = summary_row["transaction_count"]
        total_spent = summary_row["total_spent"]

        if transaction_count == 0:
            return {
                "total_spent": 0,
                "transaction_count": 0,
                "top_category": "—",
            }

        return {
            "total_spent": total_spent,
            "transaction_count": transaction_count,
            "top_category": top_category_row["category"] if top_category_row else "—",
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    conn = get_db()
    try:
        range_clause, range_params = _date_range_clause(date_from, date_to)

        rows = conn.execute(
            f"""
            SELECT date, description, category, amount
            FROM expenses
            WHERE user_id = ?{range_clause}
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (user_id, *range_params, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def insert_expense(user_id, amount, category, expense_date, description):
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_category_breakdown(user_id, date_from=None, date_to=None):
    conn = get_db()
    try:
        range_clause, range_params = _date_range_clause(date_from, date_to)

        rows = conn.execute(
            f"""
            SELECT category, SUM(amount) AS amount
            FROM expenses
            WHERE user_id = ?{range_clause}
            GROUP BY category
            ORDER BY amount DESC
            """,
            (user_id, *range_params),
        ).fetchall()

        if not rows:
            return []

        total = sum(row["amount"] for row in rows)

        breakdown = []
        for row in rows:
            amount = row["amount"]
            pct = round(amount / total * 100) if total else 0
            breakdown.append({
                "name": row["category"],
                "amount": amount,
                "pct": pct,
            })

        remainder = 100 - sum(item["pct"] for item in breakdown)
        if remainder != 0:
            largest = max(breakdown, key=lambda item: item["amount"])
            largest["pct"] += remainder

        return breakdown
    finally:
        conn.close()


def get_daily_spending_trend(user_id, date_from=None, date_to=None):
    conn = get_db()
    try:
        range_clause, range_params = _date_range_clause(date_from, date_to)

        rows = conn.execute(
            f"""
            SELECT date, SUM(amount) AS amount
            FROM expenses
            WHERE user_id = ?{range_clause}
            GROUP BY date
            ORDER BY date ASC
            """,
            (user_id, *range_params),
        ).fetchall()
        return [{"date": row["date"], "amount": row["amount"]} for row in rows]
    finally:
        conn.close()


def get_monthly_comparison(user_id, months=6):
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS amount
            FROM expenses
            WHERE user_id = ?
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
            """,
            (user_id, months),
        ).fetchall()
        return [{"month": row["month"], "amount": row["amount"]} for row in reversed(rows)]
    finally:
        conn.close()
