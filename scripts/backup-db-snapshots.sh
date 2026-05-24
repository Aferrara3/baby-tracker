#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SNAPSHOT_ROOT="${REPO_ROOT}/db-snapshots"
TIMESTAMP="$(date '+%Y-%m-%dT%H-%M-%S')"
SNAPSHOT_DIR="${SNAPSHOT_ROOT}/${TIMESTAMP}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mapfile -t DB_FILES < <(
  find "${REPO_ROOT}" \
    \( \
      -path "${REPO_ROOT}/.git" -o \
      -path "${REPO_ROOT}/backend/venv" -o \
      -path "${REPO_ROOT}/frontend/node_modules" -o \
      -path "${SNAPSHOT_ROOT}" \
    \) -prune -o \
    -type f -name '*.db' -print | sort
)

if [ "${#DB_FILES[@]}" -eq 0 ]; then
  echo "No .db files found under ${REPO_ROOT}" >&2
  exit 1
fi

mkdir -p "${SNAPSHOT_DIR}"

for db_file in "${DB_FILES[@]}"; do
  relative_path="${db_file#${REPO_ROOT}/}"
  target_path="${SNAPSHOT_DIR}/${relative_path}"
  mkdir -p "$(dirname -- "${target_path}")"
  cp -p -- "${db_file}" "${target_path}"
done

find "${SNAPSHOT_ROOT}" \
  -mindepth 1 \
  -maxdepth 1 \
  -type d \
  -mtime "+${RETENTION_DAYS}" \
  -exec rm -rf -- {} +

echo "Created DB snapshot in ${SNAPSHOT_DIR}"
