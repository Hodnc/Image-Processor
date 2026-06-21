# watcher.py
# ---------------------------------------------------------------------------
# Directory watcher — automatically processes images dropped into INPUT_DIR.
#
# The flow for each image is:
#   1. PollingObserver detects a new file in INPUT_DIR
#   2. ImageEventHandler.on_created() is called with the file path
#   3. We wait until the file is fully written (size stops changing)
#   4. ALPRProcessor runs the two-stage detection + OCR pipeline
#   5. The result is written to the daily CSV log
#   6. The file is moved to PROCESSED_DIR so it won't be processed again
#
# Why PollingObserver instead of the default Observer?
#   On Windows and macOS, Docker bind-mounts the host filesystem into the
#   Linux container using a virtual bridge.  The Linux kernel's inotify
#   subsystem (which the default Observer relies on) never sees filesystem
#   events that originate from the host side of that bridge.  PollingObserver
#   bypasses inotify entirely — it simply scans the directory on a fixed
#   interval and compares the directory listing to what it saw last time.
#   This is slightly less instantaneous but works reliably on every platform.
# ---------------------------------------------------------------------------

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from alpr_service.processor import ALPRProcessor, PlateResult, ProcessingResult
from alpr_service.config import INPUT_DIR, PROCESSED_DIR, SUPPORTED_EXTENSIONS
from alpr_service.logger import CSVLogger, LogEntry

logger = logging.getLogger(__name__)


