"""Interactive Agent access; this package never starts a model or Provider."""

PROFILE = "hypertest.interactive-mcp/v1alpha1"
MAX_MESSAGE = 1_000_000
EXECUTION_TOOLS = frozenset({
    "get_state", "request_mission", "complete_mission", "request_execution",
    "ask_user", "evaluate_gate", "submit_report", "request_gitlab_issue", "get_issue",
})
