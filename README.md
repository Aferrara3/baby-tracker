# Baby Tracker

Baby activity tracker with a FastAPI backend, React frontend, SQLite storage, and Google Calendar sync.

## Current capabilities

- Household-scoped accounts with username/password sign-in
- Activity logging for bottle, food, diaper, sleep, breastfeeding, pump, and help
- Customizable paged tracker grid with add/remove pages, reorderable labels, and symbol-based Google Calendar emoji mapping
- Search-first icon picker backed by the full Lucide catalog plus custom/community icon uploads
- Tap-to-log and hold-to-start/stop timer flows
- Service-account-managed Google Calendar provisioning and sharing
- Google Calendar write sync plus pull-based reconciliation back into SQLite
- Quick tools to simulate a sample day and delete the current local calendar day

## Repo layout

- `backend/` - FastAPI API, SQLite models, Google Calendar integration, tests
- `frontend/` - React + Vite UI

## Local development

Copy `.env.example` to `.env` at the repo root to override local settings.

Use `APP_PROFILE_CONFIG_PATH` to select which app profile the shared codebase should run, for example:

```bash
APP_PROFILE_CONFIG_PATH=app-profiles/baby-app-config.yaml
APP_PROFILE_CONFIG_PATH=app-profiles/habit-app-config.yaml
```

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

The API runs on `http://localhost:8090`.
Local development defaults to `backend/database-dev.db`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:3005`.

### Combined dev command

From the repo root:

```bash
make dev
make dev PROFILE=habit
```

`make dev` defaults to the baby profile and uses `backend/database-dev.db`.
`make dev PROFILE=habit` uses the habit profile and `backend/database-habit-dev.db`.
`make` cannot accept a custom `--profile` flag here, so profile switching uses `PROFILE=baby|habit`.

### Database snapshots

Run the snapshot script from the repo root to copy every `*.db` file into a timestamped folder under `db-snapshots/`:

```bash
./scripts/backup-db-snapshots.sh
```

The script deletes snapshot folders older than 30 days by default. You can override the retention window for a run with `RETENTION_DAYS=...`.

Install the default daily cron job at 2:30 AM:

```bash
make install-db-backups
```

The installer is idempotent and rewrites only the `baby-tracker-db-backups` cron entry. You can override the schedule or log path when installing:

```bash
DB_BACKUP_CRON_SCHEDULE="0 3 * * *" DB_BACKUP_LOG_PATH="/tmp/baby-tracker-db-backups.log" make install-db-backups
```

Equivalent cron entry:

```bash
30 2 * * * cd /path/to/baby-tracker && ./scripts/backup-db-snapshots.sh >> /tmp/baby-tracker-db-snapshots.log 2>&1
```

## Deployment notes

- Preferred deployment shape is a single origin that serves the built frontend and the FastAPI API together.
- Local development remains unchanged with `make dev`.
- Database split:
  - local dev: `backend/database-dev.db`
  - deployed container: `backend/database-prd.db`
- Production runtime is configured with environment variables:
  - `APP_PROFILE_CONFIG_PATH`
  - `APP_HOST` / `APP_PORT`
  - `DB_PATH` or `DATABASE_URL`
  - `CUSTOM_ICON_STORAGE_DIR`
  - `CORS_ALLOWED_ORIGINS`
  - `GOOGLE_CREDENTIALS_PATH`
  - `FRONTEND_DIST_PATH`
  - frontend `VITE_*` variables for separate frontend builds
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
- For functional testing of the queued retry UX without touching Google, set `FORCE_GCAL_QUEUE_RETRY_TEST=1` in the repo root `.env` file and restart the backend. That keeps the real app flow unchanged: save locally, queue automatic retries, and show the delayed-sync UX.
