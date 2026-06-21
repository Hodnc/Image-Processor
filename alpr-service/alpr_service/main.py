# main.py
# ---------------------------------------------------------------------------
# Application entry point — wires everything together and starts the service.
#
# When you run `python -m alpr_service.main` (or the Docker CMD does it), this file:
#   1. Configures structured logging so every component writes consistent
#      timestamped messages to stdout
#   2. Creates the shared CSVLogger and ALPRProcessor instances
#   3. Starts the directory watcher in a background thread
#   4. Starts the FastAPI/uvicorn HTTP server in the main thread
#   5. Registers signal handlers so Ctrl+C or `docker stop` shuts everything
#      down cleanly (stops the watcher thread before exiting)
#
# Threading model
# ---------------
# The watcher (PollingObserver) runs in its own background thread managed by
# the watchdog library.  The uvicorn server runs in the main thread.  Both
# share the same ALPRProcessor and CSVLogger instances — thread safety is
# handled inside CSVLogger with a Lock.  ALPRProcessor is read-only after
# initialisation so it is inherently safe to share.
# ---------------------------------------------------------------------------

import logging
import signal
import sys

import uvicorn  # ASGI server that hosts the FastAPI application

from alpr_service.processor import ALPRProcessor
from alpr_service.api import create_app
from alpr_service.config import HOST, LOG_DIR, PORT
from alpr_service.logger import CSVLogger
from alpr_service.watcher import start_watcher

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
# basicConfig sets up the root logger.  Every logger in every module
# (created with `logging.getLogger(__name__)`) inherits this configuration.
#
# Format fields:
#   %(asctime)s   — timestamp using datefmt below
#   %(levelname)  — DEBUG / INFO / WARNING / ERROR / CRITICAL, padded to 8 chars
#   %(name)s      — the module name (e.g. "alpr_service.watcher")
#   %(message)s   — the actual log message
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,  # Print to stdout so Docker captures it with `docker logs`
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting ALPR Service…")

    # Create the CSV logger first — every other component needs it.
    csv_logger = CSVLogger(LOG_DIR)

    # Load the ALPR models into memory.  This is the slowest part of startup
    # (~1-2 seconds) but only happens once.
    processor = ALPRProcessor()

    # Start the directory watcher in a background thread.
    # start_watcher() also immediately processes any files already in INPUT_DIR
    # before the live polling begins.
    observer = start_watcher(processor, csv_logger)

    # Build the FastAPI application, injecting the shared processor and logger.
    app = create_app(processor, csv_logger)

    # -----------------------------------------------------------------------
    # Graceful shutdown handler
    # -----------------------------------------------------------------------
    # signal.signal() registers a callback that Python calls when it receives
    # a specific OS signal.
    #
    # SIGINT  — sent when you press Ctrl+C in the terminal
    # SIGTERM — sent by `docker stop` (Docker gives the process 10 seconds to
    #           clean up before sending SIGKILL)
    #
    # Without this handler the watcher thread would be killed mid-operation,
    # potentially leaving a file partially moved or a log entry missing.
    # -----------------------------------------------------------------------
    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Received signal %d — shutting down watcher…", signum)
        observer.stop()   # Tell the PollingObserver thread to stop after its current poll
        observer.join()   # Wait for the thread to finish cleanly
        logger.info("Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # -----------------------------------------------------------------------
    # Start the HTTP server
    # -----------------------------------------------------------------------
    # uvicorn.run() blocks the main thread indefinitely, serving HTTP requests.
    # log_config=None tells uvicorn not to reconfigure logging — we already
    # set it up above and don't want it overwritten.
    # -----------------------------------------------------------------------
    logger.info("API server listening on %s:%d", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_config=None)


if __name__ == "__main__":
    main()
