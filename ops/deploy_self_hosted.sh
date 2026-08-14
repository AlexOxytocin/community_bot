#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: deploy_self_hosted.sh IMAGE_REFERENCE [BOOTSTRAP_TELEGRAM_ID]" >&2
  exit 2
fi

root_dir="${COMMUNITY_BOT_ROOT:-/opt/community-bot}"
compose_file="${root_dir}/current/compose.production.yaml"
env_file="${root_dir}/shared/.env"
image_reference="$1"
state_dir="${root_dir}/shared/releases"

if [[ ! -f "${compose_file}" || ! -f "${env_file}" ]]; then
  echo "Deployment files are missing." >&2
  exit 1
fi

if [[ -L "${env_file}" || "$(stat -c '%u:%a' "${env_file}")" != "0:600" ]]; then
  echo "Production environment file must be a root-owned regular file with mode 0600." >&2
  exit 1
fi

if [[ ! "${image_reference}" =~ ^ghcr\.io/.+@sha256:[0-9a-f]{64}$ ]] \
  && [[ ! "${image_reference}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Production deployment requires an immutable image digest or image ID." >&2
  exit 1
fi

install -d -m 700 "${state_dir}"
current_file="${state_dir}/current-image"
previous_file="${state_dir}/previous-image"
if [[ -f "${current_file}" ]]; then
  cp "${current_file}" "${previous_file}"
fi

export COMMUNITY_BOT_IMAGE="${image_reference}"
export COMMUNITY_BOT_ENV_FILE="${env_file}"
export COMMUNITY_BOT_RELEASE="${COMMUNITY_BOT_RELEASE:-${image_reference##*@}}"
compose=(docker compose --project-directory "${root_dir}/current" --env-file "${env_file}" -f "${compose_file}")

if [[ "${image_reference}" == ghcr.io/* ]]; then
  docker pull "${image_reference}"
elif ! docker image inspect "${image_reference}" >/dev/null 2>&1; then
  echo "The requested immutable image is not loaded." >&2
  exit 1
fi

"${compose[@]}" up -d postgres
"${compose[@]}" run --rm migrate
if [[ $# -eq 2 ]]; then
  "${compose[@]}" run --rm migrate community-bootstrap-admin \
    --telegram-user-id "$2" \
    --reason "${COMMUNITY_BOT_BOOTSTRAP_REASON:-initial_install}"
fi
"${compose[@]}" run --rm migrate community-bootstrap-product-config
"${compose[@]}" up -d --no-deps --force-recreate worker
worker_not_before="$(date -u +'%Y-%m-%dT%H:%M:%S.%NZ')"

wait_for_health() {
  local service="$1"
  local expected_process="$2"
  local not_before="$3"
  local attempt
  for attempt in {1..30}; do
    if "${compose[@]}" exec -T "${service}" community-health \
      --process "${expected_process}" \
      --not-before "${not_before}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Service did not become healthy: ${service}" >&2
  return 1
}

wait_for_health worker community-worker "${worker_not_before}"
"${compose[@]}" up -d --no-deps --force-recreate bot
bot_not_before="$(date -u +'%Y-%m-%dT%H:%M:%S.%NZ')"
wait_for_health bot community-bot "${bot_not_before}"
printf '%s\n' "${image_reference}" >"${current_file}"
chmod 600 "${current_file}"
"${compose[@]}" ps
