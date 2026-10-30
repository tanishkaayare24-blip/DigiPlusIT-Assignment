"""All business constants live here so rules are easy to find and change."""

# --- Meetings -------------------------------------------------------------
MEETING_TYPES = ("meeting", "handover")
MEETING_STATUSES = ("draft", "scheduled", "completed", "archived")
MEETING_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"scheduled", "archived"},
    "scheduled": {"completed", "draft", "archived"},
    "completed": {"archived"},
    "archived": set(),
}
ATTENDANCE_VALUES = ("yes", "no", "no_response")

# --- Action items ---------------------------------------------------------
ITEM_STATUSES = ("open", "in_progress", "blocked", "done", "dropped")
CLOSED_ITEM_STATUSES = {"done", "dropped"}
PRIORITIES = ("low", "medium", "high")

# Item event types (rows in item_events)
EV_CREATED = "created"
EV_STATUS = "status_changed"
EV_REASSIGNED = "reassigned"
EV_CARRIED = "carried_over"
EV_CLOSED = "closed"
EV_UPDATED = "updated"
EV_NUDGED = "nudge_sent"

# --- AI -------------------------------------------------------------------
AI_MAX_ATTEMPTS = 2  # first try + 1 retry, then fallback
AI_MAX_TOKENS = 4000
AI_PURPOSES = ("recap", "brief", "link", "nudge")
LINK_SHORTLIST_SIZE = 6
LINK_MAX_RESULTS = 4
LINK_MIN_SCORE = 0.05

# --- Handoff Health Score -------------------------------------------------
# (penalty per occurrence, maximum total penalty for the rule)
HEALTH_RULES: dict[str, tuple[int, int]] = {
    "no_owner": (10, 30),
    "no_due_date": (5, 20),
    "overdue": (10, 30),
    "stale_carry": (8, 24),
    "missed_no_brief": (8, 24),
    "decisions_no_kb": (10, 10),
    "handover_no_kb": (15, 15),
    "bus_factor": (10, 10),
}
STALE_CARRY_THRESHOLD = 2
BUS_FACTOR_SHARE = 0.6
BUS_FACTOR_MIN_ITEMS = 3
HEALTH_GREEN = 75
HEALTH_AMBER = 50
RISK_RADAR_LIMIT = 6
