# Baby Tracker

Baby activity tracker with a FastAPI backend, React frontend, SQLite storage, and Google Calendar sync.

## Current capabilities

- Household-scoped accounts with username/password sign-in
- Activity logging for bottle, food, diaper, sleep, breastfeeding, pump, and help
- Customizable paged tracker grid with add/remove pages, reorderable labels, and symbol-based Google Calendar emoji mapping
- Tap-to-log and hold-to-start/stop timer flows
- Service-account-managed Google Calendar provisioning and sharing
- Google Calendar write sync plus pull-based reconciliation back into SQLite
- Quick tools to simulate a sample day and delete the current local calendar day

## Repo layout

- `backend/` - FastAPI API, SQLite models, Google Calendar integration, tests
- `frontend/` - React + Vite UI

## Local development

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

The API runs on `http://localhost:8090`.
Local development uses `backend/database-dev.db`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:3005`.

## Deployment notes

- Preferred deployment shape is a single origin that serves the built frontend and the FastAPI API together.
- Local development remains unchanged with `make dev`.
- Database split:
  - local dev: `backend/database-dev.db`
  - deployed container: `backend/database-prd.db`
- Production runtime is configured with environment variables:
  - `APP_HOST` / `APP_PORT`
  - `DB_PATH` or `DATABASE_URL`
  - `CORS_ALLOWED_ORIGINS`
  - `GOOGLE_CREDENTIALS_PATH`
  - `FRONTEND_DIST_PATH`
- For container deployment, the production DB file is mounted in-place at `backend/database-prd.db`, and the Google credentials file is mounted read-only instead of baking it into the image.

## Tests

### Backend tests

```bash
cd backend
source venv/bin/activate
pytest -q
```

Live Google Calendar API tests are opt-in:

```bash
ENABLE_LIVE_CALENDAR_TESTS=1 pytest -q
```

### Frontend validation

```bash
cd frontend
npm run lint
npm run build
```

## Google Calendar notes

- The app is set up for one service-account-owned calendar per household account.
- Users can save share emails and enable sync from the Settings screen.
- Google pull sync runs automatically on a configurable interval in the frontend.
- The default poll interval is one hour via `VITE_GOOGLE_SYNC_POLL_INTERVAL_MS`.
