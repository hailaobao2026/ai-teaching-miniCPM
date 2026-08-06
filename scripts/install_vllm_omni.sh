#!/usr/bin/env bash
# Install the MiniCPM-o 4.5 GPU inference stack (vLLM + vLLM-Omni + Talker deps)
# into an isolated virtualenv. Follows the official vLLM-Omni 0.26 CUDA recipe:
#   uv pip install vllm==0.26.0 --torch-backend=auto
#   uv pip install vllm-omni==0.26.0
#   uv pip install stepaudio2-minicpmo==0.1.1
#
# Usage:
#   ./scripts/install_vllm_omni.sh
#   ./scripts/install_vllm_omni.sh --write-lock
#   ./scripts/install_vllm_omni.sh --from-lock
#   ./scripts/install_vllm_omni.sh --help
#
# Environment overrides:
#   VLLM_OMNI_VENV          Virtualenv path (default: <repo>/.venv-vllm-omni)
#   VLLM_OMNI_PYTHON        Host Python used to create the venv (default: python3.12)
#   VLLM_OMNI_LOCK_FILE     Lock file path (default: <repo>/requirements-gpu.lock.txt)
#   VLLM_OMNI_REQUIREMENTS  Requirements file (default: <repo>/requirements-gpu.txt)
#   VLLM_OMNI_SKIP_GPU_CHECK=1   Skip nvidia-smi check (docs/CI only)
#   UV_INDEX_URL / PIP_INDEX_URL  Optional mirror indexes

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="${VLLM_OMNI_VENV:-${repo_root}/.venv-vllm-omni}"
lock_file="${VLLM_OMNI_LOCK_FILE:-${repo_root}/requirements-gpu.lock.txt}"
requirements_file="${VLLM_OMNI_REQUIREMENTS:-${repo_root}/requirements-gpu.txt}"

write_lock=0
from_lock=0
skip_gpu_check="${VLLM_OMNI_SKIP_GPU_CHECK:-0}"

usage() {
  cat <<USAGE
Install vLLM-Omni MiniCPM-o 4.5 GPU dependencies into a dedicated venv.

Options:
  --write-lock   After install, freeze the resolved environment to the lock file
  --from-lock    Install exactly from requirements-gpu.lock.txt (must already exist)
  -h, --help     Show this help

Examples:
  ./scripts/install_vllm_omni.sh --write-lock
  VLLM_OMNI_VENV=/opt/venvs/vllm-omni ./scripts/install_vllm_omni.sh
  ./scripts/install_vllm_omni.sh --from-lock
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --write-lock)
      write_lock=1
      shift
      ;;
    --from-lock)
      from_lock=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[install_vllm_omni] %s\n' "$*"
}

die() {
  printf '[install_vllm_omni] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  local name="$1"
  command -v "${name}" >/dev/null 2>&1 || die "Required command not found: ${name}"
}

if [[ "$(uname -s)" != "Linux" ]]; then
  die "vLLM-Omni MiniCPM-o 4.5 requires a Linux GPU host."
fi

if [[ "${skip_gpu_check}" != "1" ]]; then
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    die "nvidia-smi was not found. Run on a host with NVIDIA drivers, or set VLLM_OMNI_SKIP_GPU_CHECK=1 for dry docs/CI."
  fi
  log "NVIDIA driver:"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
else
  log "Skipping nvidia-smi check (VLLM_OMNI_SKIP_GPU_CHECK=1)."
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  log "WARNING: ffmpeg not found on PATH. MiniCPM-o audio/video media IO expects system ffmpeg; install it with your package manager if media requests fail."
fi

if [[ "${from_lock}" -eq 1 && ! -f "${lock_file}" ]]; then
  die "Lock file not found: ${lock_file}. Run without --from-lock first, then --write-lock on a verified GPU host."
fi

if [[ "${from_lock}" -eq 0 && ! -f "${requirements_file}" ]]; then
  die "Missing requirements file: ${requirements_file}"
fi

python_cmd="${VLLM_OMNI_PYTHON:-python3.12}"
require_cmd "${python_cmd}"

if ! "${python_cmd}" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
  die "Python 3.12 is required for this pinned vLLM-Omni 0.26 environment (got: $(${python_cmd} -V 2>&1)). Set VLLM_OMNI_PYTHON to a 3.12 interpreter."
fi

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  log "Creating virtualenv at ${venv_dir}"
  "${python_cmd}" -m venv "${venv_dir}"
elif ! "${venv_dir}/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
  die "Existing venv is not Python 3.12: ${venv_dir}. Set VLLM_OMNI_VENV to a new path or remove the old venv."
fi

venv_python="${venv_dir}/bin/python"
venv_uv="${venv_dir}/bin/uv"
export VIRTUAL_ENV="${venv_dir}"
export PATH="${venv_dir}/bin:${PATH}"

# Prefer uv (official install path). Bootstrap it into the venv when missing.
log "Bootstrapping pip / uv in ${venv_dir}"
"${venv_python}" -m pip install --upgrade pip setuptools wheel
if [[ ! -x "${venv_uv}" ]]; then
  "${venv_python}" -m pip install --upgrade uv
fi
require_cmd uv

