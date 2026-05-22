# Legal Bot

![CI](https://github.com/vgartg/TG-Bot-DeepSeek-Integration/actions/workflows/ci.yml/badge.svg)
[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-20.7-26A5E4?logo=telegram&logoColor=white)](https://python-telegram-bot.org/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-API-4D6BFE)](https://platform.deepseek.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE.txt)

A pet project to practice building a real-world Telegram bot end to end: a long-running asyncio app, a SQLAlchemy-backed user state model, an integration with the DeepSeek chat completion API, and YooKassa payments wired through Telegram's native invoice flow

## What it does

`Legal Bot` is a Russian-language consultation bot that answers civil-law questions on demand. Users start with four free questions, then either buy one-off paid questions (text or with attached PDF/DOCX/TXT documents) or activate an unlimited subscription for two weeks, one month, or three months

The bot remembers each user's quota, persists every paid request as a receipt that an admin can mark as issued, falls back from DeepSeek's remote file upload to local text extraction (`pdfplumber` → `PyPDF2` → `python-docx`) when the upload endpoint is unavailable, and splits long answers across multiple Telegram messages so it never trips the 4096-character limit

## Architecture

```
Telegram client
      │
      ▼
python-telegram-bot (long polling)
      │
      ▼
LegalBot dispatcher  ──►  SQLAlchemy / SQLite  (users, requests, paid_requests)
      │
      ├──►  DeepSeekAPI  ──►  https://api.deepseek.com  (chat + file upload)
      │
      └──►  YooKassa (via Telegram Payments)  ──►  successful_payment_callback
```

Three boundaries: the Telegram update loop on top, the SQLAlchemy session per request in the middle, the DeepSeek and YooKassa integrations on the outside. State machines (`ConversationHandler`) track multi-step flows like "upload file → ask question"

## Quickstart

You only need Python 3.11+ and a Telegram bot token. The `bin/` scripts create a virtual environment and install the package in editable mode on first run

```bash
cp .env.example .env
# fill in BOT_TOKEN, DEEPSEEK_API_KEY, PROVIDER_TOKEN, ADMIN_IDS

./bin/run             # Linux / macOS
.\bin\run.ps1         # Windows PowerShell
```

Or set up manually:

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .[dev]
python -m legal_bot
```

After install, the `legal-bot` console script does the same thing:

```bash
legal-bot
```

## Running tests

```bash
./bin/test            # Linux / macOS
# or:
ruff check legal_bot tests
ruff format --check legal_bot tests
pytest -q
```

The test suite covers pure helpers (`format_answer`, `check_file_type`, `get_file_size_mb`) and every keyboard factory in `legal_bot/keyboards.py`, with an in-memory SQLite DB used during collection so importing the package never touches a real database file

## HTTP integrations

| Integration | Direction | Purpose |
| --- | --- | --- |
| Telegram Bot API | inbound long polling + outbound `send_message`, `send_invoice`, `send_photo` | All chat traffic and payment invoices |
| DeepSeek `/chat/completions` | outbound | Answer text generation |
| DeepSeek `/files` | outbound | Optional file upload for richer document QA |
| YooKassa via Telegram Payments | webhook-driven `pre_checkout_query` + `successful_payment` updates | Subscriptions and one-off paid questions |

## Configuration

All configuration is read from environment variables loaded via `python-dotenv`

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `BOT_TOKEN` | yes | — | Bot token from @BotFather |
| `DEEPSEEK_API_KEY` | yes | — | API key from platform.deepseek.com |
| `PROVIDER_TOKEN` | yes | — | YooKassa provider token issued by Telegram |
| `DATABASE_URL` | no | `sqlite:///legal_bot.db` | Any SQLAlchemy URL |
| `ADMIN_IDS` | no | (internal fallback) | Comma-separated Telegram user IDs for the admin panel |

Pricing is hard-coded in `legal_bot/config.py` in kopecks (200 RUB = 20000): edit there if you want different tiers

## Project layout in detail

```
legal_bot/
├── __init__.py             # package version
├── __main__.py             # `python -m legal_bot` entry point
├── bot.py                  # LegalBot class, handlers, ConversationHandler wiring
├── config.py               # env loading, prices, text constants, admin IDs
├── database.py             # SQLAlchemy engine + scoped session, CRUD helpers
├── deepseek_api.py         # OpenAI-compatible client + file extraction fallbacks
├── keyboards.py            # InlineKeyboardMarkup factories per menu
├── models.py               # User / UserRequest / PaidRequest schemas
└── utils.py                # QR generation, message splitting, file checks
tests/                      # pytest specs for utils + keyboards + package metadata
bin/                        # convenience launch and test scripts
.github/workflows/ci.yml    # lint + format check + tests on Python 3.11 and 3.12
pyproject.toml              # PEP 621 metadata, dependencies, ruff + pytest config
requirements.txt            # legacy pip-only install path, kept for parity
.env.example                # documented env vars
```

## Tooling

| Concern | Tool |
| --- | --- |
| Lint | [ruff](https://docs.astral.sh/ruff/) |
| Format | `ruff format` |
| Tests | [pytest](https://docs.pytest.org/) |
| ORM | [SQLAlchemy 2.x](https://www.sqlalchemy.org/) |
| Telegram client | [python-telegram-bot 20.7](https://python-telegram-bot.org/) |
| Chat completion client | [openai 1.x](https://github.com/openai/openai-python) pointed at DeepSeek |
| PDF extraction | `pdfplumber`, `PyPDF2` |
| DOCX extraction | `python-docx` |
| QR generation | `qrcode`, `Pillow` |
| CI | GitHub Actions matrix on Python 3.11 and 3.12 |

## Roadmap

- Pluggable model backend so DeepSeek can be swapped for any other OpenAI-compatible endpoint via env config
- Webhook mode in addition to long polling, so deployment on a free PaaS becomes a single container with no busy-poll
- Postgres support exercised end-to-end in CI (currently the schema works against Postgres but only SQLite is verified)
- Localization of all user-facing strings via gettext so a second language is opt-in
- A small admin web view for browsing receipts, since the inline keyboard pagination gets unwieldy past a few dozen entries
