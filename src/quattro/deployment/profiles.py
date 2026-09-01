"""Independent Core and Linux Desktop deployment ownership.

The file inventory is metadata only.  Core operation never opens or validates a
Desktop source path unless the Desktop profile is explicitly requested.
"""
from __future__ import annotations

CORE_DEPLOYMENT_MAPPINGS = {
    "launcher": ("src/quattro-agent", ".local/bin/quattro-agent"),
    "harness": ("src/quattro_harness.py", ".local/bin/quattro_harness.py"),
    "deployment": ("src/quattro_deployment.py", ".local/bin/quattro_deployment.py"),
    "release": ("src/quattro_release.py", ".local/bin/quattro_release.py"),
    "memory": ("src/quattro_memory.py", ".local/bin/quattro_memory.py"),
    "pr-review": ("src/quattro_pr_review.py", ".local/bin/quattro_pr_review.py"),
    "model-catalog": (
        "src/quattro/omniroute-model-catalog.json",
        ".local/share/quattro-ai/codex/omniroute-model-catalog.json",
    ),
    **{
        f"core-{name.removesuffix('.py')}":
            (f"src/quattro_agent/{name}", f".local/bin/quattro_agent/{name}")
        for name in (
            "__init__.py", "__main__.py", "adapters.py", "benchmark.py", "cli.py",
            "collaboration.py", "config.py", "containment.py", "delegation.py", "errors.py",
            "mandatory_context.py", "models.py", "omniroute.py", "paths.py", "policy.py",
            "privacy.py", "recovery.py", "retrieval.py", "routing.py", "scheduler.py",
            "sessions.py", "store.py", "supervisor.py", "terminal_lifecycle.py",
            "validators.py", "workflow.py",
        )
    },
    **{
        f"namespace-{relative.replace('/', '-').removesuffix('.py')}":
            (f"src/quattro/{relative}", f".local/bin/quattro/{relative}")
        for relative in (
            "__init__.py", "core/__init__.py", "adapters/__init__.py",
            "cli/__init__.py", "cli/__main__.py", "platform/__init__.py",
            "platform/directories.py", "platform/executables.py", "platform/locking.py",
            "platform/processes.py", "platform/filesystem.py", "deployment/__init__.py", "deployment/profiles.py",
            "deployment/migration.py",
        )
    },
}

DESKTOP_DEPLOYMENT_MAPPINGS = {
    "menu-helper": ("src/quattro-menu", ".local/bin/quattro-menu"),
    "session-helper": ("src/quattro-session", ".local/bin/quattro-session"),
    "theme-helper": ("src/quattro-theme", ".local/bin/quattro-theme"),
    "night-light-helper": ("src/quattro-night-light", ".local/bin/quattro-night-light"),
    "pointer-helper": ("src/quattro-pointer", ".local/bin/quattro-pointer"),
    "system-stats-helper": ("src/quattro-system-stats", ".local/bin/quattro-system-stats"),
    "agents-qml": ("src/quickshell/components/Agents.qml", ".config/quickshell/components/Agents.qml"),
    "bar-qml": ("src/quickshell/components/Bar.qml", ".config/quickshell/components/Bar.qml"),
    "clipboard-qml": ("src/quickshell/components/Clipboard.qml", ".config/quickshell/components/Clipboard.qml"),
    "main-menu-qml": ("src/quickshell/components/MainMenu.qml", ".config/quickshell/components/MainMenu.qml"),
    "notifications-qml": ("src/quickshell/components/Notifications.qml", ".config/quickshell/components/Notifications.qml"),
    "system-panels-qml": ("src/quickshell/components/SystemPanels.qml", ".config/quickshell/components/SystemPanels.qml"),
    "system-stats-qml": ("src/quickshell/components/SystemStats.qml", ".config/quickshell/components/SystemStats.qml"),
    "theme-background-qml": ("src/quickshell/components/ThemeBackground.qml", ".config/quickshell/components/ThemeBackground.qml"),
    "theme-controller-qml": ("src/quickshell/components/ThemeController.qml", ".config/quickshell/components/ThemeController.qml"),
    "audio-panel-qml": ("src/quickshell/components/panels/AudioPanel.qml", ".config/quickshell/components/panels/AudioPanel.qml"),
    "bluetooth-panel-qml": ("src/quickshell/components/panels/BluetoothPanel.qml", ".config/quickshell/components/panels/BluetoothPanel.qml"),
    "clock-panel-qml": ("src/quickshell/components/panels/ClockPanel.qml", ".config/quickshell/components/panels/ClockPanel.qml"),
    "network-panel-qml": ("src/quickshell/components/panels/NetworkPanel.qml", ".config/quickshell/components/panels/NetworkPanel.qml"),
    "panel-button-qml": ("src/quickshell/components/shared/PanelButton.qml", ".config/quickshell/components/shared/PanelButton.qml"),
    "small-button-qml": ("src/quickshell/components/shared/SmallButton.qml", ".config/quickshell/components/shared/SmallButton.qml"),
    "shell-qml": ("src/quickshell/shell.qml", ".config/quickshell/shell.qml"),
    "theme-qml": ("src/quickshell/theme/Theme.qml", ".config/quickshell/theme/Theme.qml"),
    "theme-qmldir": ("src/quickshell/theme/qmldir", ".config/quickshell/theme/qmldir"),
    "hypr-bindings": ("src/hypr/bindings.lua", ".config/hypr/bindings.lua"),
    "hypr-config": ("src/hypr/hyprland.lua", ".config/hypr/hyprland.lua"),
    "foot-config": ("src/foot/foot.ini", ".config/foot/foot.ini"),
    "usage-service": ("src/systemd/quattro-agent-usage.service", ".config/systemd/user/quattro-agent-usage.service"),
    "usage-timer": ("src/systemd/quattro-agent-usage.timer", ".config/systemd/user/quattro-agent-usage.timer"),
    "reconcile-service": ("src/systemd/quattro-agent-reconcile.service", ".config/systemd/user/quattro-agent-reconcile.service"),
    "reconcile-timer": ("src/systemd/quattro-agent-reconcile.timer", ".config/systemd/user/quattro-agent-reconcile.timer"),
}

# Versioned Desktop cleanup policy. These are never consulted by Core deploys.
DESKTOP_RETIRED_PATHS = {
    ".local/share/quattro/wallpapers/avengers-doomsday.png",
}

# Import compatibility for code that historically treated deployment as one unit.
DEPLOYMENT_MAPPINGS = {**CORE_DEPLOYMENT_MAPPINGS, **DESKTOP_DEPLOYMENT_MAPPINGS}
