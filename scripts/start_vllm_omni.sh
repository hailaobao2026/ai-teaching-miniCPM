#!/usr/bin/env bash
# Start the vLLM-Omni MiniCPM-o 4.5 online serving endpoint.
# Official equivalent:
#   vllm serve openbmb/MiniCPM-o-4_5 --omni --trust-remote-code --host 0.0.0.0 --port 8099
#
# Environment overrides:
#   VLLM_OMNI_MODEL          HF id or local checkpoint (default: openbmb/MiniCPM-o-4_5)
#   VLLM_OMNI_PORT           Listen port (default: 8099)
#   VLLM_OMNI_HOST           Bind host (default: 127.0.0.1)
#   VLLM_API_KEY             Required API key when binding beyond loopback
#   VLLM_OMNI_DEPLOY_CONFIG  Optional deploy YAML (e.g. minicpmo_4_5_2gpu.yaml)
#   VLLM_OMNI_COMMAND        CLI binary (default: vllm, falls back to venv path)
#   VLLM_OMNI_EXTRA_ARGS     Extra args string, split on whitespace

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model="${VLLM_OMNI_MODEL:-openbmb/MiniCPM-o-4_5}"
port="${VLLM_OMNI_PORT:-8099}"
host="${VLLM_OMNI_HOST:-127.0.0.1}"
config="${VLLM_OMNI_DEPLOY_CONFIG:-}"
vllm_command="${VLLM_OMNI_COMMAND:-vllm}"
venv_vllm="${repo_root}/.venv-vllm-omni/bin/vllm"
api_key="${VLLM_API_KEY:-}"

is_loopback=0
case "${host}" in
  127.0.0.1|::1|localhost) is_loopback=1 ;;
esac
if [[ "${is_loopback}" -eq 0 && -z "${api_key}" ]]; then
  if [[ "${VLLM_OMNI_ALLOW_NO_API_KEY:-false}" == "true" ]]; then
    printf '[start_vllm_omni] WARNING: public listener runs without API authentication.\n' >&2
  else
    printf 'Refusing to bind %s without VLLM_API_KEY. Generate one with:\n  python3 -c '"'"'import secrets; print(secrets.token_urlsafe(32))'"'"'\n' "${host}" >&2
    exit 1
  fi
fi
if [[ -n "${api_key}" && "${#api_key}" -lt 32 ]]; then
  printf 'VLLM_API_KEY must contain at least 32 characters.\n' >&2
  exit 1
fi

if ! command -v "${vllm_command}" >/dev/null 2>&1; then
  if [[ -x "${venv_vllm}" ]]; then
    vllm_command="${venv_vllm}"
  else
    printf 'vllm CLI not found. Install GPU deps first:\n  %s/scripts/install_vllm_omni.sh\n' "${repo_root}" >&2
    exit 1
  fi
fi

args=(serve "${model}" --omni --trust-remote-code --host "${host}" --port "${port}")
if [[ -n "${api_key}" ]]; then
  args+=(--api-key "${api_key}")
fi
if [[ -n "${config}" ]]; then
  args+=(--deploy-config "${config}")
fi
if [[ -n "${VLLM_OMNI_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  extra=( ${VLLM_OMNI_EXTRA_ARGS} )
  args+=("${extra[@]}")
fi

printable_args=()
for value in "${args[@]}"; do
  if [[ "${value}" == "${api_key}" && -n "${api_key}" ]]; then
    printable_args+=("<redacted-api-key>")
  else
    printable_args+=("${value}")
  fi
done
printf '[start_vllm_omni] %s %s\n' "${vllm_command}" "${printable_args[*]}"
exec "${vllm_command}" "${args[@]}"
