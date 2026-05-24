#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
CRON_SCHEDULE="${DB_BACKUP_CRON_SCHEDULE:-30 2 * * *}"
LOG_PATH="${DB_BACKUP_LOG_PATH:-/tmp/baby-tracker-db-snapshots.log}"
CRON_MARKER="# baby-tracker-db-backups"
CRON_COMMAND="cd \"${REPO_ROOT}\" && ./scripts/backup-db-snapshots.sh >> \"${LOG_PATH}\" 2>&1"
CRON_ENTRY="${CRON_SCHEDULE} ${CRON_COMMAND} ${CRON_MARKER}"

if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab is not installed on this system." >&2
  exit 1
fi

existing_crontab="$(mktemp)"
updated_crontab="$(mktemp)"
trap 'rm -f "${existing_crontab}" "${updated_crontab}"' EXIT

if ! crontab -l >"${existing_crontab}" 2>/dev/null; then
  : >"${existing_crontab}"
fi

grep -Fv "${CRON_MARKER}" "${existing_crontab}" >"${updated_crontab}" || true
printf '%s\n' "${CRON_ENTRY}" >>"${updated_crontab}"

crontab "${updated_crontab}"

echo "Installed cron entry:"
echo "${CRON_ENTRY}"
