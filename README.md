# OpenBench — AI-powered resource sharing

A hackathon prototype built with Python, Flask, Flask-SQLAlchemy, SQLite, HTML, CSS and JavaScript. It supports resource listings across multiple categories, renter/owner workflows, bookings, waitlists, condition records, incident reporting, audit history, an admin review dashboard, impact metrics and optional Gemini-powered search assistance.

## Requirements
- Python 3.10 or newer (Python 3.12 is fine)
- VS Code (recommended)
- Internet connection for installing dependencies and optional Gemini AI calls

## Run on Windows PowerShell
Open this folder in VS Code, then choose **Terminal → New Terminal**:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

If `.env` already exists, do not overwrite it; just check its settings. Open <http://127.0.0.1:5000> in your browser. Stop the server with `Ctrl+C`.

If PowerShell blocks virtual-environment activation, run this in that terminal, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Run on macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## Demo accounts
These accounts are seeded for local demonstrations when `SEED_DEMO=true`:

| Role | Email | Password |
|---|---|---|
| Owner | owner@openbench.demo | OwnerDemo123! |
| Renter | renter@openbench.demo | RenterDemo123! |
| Admin | admin@openbench.demo | AdminDemo123! |

Do not use demo credentials or the development secret on a public deployment. The demo admin is for local judging only. Admin access must never be self-selected by ordinary registration.

## Environment configuration
`.env.example` is a template. The app loads `.env` automatically. For local use, leave `DATABASE_URL` blank (`DATABASE_URL=`) so the app uses `instance/openbench.db`. The app also ignores whitespace-only values. If `DATABASE_URL` contains a non-empty invalid URL, SQLAlchemy will still reject it; remove that line or set it to `DATABASE_URL=` for SQLite.

AI search uses keyword fallback if `GEMINI_API_KEY` is blank. To enable Gemini, add your own key to `.env`:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Restart the server after changing `.env`. Never commit `.env` or share your API key. Voice input depends on browser speech-recognition support and may require internet access.

## Tests
Install requirements, activate the virtual environment, and run:

```powershell
python -m unittest discover -s tests -v
```

## Troubleshooting
- **`Could not parse SQLAlchemy URL`**: open `.env`, make sure `DATABASE_URL=` is empty. Do not put quotes, placeholder text, or other text after the equals sign. This build also treats whitespace-only values as empty.
- **`Address already in use`**: stop another running Flask instance with `Ctrl+C`, or close the terminal running it.
- **PowerShell activation blocked**: use the execution-policy command shown above, or run `.venv\Scripts\python.exe app.py` without activating.
- **AI appears to use fallback search**: this is expected until a valid `GEMINI_API_KEY` is configured.

## Important limitations
OpenBench is a hackathon prototype, not a production marketplace. The `verified` field is an admin review flag, not proof of real-world identity. Payments, third-party identity verification, automatic image-based damage detection, and production-grade dispute adjudication are not implemented. Fairness and impact figures should be presented as recommendations or estimates, not authoritative decisions or verified real-world outcomes. Before public deployment, add CSRF protection, rate limiting, hardened session/security configuration, proper migrations, deployment secrets, privacy review and comprehensive tests.
