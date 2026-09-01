#!/usr/bin/env bash
# Linux convenience installer. Windows uses: py -m pip install .
set -euo pipefail

profile="core"
python_bin="${PYTHON:-python3}"
while (($#)); do
    case "$1" in
        --profile) profile="${2:?missing profile}"; shift 2 ;;
        --python) python_bin="${2:?missing interpreter}"; shift 2 ;;
        -h|--help)
            printf 'Usage: ./install.sh [--profile core|desktop] [--python PATH]\n'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
if [[ "$profile" != core && "$profile" != desktop ]]; then
    printf 'Profile must be core or desktop\n' >&2
    exit 2
fi
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
"$python_bin" -m pip install "$repo_root"
if [[ "$profile" == desktop ]]; then
    if [[ "$(uname -s)" != Linux ]]; then
        printf 'Quattro Desktop is supported only on Linux. Core is installed.\n' >&2
        exit 2
    fi
    QUATTRO_WORKSPACE="$repo_root" quattro-agent deployment deploy --profile desktop
fi
printf 'Installed Quattro %s profile. Run: quattro-agent doctor\n' "$profile"
