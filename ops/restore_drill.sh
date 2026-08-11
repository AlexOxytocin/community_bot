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
  --command "
DO \$\$
BEGIN
  IF (SELECT version_num FROM alembic_version) <> '0010' THEN
    RAISE EXCEPTION 'Unexpected Alembic revision in restored database.';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM members AS member
    LEFT JOIN (
      SELECT
        member_id,
        COALESCE(SUM(credit_delta), 0) AS credit_total,
        COALESCE(SUM(experience_delta), 0) AS experience_total
      FROM account_transactions
      GROUP BY member_id
    ) AS ledger ON ledger.member_id = member.id
    WHERE member.credit_balance_cached <> COALESCE(ledger.credit_total, 0)
       OR member.experience_total_cached <> COALESCE(ledger.experience_total, 0)
  ) THEN
    RAISE EXCEPTION 'Ledger reconciliation failed in restored database.';
  END IF;
END
\$\$;
SELECT version_num AS alembic_revision FROM alembic_version;
SELECT count(*) AS members_count FROM members;
SELECT count(*) AS account_transactions_count FROM account_transactions;
SELECT 0 AS ledger_mismatch_count;
"
