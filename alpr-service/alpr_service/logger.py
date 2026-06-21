# logger.py
# ---------------------------------------------------------------------------
# Thread-safe, daily-rolling CSV logger.
#
# Every image the service processes — whether it came from the directory
# watcher or the REST API — gets a row written here.  A new file is created
# automatically each day so logs stay manageable and are easy to archive.
#
# "Thread-safe" is important because the watcher and the API server run
# concurrently.  Without a lock, two threads could try to write to the same
# file at the same time, producing garbled rows.  The threading.Lock() below
# ensures only one thread writes at a time.
# ---------------------------------------------------------------------------

import csv
import logging
import threading
from dataclasses import astuple, dataclass, fields
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LogEntry — one row in the CSV
# ---------------------------------------------------------------------------
# Using a @dataclass here gives us:
#   • A clear list of every column in one place
#   • Free __init__ so we can construct entries with keyword arguments
#   • astuple() which converts the row to a plain tuple for csv.writer
#
# All values are stored as strings so csv.writer never has to guess how to
# format a float or datetime — we control the exact output ourselves.
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    timestamp: str           # ISO 8601 UTC, e.g. "2026-06-21T03:32:54+00:00"
    filename: str            # Original filename, e.g. "car.jpg"
    source: str              # "api" when sent via POST, "watcher" when auto-detected
    plate_text: str          # The recognised plate string, e.g. "ABC123" (empty if none)
    confidence: str          # Detection confidence 0–1 as a string (empty if no plate)
    processing_duration_ms: str  # How long ALPR took, in milliseconds
    status: str              # "success", "no_plate_found", or "error"
    error: str               # Human-readable error message (empty on success)


# Build the CSV header row automatically from the field names defined above.
# This means if you ever add or rename a field on LogEntry, the header
# updates itself — no chance of them getting out of sync.
_HEADERS = [f.name for f in fields(LogEntry)]


# ---------------------------------------------------------------------------
# CSVLogger
# ---------------------------------------------------------------------------

class CSVLogger:
    """Appends LogEntry rows to a daily CSV file, creating a new file each day."""

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        # threading.Lock() is a mutual-exclusion primitive.  Calling
        # `with self._lock:` blocks any other thread from entering the same
        # block until the first thread exits it — preventing concurrent writes.
        self._lock = threading.Lock()
        # Ensure the log directory exists before we try to write to it.
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_today(self) -> Path:
        # Build today's log file path.  date.today() is evaluated each time
        # this method is called, so the logger automatically rolls over to a
        # new file at midnight without any extra scheduling needed.
        return self._log_dir / f"alpr_{date.today().isoformat()}.csv"

    def _ensure_header(self, path: Path) -> None:
        # Write the header row only if the file is brand new (doesn't exist
        # yet) or somehow ended up empty.  We never want duplicate headers
        # in the middle of a log file.
        if not path.exists() or path.stat().st_size == 0:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(_HEADERS)

    def write(self, entry: LogEntry) -> None:
        # Acquire the lock — only one thread can be inside this block at once.
        with self._lock:
            path = self._path_for_today()
            try:
                self._ensure_header(path)
                # Open in append mode ("a") so we add to the end of the file
                # rather than overwriting it.  newline="" is required by the
                # csv module on Windows to avoid double line endings.
                with open(path, "a", newline="", encoding="utf-8") as fh:
                    # astuple() converts the LogEntry dataclass into a plain
                    # tuple, which csv.writer then writes as a single row.
                    csv.writer(fh).writerow(astuple(entry))
            except OSError as exc:
                # Log the failure but don't raise — a CSV write error should
                # never crash the main processing pipeline.
                logger.error("Failed to write CSV log entry: %s", exc)