class ImageEventHandler(FileSystemEventHandler):
    """
    Handles filesystem events from the PollingObserver.

    watchdog calls on_created() or on_moved() each time it detects a change
    in the watched directory.  Both methods funnel into _handle() which does
    the real work.
    """

    def __init__(self, processor: ALPRProcessor, csv_logger: CSVLogger) -> None:
        self._processor = processor
        self._csv_logger = csv_logger
        # Ensure the destination directory exists before we try to move files there.
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # watchdog event callbacks
    # -----------------------------------------------------------------------

    def on_created(self, event: FileCreatedEvent) -> None:
        # Called when a new file appears in the watched directory.
        # We ignore directory creation events (e.g. someone creates a subfolder).
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        # Called when a file is renamed or moved *into* the watched directory.
        # Some tools (e.g. cp on Linux) write to a temp file first then rename
        # it — we need this handler to catch that final rename.
        if not event.is_directory:
            self._handle(Path(event.dest_path))

    # -----------------------------------------------------------------------
    # Core processing logic
    # -----------------------------------------------------------------------

    def _handle(self, path: Path) -> None:
        """Entry point for a candidate file — filter, wait, then process."""
        # Skip files that aren't images we support (e.g. .txt, .DS_Store).
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        # Guard against a race where the file disappears between detection
        # and processing (e.g. moved away by another process).
        if not path.exists():
            return
        # Wait for the file to finish being written before we try to read it.
        self._wait_stable(path)
        self._process_and_move(path)

    def _wait_stable(self, path: Path, retries: int = 6, interval: float = 0.4) -> None:
        """
        Poll the file size until it stops changing.

        When a large image is being copied into INPUT_DIR the file appears
        immediately but its contents arrive progressively.  Reading a
        partially-written file would produce a corrupt image.  We check the
        size every `interval` seconds; once two consecutive readings match
        we assume the write is complete.
        """
        prev = -1
        for _ in range(retries):
            try:
                size = path.stat().st_size
            except OSError:
                # File temporarily inaccessible — wait and retry.
                time.sleep(interval)
                continue
            if size == prev:
                return   # Size is stable; safe to proceed.
            prev = size
            time.sleep(interval)
        # If we exhaust all retries we proceed anyway — better to try and
        # get a partial-read error than to silently drop the file.

    def _process_and_move(self, path: Path) -> None:
        """Run ALPR, log the result, and move the file to PROCESSED_DIR."""
        logger.info("Watcher: processing '%s'", path.name)

        # Hand the image file to the ALPR pipeline.
        result: ProcessingResult = self._processor.process_file(path)

        # Capture the current UTC time as an ISO 8601 string for the log.
        now = datetime.now(timezone.utc).isoformat()

        if result.error:
            # Something went wrong (e.g. corrupt file).  Log it and move on.
            self._write_log(now, path.name, result.processing_duration_ms, "", "", "error", result.error)
            logger.warning("Error processing '%s': %s", path.name, result.error)

        elif not result.plates:
            # The image was valid but no plate was found in it.
            self._write_log(now, path.name, result.processing_duration_ms, "", "", "no_plate_found", "")
            logger.info("No plates found in '%s'", path.name)

        else:
            # One or more plates were found.  Write a separate CSV row for
            # each plate so the log stays flat and easy to query.
            for plate in result.plates:
                self._write_plate_log(now, path.name, plate, result.processing_duration_ms)
            logger.info(
                "Found %d plate(s) in '%s': %s",
                len(result.plates),
                path.name,
                [p.plate_text for p in result.plates],
            )

        # Move the file to PROCESSED_DIR regardless of outcome so it is never
        # re-processed if the container restarts.
        dest = self._unique_dest(path)
        try:
            shutil.move(str(path), str(dest))
            logger.debug("Moved '%s' -> '%s'", path.name, dest.name)
        except OSError as exc:
            logger.error("Could not move '%s' to processed dir: %s", path.name, exc)

    # -----------------------------------------------------------------------
    # CSV helpers
    # -----------------------------------------------------------------------

    def _write_log(
        self,
        ts: str,
        filename: str,
        duration_ms: float,
        plate_text: str,
        confidence: str,
        status: str,
        error: str,
    ) -> None:
        """Build and write a LogEntry for any outcome (success, no plate, or error)."""
        self._csv_logger.write(
            LogEntry(
                timestamp=ts,
                filename=filename,
                source="watcher",   # Always "watcher" from this module
                plate_text=plate_text,
                confidence=confidence,
                processing_duration_ms=str(round(duration_ms, 2)),
                status=status,
                error=error,
            )
        )

    def _write_plate_log(
        self, ts: str, filename: str, plate: PlateResult, duration_ms: float
    ) -> None:
        """Convenience wrapper — writes one success row per detected plate."""
        self._write_log(
            ts=ts,
            filename=filename,
            duration_ms=duration_ms,
            plate_text=plate.plate_text,
            confidence=str(plate.confidence),
            status="success",
            error="",
        )

    # -----------------------------------------------------------------------
    # Destination path helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _unique_dest(path: Path) -> Path:
        """
        Return a path in PROCESSED_DIR that does not already exist.

        If 'car.jpg' is already in processed/, this returns 'car_1.jpg',
        then 'car_2.jpg', and so on — preventing silent overwrites.
        """
        dest = PROCESSED_DIR / path.name
        if not dest.exists():
            return dest
        counter = 1
        while dest.exists():
            dest = PROCESSED_DIR / f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        return dest


# ---------------------------------------------------------------------------
# Startup scan
# ---------------------------------------------------------------------------

def _scan_existing(handler: ImageEventHandler) -> None:
    """
    Process any images already sitting in INPUT_DIR when the service starts.

    The watcher only catches events that happen *after* it starts.  If images
    were copied into INPUT_DIR while the container was stopped, this function
    ensures they are not silently skipped on the next startup.
    """
    existing = [
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not existing:
        return
    logger.info(
        "Found %d pre-existing image(s) in input dir — processing now.", len(existing)
    )
    for path in existing:
        handler._process_and_move(path)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def start_watcher(processor: ALPRProcessor, csv_logger: CSVLogger) -> PollingObserver:
    """
    Set up and start the directory watcher.  Returns the observer so the
    caller (main.py) can stop it cleanly on shutdown.
    """
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    handler = ImageEventHandler(processor, csv_logger)

    # Process anything already in the input directory before the live watcher
    # starts — this covers files dropped while the container was offline.
    _scan_existing(handler)

    # PollingObserver scans INPUT_DIR every `timeout` seconds and calls the
    # handler's on_created / on_moved methods for any changes it detects.
    observer = PollingObserver(timeout=3)
    observer.schedule(handler, str(INPUT_DIR), recursive=False)
    observer.start()
    logger.info("Watcher started (polling every 3s), watching '%s'", INPUT_DIR)
    return observer
