#!/usr/bin/env bash
# Install the upstream Realtek USB ID fix for the installed Arch 7.2.6 kernel.
set -euo pipefail

version=7.2.6-1
kernel=7.2.6-arch2-1
name=quattro-btusb-rtl8821ce
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../src/bluetooth/rtl8821ce" && pwd)"
target="/usr/src/$name-$version"

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this installer with sudo; do not paste your password into Quattro." >&2
    exit 1
fi
if ! lsusb -d 13d3:3558 | grep -q '13d3:3558'; then
    echo "Expected Realtek Bluetooth adapter 13d3:3558 was not found." >&2
    exit 1
fi
if [[ ! -d "/usr/lib/modules/$kernel/build" ]] || ! command -v dkms >/dev/null; then
    echo "Install dkms and matching linux-headers ($kernel) first." >&2
    exit 1
fi
if [[ "$(pacman -Q linux)" != "linux 7.2.6.arch2-1" ]]; then
    echo "Installed kernel changed; review the patch against the new kernel first." >&2
    exit 1
fi

install -d -m 0755 "$target"
install -m 0644 "$source_dir"/{Makefile,dkms.conf,btusb.c,btbcm.h,btintel.h,btmtk.h,btrtl.h} "$target/"
if ! dkms status -m "$name" -v "$version" | grep -q '^quattro-btusb-rtl8821ce/'; then
    dkms add -m "$name" -v "$version"
fi
dkms build -m "$name" -v "$version" -k "$kernel"
dkms install -m "$name" -v "$version" -k "$kernel"
depmod "$kernel"
module_path="$(modinfo -k "$kernel" -n btusb)"
case "$module_path" in
    */updates/dkms/btusb.ko*) printf 'Installed patched btusb: %s\n' "$module_path" ;;
    *) echo "Patched module was built but does not take precedence: $module_path" >&2; exit 1 ;;
esac
printf 'Reboot into %s to activate the patched driver.\n' "$kernel"
