#!/usr/bin/env bash
set -euo pipefail

root_dir="${COMMUNITY_BOT_ROOT:-/opt/community-bot}"
env_file="${root_dir}/shared/.env"
backup_dir="${COMMUNITY_BOT_BACKUP_DIR:-/var/backups/community-bot}"
compose_file="${root_dir}/current/compose.production.yaml"
current_image_file="${root_dir}/shared/releases/current-image"

if [[ ! -f "${env_file}" || ! -f "${current_image_file}" ]]; then
  echo "Production environment file is missing." >&2
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
install -d -m 700 "${backup_dir}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="${backup_dir}/.${POSTGRES_DB}-${timestamp}.dump.part"
target="${backup_dir}/${POSTGRES_DB}-${timestamp}.dump"
compose=(docker compose --project-directory "${root_dir}/current" --env-file "${env_file}" -f "${compose_file}")

umask 077
"${compose[@]}" exec -T postgres pg_dump \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --format custom \
  --no-owner \
  --no-privileges >"${temporary}"
test -s "${temporary}"
mv "${temporary}" "${target}"
find "${backup_dir}" -maxdepth 1 -type f -name '*.dump' -mtime +7 -delete
printf '%s\n' "${target}"
