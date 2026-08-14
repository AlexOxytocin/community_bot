#!/usr/bin/env bash
set -euo pipefail

readonly PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

validate_only=0
test_mode=0
root_dir="/opt/community-bot"
if [[ $# -eq 2 && "$1" == "--validate-command" ]]; then
  original_command="$2"
  validate_only=1
elif [[ $# -eq 3 && "$1" == "--test-deploy" ]]; then
  root_dir="$2"
  original_command="$3"
  test_mode=1
elif [[ $# -eq 0 ]]; then
  original_command="${SSH_ORIGINAL_COMMAND:-}"
else
  echo "Rejected deployment command." >&2
  exit 2
fi
readonly original_command validate_only test_mode root_dir
readonly state_dir="${root_dir}/shared/releases"
readonly lock_file="${state_dir}/github-deploy.lock"
readonly marker_file="${state_dir}/github-deploy-sequence"
readonly trusted_bin_dir="${root_dir}/shared/bin"
readonly deploy_script="${trusted_bin_dir}/deploy_self_hosted.sh"

if [[ "${original_command}" == *$'\n'* || "${original_command}" == *$'\r'* ]]; then
  echo "Rejected deployment command." >&2
  exit 2
fi

readonly command_pattern='^deploy ([1-9][0-9]{0,17}) ([1-9][0-9]{0,17}) ([0-9a-f]{40}) (ghcr\.io/alexgoodman53/community_bot@sha256:[0-9a-f]{64})$'
if [[ ! "${original_command}" =~ ${command_pattern} ]]; then
  echo "Rejected deployment command." >&2
  exit 2
fi

readonly run_number="${BASH_REMATCH[1]}"
readonly run_attempt="${BASH_REMATCH[2]}"
readonly commit_sha="${BASH_REMATCH[3]}"
readonly image_reference="${BASH_REMATCH[4]}"

if [[ "${validate_only}" == "1" ]]; then
  exit 0
fi

if [[ "${test_mode}" != "1" && "$(id -u)" != "0" ]]; then
  echo "Deployment entrypoint must run as root." >&2
  exit 1
fi
trusted_uid=0
if [[ "${test_mode}" == "1" ]]; then
  trusted_uid="$(id -u)"
fi
root_mode="$(stat -c '%a' "${root_dir}")"
if [[ "$(stat -c '%u' "${root_dir}")" != "${trusted_uid}" ]] \
  || (( (8#${root_mode} & 8#022) != 0 )); then
  echo "Deployment root has unsafe ownership or mode." >&2
  exit 1
fi
for trusted_dir in "${root_dir}/shared" "${trusted_bin_dir}"; do
  if [[ ! -d "${trusted_dir}" || -L "${trusted_dir}" ]] \
    || [[ "$(stat -c '%u:%a' "${trusted_dir}")" != "${trusted_uid}:700" ]]; then
    echo "Trusted deployment directory has unsafe ownership or mode." >&2
    exit 1
  fi
done
if [[ ! -f "${deploy_script}" || ! -x "${deploy_script}" || -L "${deploy_script}" ]] \
  || [[ "$(stat -c '%u:%a' "${deploy_script}")" != "${trusted_uid}:700" ]]; then
  echo "Trusted deployment script has unsafe ownership or mode." >&2
  exit 1
fi

if [[ "${test_mode}" == "1" ]]; then
  mkdir -p "${state_dir}"
  chmod 700 "${state_dir}"
else
  install -d -o root -g root -m 700 "${state_dir}"
fi
exec 9>"${lock_file}"
flock -x 9

if [[ -f "${marker_file}" ]]; then
  read -r current_number current_attempt _ <"${marker_file}"
  if [[ ! "${current_number:-}" =~ ^[1-9][0-9]*$ ]] \
    || [[ ! "${current_attempt:-}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Deployment sequence marker is invalid." >&2
    exit 1
  fi
  if (( run_number < current_number )) \
    || (( run_number == current_number && run_attempt <= current_attempt )); then
    echo "Stale or duplicate deployment rejected." >&2
    exit 3
  fi
fi

COMMUNITY_BOT_RELEASE="${image_reference##*@}.run${run_number}.${run_attempt}" \
  "${deploy_script}" "${image_reference}"

marker_tmp="$(mktemp "${state_dir}/github-deploy-sequence.XXXXXX")"
trap 'rm -f "${marker_tmp:-}"' EXIT
printf '%s %s %s %s\n' \
  "${run_number}" "${run_attempt}" "${commit_sha}" "${image_reference}" >"${marker_tmp}"
chmod 600 "${marker_tmp}"
mv -f "${marker_tmp}" "${marker_file}"
trap - EXIT
