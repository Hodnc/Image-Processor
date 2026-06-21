# processor.py
# ---------------------------------------------------------------------------
# Wraps the fast-alpr library with clean input/output types and error handling.
#
# The rest of the application (watcher and API) never import fast-alpr
# directly — they only talk to this module.  That means if we ever need to
# swap the ALPR engine for a different library, we only change this file.
#
# How the two-stage ALPR pipeline works:
#   1. DETECTOR  — a YOLOv9 model scans the full image and outputs bounding
#                  boxes around every region that looks like a licence plate.
#   2. OCR MODEL — each detected region is cropped and fed into a MobileViT
#                  model that reads the text character by character.
#
# Both models run locally using ONNX Runtime (CPU).  No internet connection
# or API key is required once the Docker image is built.
# ---------------------------------------------------------------------------

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2           # OpenCV — used to load image files and decode byte payloads
import numpy as np   # NumPy — OpenCV returns images as NumPy arrays
from fast_alpr import ALPR

from alpr_service.config import DETECTOR_MODEL, OCR_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
# Using @dataclass gives us simple value objects with no boilerplate.
# These are returned by the public methods below so callers get a consistent
# structure regardless of whether zero, one, or multiple plates were found.
# ---------------------------------------------------------------------------

@dataclass
class PlateResult:
    """A single detected licence plate and its recognition metadata."""
    plate_text: str             # The plate string, e.g. "ABC123", normalised to uppercase
    confidence: float           # 0.0–1.0 — how confident the OCR model is
    processing_duration_ms: float  # Total time for this image, in milliseconds


@dataclass
class ProcessingResult:
    """The outcome of processing one image — may contain zero or more plates."""
    plates: list[PlateResult]       # Empty list when no plates were found
    processing_duration_ms: float   # Total processing time in milliseconds
    error: Optional[str] = None     # Set to an error message if something went wrong

    @property
    def success(self) -> bool:
        # Convenience property — True when no error occurred.
        # Note: success=True does NOT mean a plate was found; an image with
        # no plates still has success=True but an empty plates list.
        return self.error is None


# ---------------------------------------------------------------------------
# ALPRProcessor
# ---------------------------------------------------------------------------

class ALPRProcessor:
    """Loads the ALPR models once and exposes methods to process images."""

    def __init__(self) -> None:
        logger.info(
            "Loading ALPR models (detector=%s, ocr=%s)…", DETECTOR_MODEL, OCR_MODEL
        )
        # ALPR() instantiation downloads the ONNX model files if they are not
        # already cached, then loads them into memory ready for inference.
        # This happens once at startup — subsequent calls to predict() reuse
        # the already-loaded models and are therefore fast.
        self._alpr = ALPR(detector_model=DETECTOR_MODEL, ocr_model=OCR_MODEL)
        logger.info("ALPR models loaded successfully.")

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def process_file(self, image_path: Path) -> ProcessingResult:
        """Load an image from disk and run ALPR on it."""
        start = time.perf_counter()
        try:
            # cv2.imread reads the image file from disk and decodes it into a
            # NumPy array with shape (height, width, 3) in BGR colour order.
            # It returns None (not an exception) if the file cannot be decoded.
            img = cv2.imread(str(image_path))
            if img is None:
                # Return a structured error rather than raising — the caller
                # can then log it and move the file without crashing.
                return ProcessingResult(
                    plates=[],
                    processing_duration_ms=0.0,
                    error=f"Could not decode image '{image_path.name}' — file may be corrupt or unsupported.",
                )
            return self._run(img, start)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception("Unexpected error processing file %s", image_path)
            return ProcessingResult(
                plates=[], processing_duration_ms=round(elapsed, 2), error=str(exc)
            )

    def process_bytes(self, data: bytes, filename: str = "<upload>") -> ProcessingResult:
        """Decode a raw image byte payload (e.g. from an HTTP upload) and run ALPR."""
        start = time.perf_counter()
        try:
            # np.frombuffer interprets the raw bytes as a 1-D array of uint8
            # values.  cv2.imdecode then parses that array as if it were an
            # image file (auto-detecting JPEG, PNG, etc.) and returns the same
            # kind of NumPy (h, w, 3) array that cv2.imread would produce.
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return ProcessingResult(
                    plates=[],
                    processing_duration_ms=0.0,
                    error=f"Could not decode uploaded image '{filename}' — file may be corrupt or unsupported.",
                )
            return self._run(img, start)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception("Unexpected error processing upload %s", filename)
            return ProcessingResult(
                plates=[], processing_duration_ms=round(elapsed, 2), error=str(exc)
            )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _run(self, img: np.ndarray, start: float) -> ProcessingResult:
        """Run the two-stage ALPR pipeline on a decoded image array."""

        # fast-alpr's predict() runs both the detector and the OCR model.
        # It returns a list of ALPRResult objects — one per detected plate.
        # An empty list means no plates were found in the image.
        raw = self._alpr.predict(img)

        # Measure total elapsed time now that inference is complete.
        elapsed = round((time.perf_counter() - start) * 1000, 2)

        plates: list[PlateResult] = []
        for r in raw:
            # r.ocr is None if the detector found a plate-shaped region but
            # the OCR model could not extract any text from it.
            if r.ocr is None or not r.ocr.text:
                continue

            # r.ocr.confidence can be either:
            #   • A single float  — overall confidence for the whole plate string
            #   • A list of floats — one confidence value per recognised character
            # We normalise both cases to a single representative float by
            # averaging the list when needed.
            confidence = r.ocr.confidence
            if isinstance(confidence, list):
                confidence = sum(confidence) / len(confidence) if confidence else 0.0

            plates.append(
                PlateResult(
                    # .strip() removes accidental whitespace; .upper() ensures
                    # consistent casing regardless of what the model outputs.
                    plate_text=r.ocr.text.strip().upper(),
                    confidence=round(float(confidence), 4),
                    processing_duration_ms=elapsed,
                )
            )

        return ProcessingResult(plates=plates, processing_duration_ms=elapsed)
