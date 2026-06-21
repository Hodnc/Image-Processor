# config.py
# ---------------------------------------------------------------------------
# Central configuration for the ALPR service.
#
# Every setting is read from an environment variable so the same Docker image
# can be used in development, staging, and production just by changing the
# values passed to the container — no code changes required.
#
# If an environment variable is not set, the default value (second argument
# to os.getenv) is used instead.
# ---------------------------------------------------------------------------

from pathlib import Path
import os

# ---------------------------------------------------------------------------
# Directory paths
# ---------------------------------------------------------------------------

# INPUT_DIR: the folder the watcher monitors for incoming images.
# Drop any supported image file here and the service will process it
# automatically, then move it to PROCESSED_DIR.
INPUT_DIR = Path(os.getenv("INPUT_DIR", "/data/input"))

# PROCESSED_DIR: after a file in INPUT_DIR is processed (successfully or not)
# it is moved here so it is no longer re-processed on the next restart.
PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", "/data/processed"))

# LOG_DIR: daily CSV log files are written here.
# One file per day, named  alpr_YYYY-MM-DD.csv
LOG_DIR = Path(os.getenv("LOG_DIR", "/data/logs"))

# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------

# HOST: the network interface for the API server to listen on.
# "0.0.0.0" means accept connections on all interfaces, which is required
# inside Docker so traffic from outside the container can reach it.
HOST = os.getenv("HOST", "0.0.0.0")

# PORT: the TCP port the API server binds to inside the container.
# docker-compose.yml maps this to a port on your host machine.
PORT = int(os.getenv("PORT", "8080"))

# ---------------------------------------------------------------------------
# Supported image formats
# ---------------------------------------------------------------------------

# Only files with these extensions are processed.  Any other file type
# dropped into INPUT_DIR is silently ignored so the watcher never chokes
# on README files, .DS_Store, etc.
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

# ---------------------------------------------------------------------------
# ALPR model names
# ---------------------------------------------------------------------------

# These are the names of the two ONNX models that power plate recognition.
# They are downloaded from Hugging Face the first time they are needed and
# cached in /root/.cache/ inside the container.  The Dockerfile pre-downloads
# them at build time so the service starts instantly with no internet needed.

# DETECTOR_MODEL: a YOLOv9 model that locates the bounding box of every
# licence plate in the image.
DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"

# OCR_MODEL: a CCT model that reads the text from each detected plate
# region found by the detector above.
OCR_MODEL = "cct-s-v2-global-model"
