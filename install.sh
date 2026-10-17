#!/usr/bin/env bash
# Install only the intelligence core in a repository-local virtual environment.
set -euo pipefail

python_bin="${PYTHON:-python3}"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
destination="$repo_root/.venv"
while (($#)); do
    case "$1" in
        --destination) destination="${2:?missing destination}"; shift 2 ;;
        --python) python_bin="${2:?missing interpreter}"; shift 2 ;;
        -h|--help)
            printf 'Usage: ./install.sh [--destination VENV] [--python PATH]\n'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
"$python_bin" "$repo_root/scripts/install_local.py" --destination "$destination"
