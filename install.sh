#!/usr/bin/env bash
# Install Intelligence alone, or choose an Arch desktop feature set.
set -euo pipefail

python_bin="${PYTHON:-python3}"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
destination="$repo_root/.venv"
mode=""
help_requested=false
arguments=("$@")
for argument in "${arguments[@]}"; do
    case "$argument" in
        --arch|--core)
            if [[ -n "$mode" && "$mode" != "${argument#--}" ]]; then
                printf 'Choose either --arch or --core, not both.\n' >&2
                exit 2
            fi
            mode="${argument#--}" ;;
        --help|-h) help_requested=true ;;
    esac
done
if [[ "$help_requested" == true && "$mode" != arch ]]; then
    printf '%s\n' \
        'Usage: ./install.sh [--core] [--destination VENV] [--python PATH]' \
        '       ./install.sh --arch [--features LIST] [--dry-run] [--yes]' \
        '' \
        'Without a mode: interactive chooser in a terminal; core-only otherwise.' \
        'Arch setup configures an existing Arch installation; it does not install the OS.' \
        'Run ./install.sh --arch --help for features and provisioning options.'
    exit 0
fi
if [[ -z "$mode" && $# -eq 0 && -t 0 && -t 1 ]]; then
    printf '%s\n' 'Quattro setup' '  1) Intelligence only (isolated Python environment)' \
        '  2) Arch desktop with selectable features'
    read -r -p 'Choose [1]: ' choice
    case "$choice" in
        ""|1) mode=core ;;
        2) mode=arch ;;
        *) printf 'Invalid selection.\n' >&2; exit 2 ;;
    esac
fi
mode="${mode:-core}"
forward=()
while (($#)); do
    case "$1" in
        --core|--arch) shift ;;
        --python) python_bin="${2:?missing interpreter}"; shift 2 ;;
        --destination)
            if [[ "$mode" == arch ]]; then
                printf '%s\n' '--destination is for core-only installs.' >&2
                exit 2
            fi
            destination="${2:?missing destination}"; shift 2 ;;
        *) forward+=("$1"); shift ;;
    esac
done
if [[ "$mode" == arch ]]; then
    if ! command -v "$python_bin" >/dev/null 2>&1; then
        if [[ "$python_bin" != python3 || ! -f /etc/arch-release ]]; then
            printf 'Python 3.11+ is required; interpreter unavailable: %s\n' "$python_bin" >&2
            exit 1
        fi
        for argument in "${forward[@]}"; do
            case "$argument" in
                --dry-run|--help|-h)
                    printf '%s\n' 'Python bootstrap prerequisite: sudo pacman -Syu --needed python' \
                        'No changes made. Install Python, then rerun to see the complete feature plan.'
                    exit 0 ;;
                --home|--home=*|--skip-packages)
                    printf '%s\n' 'File-only setup requires Python 3.11+ already installed; no packages changed.' >&2
                    exit 1 ;;
            esac
        done
        if ((EUID == 0)) || ! command -v sudo >/dev/null || ! command -v pacman >/dev/null; then
            printf '%s\n' 'Arch bootstrap requires a normal user with sudo and pacman.' >&2
            exit 1
        fi
        printf '%s\n' 'Installing the Python prerequisite before feature selection; pacman requests confirmation.'
        sudo pacman -Syu --needed python
    fi
    exec "$python_bin" "$repo_root/scripts/setup_arch.py" "${forward[@]}"
fi
if ((${#forward[@]})); then
    printf 'Unknown core option: %s\n' "${forward[0]}" >&2
    exit 2
fi
exec "$python_bin" "$repo_root/scripts/install_local.py" --destination "$destination"
