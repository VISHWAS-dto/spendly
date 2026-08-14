# Spendly

A lightweight personal expense tracker built with Flask and SQLite.

## Features

- User registration and login
- Add, view, and edit expenses
- Profile page with recent transactions and date-range filtering
- Analytics page with spending breakdowns and trends over time

## Tech stack

- **Backend:** Flask (Python), single `app.py` — no blueprints
- **Database:** SQLite via raw `sqlite3`, no ORM
- **Frontend:** Jinja2 templates, vanilla JS, no frameworks

## Getting started

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

python app.py
```

The app runs at `http://localhost:5001`.

## Running tests

```bash
pytest                    # run all tests
pytest tests/test_foo.py  # run a specific file
pytest -k "test_name"     # run a specific test
pytest -s                 # show output
```

## Project structure

```
spendly/
├── app.py              # All routes
├── database/
│   ├── db.py            # Connection, schema, seeding
│   └── queries.py       # Query helpers
├── templates/           # Jinja2 templates, one per page
├── static/
│   ├── css/              # Global + page-specific styles
│   └── js/                # Vanilla JS
├── tests/                # Pytest test suite
└── requirements.txt
```

## Routes

| Route | Description |
|---|---|
| `GET /` | Landing page |
| `GET/POST /register` | User registration |
| `GET/POST /login` | User login |
| `GET /logout` | User logout |
| `GET /profile` | Profile page with transaction history |
| `GET /analytics` | Spending analytics and trends |
| `GET/POST /expenses/add` | Add a new expense |
| `GET/POST /expenses/<id>/edit` | Edit an existing expense |
| `GET /expenses/<id>/delete` | Delete an expense — not yet implemented |

See `CLAUDE.md` for detailed architecture, code style, and contribution conventions.
