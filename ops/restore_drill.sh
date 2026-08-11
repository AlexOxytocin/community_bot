#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: restore_drill.sh BACKUP_FILE" >&2
  exit 2
fi

root_dir="${COMMUNITY_BOT_ROOT:-/opt/community-bot}"
env_file="${root_dir}/shared/.env"
compose_file="${root_dir}/current/compose.production.yaml"
current_image_file="${root_dir}/shared/releases/current-image"
backup_file="$1"
drill_database="community_bot_restore_drill"

if [[ ! -s "${backup_file}" || ! -f "${env_file}" || ! -f "${current_image_file}" ]]; then
  echo "Backup or environment file is missing." >&2
  exit 1
fi

if [[ -L "${env_file}" || "$(stat -c '%u:%a' "${env_file}")" != "0:600" ]]; then
  echo "Production environment file must be a root-owned regular file with mode 0600." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${env_file}"
set +a
export COMMUNITY_BOT_IMAGE="$(<"${current_image_file}")"
export COMMUNITY_BOT_ENV_FILE="${env_file}"
if [[ ! "${COMMUNITY_BOT_IMAGE}" =~ ^ghcr\.io/.+@sha256:[0-9a-f]{64}$ ]] \
  && [[ ! "${COMMUNITY_BOT_IMAGE}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Current image identity is invalid." >&2
  exit 1
fi
compose=(docker compose --project-directory "${root_dir}/current" --env-file "${env_file}" -f "${compose_file}")

cleanup() {
  "${compose[@]}" exec -T postgres dropdb \
    --username "${POSTGRES_USER}" \
    --if-exists \
    --force \
    "${drill_database}" >/dev/null
}
trap cleanup EXIT
cleanup
"${compose[@]}" exec -T postgres createdb \
  --username "${POSTGRES_USER}" \
  "${drill_database}"
"${compose[@]}" exec -T postgres pg_restore \
  --username "${POSTGRES_USER}" \
  --dbname "${drill_database}" \
  --no-owner \
  --no-privileges <"${backup_file}"
"${compose[@]}" exec -T postgres psql \
  --username "${POSTGRES_USER}" \
  --dbname "${drill_database}" \
  --set ON_ERROR_STOP=1 \
  --tuples-only \
  --command "SELECT version_num FROM alembic_version; SELECT count(*) FROM members; SELECT count(*) FROM account_transactions;"
