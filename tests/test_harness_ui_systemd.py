from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
AGENTS_QML = ROOT / "src/quickshell/components/Agents.qml"
USAGE_SERVICE = ROOT / "src/systemd/quattro-agent-usage.service"
RECONCILE_SERVICE = ROOT / "src/systemd/quattro-agent-reconcile.service"
RECONCILE_TIMER = ROOT / "src/systemd/quattro-agent-reconcile.timer"


class HarnessUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qml = AGENTS_QML.read_text(encoding="utf-8")

    def test_control_center_uses_authoritative_dashboard_surfaces(self):
        self.assertIn("root.dashboard", self.qml)
        for surface in ("home", "tasks", "sessions", "knowledge", "system"):
            self.assertIn(f'target: "{surface}"', self.qml)
        for field in ("logicalSessions", "approvals", "project", "retrieval", "memory"):
            self.assertIn(field, self.qml)

    def test_durable_task_projection_is_defensive_and_complete(self):
        self.assertIn("Array.isArray(value)", self.qml)
        for field in ("taskId", "state", "phase", "agent", "validation", "children", "capabilities"):
            self.assertIn(field, self.qml)
        self.assertIn("No durable tasks", self.qml)

    def test_task_actions_use_argument_vector_contract(self):
        self.assertIn('invoke(["task", "show", String(identifier), "--json"]', self.qml)
        self.assertIn('["task", "retry", taskDetail.task.taskId, "--json"]', self.qml)
        self.assertIn('["task", "cancel", taskDetail.task.taskId, "--json"]', self.qml)
        self.assertIn("taskDetail.caps.retry", self.qml)
        self.assertIn("taskDetail.caps.cancel", self.qml)
        self.assertNotIn("bash -c", self.qml)
        self.assertNotIn("sh -c", self.qml)

    def test_running_sessions_can_be_stopped_and_omniroute_can_open(self):
        self.assertIn('["sessions", "open", modelData.coordinationSessionId || modelData.sessionId || modelData.taskId]', self.qml)
        self.assertIn('["sessions", "stop", modelData.coordinationSessionId || modelData.sessionId || modelData.taskId]', self.qml)
        self.assertIn('["resume", modelData.quattroSessionId]', self.qml)
        self.assertIn('["open", modelData.repository]', self.qml)

    def test_sessions_show_prompt_derived_titles_before_opaque_ids(self):
        self.assertIn('modelData.title || "Agent session"', self.qml)
        self.assertIn('root.shortId(modelData.quattroSessionId) + " · Last active "', self.qml)
        self.assertIn('Text { text: modelData.title || ((modelData.agent || "agent")', self.qml)
        self.assertIn('[root.agentCommand, "recent", "refresh"]', self.qml)

    def test_prompt_palette_knowledge_and_approval_contracts(self):
        self.assertIn('["submit", "--agent", selectedAgent', self.qml)
        self.assertIn('property string selectedAgent: "auto"', self.qml)
        self.assertIn("Qt.ShiftModifier", self.qml)
        self.assertIn("Qt.Key_K", self.qml)
        self.assertIn('"retrieval", "ui-search"', self.qml)
        self.assertIn('"memory", "ui-search"', self.qml)
        self.assertIn('["approval", approvalDecision, selectedApproval.approvalId, "--json"]', self.qml)
        self.assertIn("confirmOpen", self.qml)

    def test_account_switching_and_usage_limits_remain_available(self):
        self.assertIn('"account", "set", modelData.id', self.qml)
        self.assertIn('[root.agentCommand, "account", "list"]', self.qml)
        self.assertIn('id: accountStatusProcess', self.qml)
        self.assertIn('id: panelUsageProcess', self.qml)
        self.assertIn('interval: 2000', self.qml)
        self.assertIn('next.activeAccount = parsed.active', self.qml)
        self.assertIn('next.usage = parsed', self.qml)
        self.assertIn('"usage", "refresh", "--all"', self.qml)
        self.assertIn("CODEX ACCOUNT & LIMITS", self.qml)
        self.assertIn("% remaining", self.qml)
        self.assertIn("resetAt", self.qml)

    def test_expensive_operations_are_explicit_and_polling_stops_closed(self):
        self.assertIn('running: root.opened', self.qml)
        self.assertIn('interval: 15000', self.qml)
        self.assertIn('[root.agentCommand, "ui-state"]', self.qml)
        self.assertIn('root.startMaintenance("reindex")', self.qml)
        self.assertIn('root.startMaintenance("benchmark")', self.qml)
        self.assertNotIn('onTriggered: root.startMaintenance', self.qml)


class UsageServiceHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = USAGE_SERVICE.read_text(encoding="utf-8")

    def test_required_hardening_directives_are_present(self):
        for directive in (
            "UMask=0077",
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "ProtectSystem=strict",
            "ProtectHome=read-only",
        ):
            self.assertIn(directive, self.unit)

    def test_account_homes_allow_app_server_state_and_other_home_is_read_only(self):
        self.assertIn("ReadWritePaths=%h/.local/share/quattro-ai/codex/accounts", self.unit)
        self.assertIn("ReadOnlyPaths=%h/.config/quattro", self.unit)
        self.assertIn("ReadWritePaths=%h/.local/state/quattro/agents", self.unit)

    def test_loopback_omniroute_network_is_not_disabled(self):
        self.assertNotIn("PrivateNetwork=yes", self.unit)
        self.assertNotIn("IPAddressDeny=any", self.unit)


class ReconcileServiceTests(unittest.TestCase):
    def test_reconcile_is_bounded_hardened_and_periodic(self):
        service = RECONCILE_SERVICE.read_text(encoding="utf-8")
        timer = RECONCILE_TIMER.read_text(encoding="utf-8")
        self.assertIn("quattro-agent task reconcile", service)
        self.assertIn("TimeoutStartSec=30", service)
        self.assertIn("NoNewPrivileges=yes", service)
        self.assertIn("ReadWritePaths=%h/.local/state/quattro/agents", service)
        self.assertIn("OnCalendar=*-*-* *:*:00", timer)


if __name__ == "__main__":
    unittest.main()
