import os
import csv
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "session_log.csv")


def _ensure_log():
    """Create log directory and file with headers if they don't exist."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "user", "event", "detail"])


def log_event(user: str, event: str, detail: str = ""):
    """Append an event to the session log."""
    _ensure_log()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), user, event, detail])


def get_log():
    """Read the session log as a list of dicts."""
    _ensure_log()
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)