parse_pinned_requirement() {
  # Read "name==version" from requirements-gpu.txt, ignoring comments/blank lines.
  local package="$1"
  local line
  line="$(
    grep -E "^${package}==" "${requirements_file}" | head -n 1 || true
  )"
  if [[ -z "${line}" ]]; then
    die "Package pin for '${package}' not found in ${requirements_file}"
  fi
  printf '%s\n' "${line}"
}

install_from_requirements() {
  [[ -f "${requirements_file}" ]] || die "Missing requirements file: ${requirements_file}"

  local vllm_pin vllm_omni_pin stepaudio_pin
  vllm_pin="$(parse_pinned_requirement vllm)"
  vllm_omni_pin="$(parse_pinned_requirement vllm-omni)"
  stepaudio_pin="$(parse_pinned_requirement stepaudio2-minicpmo)"

  log "Installing ${vllm_pin} with CUDA torch backend auto-selection"
  # Official CUDA recipe: choose a torch wheel compatible with the host CUDA driver.
  # Do not pin torch/torchaudio ourselves; vLLM resolves them via --torch-backend=auto.
  uv pip install --python "${venv_python}" "${vllm_pin}" --torch-backend=auto

  log "Installing ${vllm_omni_pin}"
  # Keep omni on the same minor line as vLLM (0.26.x).
  uv pip install --python "${venv_python}" "${vllm_omni_pin}"

  log "Installing MiniCPM-o Talker/Code2Wav dependency ${stepaudio_pin}"
  # Code2Wav needs the MiniCPM-flavored package, not upstream step-audio2.
  uv pip install --python "${venv_python}" "${stepaudio_pin}"

  # Install any additional pins listed in requirements-gpu.txt (future-proof).
  # Re-running the known pins above is intentional and idempotent.
  if grep -E '^[A-Za-z0-9_.-]+' "${requirements_file}" | grep -Ev '^(vllm|vllm-omni|stepaudio2-minicpmo)==' >/dev/null 2>&1; then
    log "Installing remaining entries from ${requirements_file}"
    uv pip install --python "${venv_python}" -r "${requirements_file}"
  fi
}

install_from_lock() {
  [[ -f "${lock_file}" ]] || die "Lock file not found: ${lock_file}. Run without --from-lock first, then --write-lock on a verified GPU host."
  log "Installing frozen environment from ${lock_file}"
  # Lock files are host/CUDA/Python specific. Still pass torch-backend when
  # torch lines are present so uv can validate the CUDA wheel family.
  uv pip install --python "${venv_python}" -r "${lock_file}" --torch-backend=auto
}

if [[ "${from_lock}" -eq 1 ]]; then
  install_from_lock
else
  install_from_requirements
fi

log "Running pip check"
"${venv_python}" -m pip check

log "Verifying imports and versions"
"${venv_python}" - <<'PY'
import importlib
import importlib.metadata as md
import importlib.util

def ver(mod_name: str) -> str:
    mod = importlib.import_module(mod_name)
    return getattr(mod, "__version__", "installed")

print("vLLM", ver("vllm"))
print("vLLM-Omni", ver("vllm_omni"))

# Distribution name is stepaudio2-minicpmo; import path can differ by release.
try:
    dist_ver = md.version("stepaudio2-minicpmo")
except md.PackageNotFoundError as exc:
    raise SystemExit("stepaudio2-minicpmo distribution is not installed") from exc
print("stepaudio2-minicpmo", dist_ver)
if importlib.util.find_spec("stepaudio2_minicpmo") is not None:
    print("stepaudio2_minicpmo importable", True)

# Torch is pulled in by vLLM; surface CUDA visibility for operators.
import torch
print("torch", torch.__version__)
print("torch.cuda.is_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("torch.cuda.device_count", torch.cuda.device_count())
    print("torch.version.cuda", torch.version.cuda)
PY

if [[ ! -x "${venv_dir}/bin/vllm" ]]; then
  die "vllm CLI was not installed into ${venv_dir}/bin"
fi

if [[ "${write_lock}" -eq 1 ]]; then
  log "Writing resolved lock file to ${lock_file}"
  {
    printf '# Host-resolved GPU lock for MiniCPM-o 4.5 / vLLM-Omni.\n'
    printf '# Do not reuse across different CUDA drivers, GPU arches, or Python versions.\n'
    printf '# Generated: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# Host: %s\n' "$(uname -a)"
    if command -v nvidia-smi >/dev/null 2>&1; then
      printf '# nvidia-smi: %s\n' "$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | paste -sd ';' -)"
    fi
    # Capture the full host-resolved environment (CUDA/Python specific).
    uv pip freeze --python "${venv_python}" | sort
  } > "${lock_file}"
  log "Wrote ${lock_file}"
fi

cat <<EOF

GPU dependencies installed in:
  ${venv_dir}

Activate:
  source ${venv_dir}/bin/activate

Start MiniCPM-o 4.5 (default port 8099):
  ${repo_root}/scripts/start_vllm_omni.sh

Recommended 2-GPU deploy config (after activate):
  python -c "import pathlib, vllm_omni; print(pathlib.Path(vllm_omni.__file__).resolve().parent / 'deploy' / 'minicpmo_4_5_2gpu.yaml')"
  export VLLM_OMNI_DEPLOY_CONFIG=/path/from/above
  ${repo_root}/scripts/start_vllm_omni.sh

Point the Web app at the model server:
  export VLLM_OMNI_URL=http://127.0.0.1:8099
EOF
