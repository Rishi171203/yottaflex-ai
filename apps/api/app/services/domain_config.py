"""Domain configuration constants (defaults documented in docs/decisions)."""

FIVE_PRIORITY_CODES = ("P1", "P2", "P3", "P4")

SYSTEM_MESSAGES_COUNT_AS_RESPONSE = False  # D-Q4; flip in one place if rubric differs

# languages / locales (D-Q3)
SUPPORTED_LANGUAGES = ("en", "hi", "ta", "es", "fr", "de", "ja", "pt", "ko")
DEFAULT_PREFERRED_LANGUAGE = "en"
MIN_AGENT_PROFICIENCY = 3  # AgentLanguage.proficiency cutoff for assignment eligibility

# SLA policy matrix (D-Q2): (clock_type, priority) → (first_response_minutes, resolution_minutes)
SLA_POLICY_MATRIX: dict[tuple[str, str], tuple[int, int]] = {
    ("calendar", "P1"): (60, 1440),
    ("calendar", "P2"): (240, 2880),
    ("calendar", "P3"): (480, 5760),
    ("calendar", "P4"): (1440, 11520),
    ("business", "P1"): (30, 480),
    ("business", "P2"): (60, 1440),
    ("business", "P3"): (240, 2880),
    ("business", "P4"): (480, 5760),
}

# Lifecycle & calendar policy windows (D-Q8 / §14.4)
CLOSE_AFTER_BUSINESS_DAYS = 10
REOPEN_AFTER_CLOSE_WINDOW_DAYS = 30

# Anomaly framework (D-Q1)
ANOMALY_CODES = (
    "ANOM-CAPACITY-OVERLOAD",
    "ANOM-SLA-CALENDAR-IGNORED",
    "ANOM-REOPEN-HISTORY-LOSS",
    "ANOM-TRANSFER-LOOP",
    "ANOM-PRIORITY-SAFETY-VIOLATION",
)
