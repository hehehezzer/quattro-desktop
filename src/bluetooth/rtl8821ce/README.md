# Realtek RTL8821CE Bluetooth USB ID fix

This desktop's Bluetooth adapter is USB `13d3:3558`. The installed Arch
7.2.6 `btusb` module lacks this ID in its Realtek quirk table, so it binds as
a generic Bluetooth USB device and skips the Realtek firmware initialization.
The sole code change to the upstream Linux 7.2.6 driver is the two-line USB ID
entry beside the existing RTL8821CE IDs. The C source and private headers here
come from the Linux stable `v7.2.6` tag (GPL-2.0-or-later).

`scripts/install_rtl8821ce_bluetooth_fix.sh` installs this as a DKMS override
for exactly `7.2.6-arch2-1`. It requires `dkms` and matching `linux-headers`.
It does not unload the active driver. Reboot into that kernel after installation.
Review the override at each kernel update and remove it once the upstream ID
entry is in the packaged kernel; DKMS may need a new source version for a newer
kernel API.
