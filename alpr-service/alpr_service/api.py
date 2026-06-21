# api.py
# ---------------------------------------------------------------------------
# REST API — exposes HTTP endpoints for submitting images and checking health.
#
# Built with FastAPI, which is a modern Python web framework that:
#   • Automatically generates interactive docs at /docs (Swagger UI)
#   • Validates request and response data using Pydantic models
#   • Is async-native, meaning it can handle many concurrent requests
#     without blocking (important when ALPR processing takes ~100-300ms)
#
# Endpoints
# ---------
#   GET  /health         — simple liveness check
#   POST /api/process    — upload an image, receive plate data as JSON
# ---------------------------------------------------------------------------

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from alpr_service.processor import ALPRProcessor
from alpr_service.config import SUPPORTED_EXTENSIONS
from alpr_service.logger import CSVLogger, LogEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models (Pydantic)
# ---------------------------------------------------------------------------
# Pydantic BaseModel classes do two things:
#   1. Define the exact JSON structure that the API returns
#   2. Automatically validate and serialise the data — if we accidentally
#      return a field with the wrong type, Pydantic raises an error before
#      the response is sent rather than returning garbage to the client.
# ---------------------------------------------------------------------------

class PlateResponse(BaseModel):
    """JSON representation of one detected licence plate."""
    plate_text: str               # e.g. "ABC123"
    detection_confidence: float   # 0.0–1.0
    ocr_confidence: float         # 0.0–1.0
    processing_duration_ms: float # Total time for this image


class ProcessResponse(BaseModel):
    """JSON response body returned by POST /api/process."""
    filename: str                   # The original filename sent by the client
    plates: list[PlateResponse]     # Empty list when no plate was found
    processing_duration_ms: float   # Total time for this image
    status: str                     # "success" | "no_plate_found" | "plate_found_unreadable"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
# create_app() is a factory function rather than a module-level `app = FastAPI()`.
# This pattern lets main.py pass in the already-initialised processor and logger
# so all three components share the same instances — avoiding loading the
# ALPR models a second time.
# ---------------------------------------------------------------------------

def create_app(processor: ALPRProcessor, csv_logger: CSVLogger) -> FastAPI:
    app = FastAPI(
        title="ALPR Service",
        version="1.0.0",
        description="Automatic Licence Plate Recognition — local ONNX inference, no external API required.",
    )

    # -----------------------------------------------------------------------
    # GET /health
    # -----------------------------------------------------------------------

    @app.get("/health", tags=["Ops"])
    async def health() -> dict:
        """
        Liveness check — returns 200 OK when the service is running.

        Useful for Docker health checks, load balancers, or just quickly
        confirming the container is up.  Does not test ALPR functionality.
        """
        return {"status": "ok"}

    # -----------------------------------------------------------------------
    # POST /api/process
    # -----------------------------------------------------------------------

    @app.post("/api/process", response_model=ProcessResponse, tags=["ALPR"])
    async def process_image(file: UploadFile = File(...)) -> ProcessResponse:
        """
        Accept an image upload and return any detected licence plates as JSON.

        The request must be multipart/form-data with a field named `file`.
        The response includes the plate text, confidence score, and the time
        taken to process the image.  A separate row is written to the daily
        CSV log for each detected plate (or one row if none were found).
        """

        # UploadFile.filename comes from the Content-Disposition header in the
        # multipart request.  It can theoretically be empty or None.
        filename = file.filename or ""
        if not filename:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Request must include a named file."
            )

        # Reject file types we don't support before reading the body —
        # saves bandwidth and gives the client a clear error message.
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Unsupported file type '{ext}'. "
                    f"Accepted: {sorted(SUPPORTED_EXTENSIONS)}"
                ),
            )

        # Read the entire file body into memory as bytes.
        # `await` is used here because this is an async function — it yields
        # control back to the event loop while waiting for the network I/O,
        # allowing other requests to be handled concurrently.
        data = await file.read()
        if not data:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty."
            )

        # Pass the raw bytes to the ALPR processor for decoding and inference.
        result = processor.process_bytes(data, filename=filename)
        now = datetime.now(timezone.utc).isoformat()

        # ---------------------------------------------------------------
        # Handle processing errors (e.g. corrupt image)
        # ---------------------------------------------------------------
        if result.error:
            csv_logger.write(
                LogEntry(
                    timestamp=now,
                    filename=filename,
                    source="api",
                    plate_text="",
                    detection_confidence="",
                    ocr_confidence="",
                    processing_duration_ms=str(round(result.processing_duration_ms, 2)),
                    status="error",
                    error=result.error,
                )
            )
            # 422 Unprocessable Entity — the request was well-formed but the
            # image content could not be processed.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result.error
            )

        # ---------------------------------------------------------------
        # No plate detected or plate detected but OCR could not read it
        # ---------------------------------------------------------------
        if result.status != "success":
            csv_logger.write(
                LogEntry(
                    timestamp=now,
                    filename=filename,
                    source="api",
                    plate_text="",
                    detection_confidence="",
                    ocr_confidence="",
                    processing_duration_ms=str(round(result.processing_duration_ms, 2)),
                    status=result.status,
                    error="",
                )
            )
            # Return 200 (not an error) — the request succeeded, but either
            # no plate was visible or OCR could not extract text.
            return ProcessResponse(
                filename=filename,
                plates=[],
                processing_duration_ms=result.processing_duration_ms,
                status=result.status,
            )

        # ---------------------------------------------------------------
        # One or more plates found — write one CSV row per plate
        # ---------------------------------------------------------------
        for plate in result.plates:
            csv_logger.write(
                LogEntry(
                    timestamp=now,
                    filename=filename,
                    source="api",
                    plate_text=plate.plate_text,
                    detection_confidence=str(plate.detection_confidence),
                    ocr_confidence=str(plate.ocr_confidence),
                    processing_duration_ms=str(round(result.processing_duration_ms, 2)),
                    status="success",
                    error="",
                )
            )

        return ProcessResponse(
            filename=filename,
            plates=[
                PlateResponse(
                    plate_text=p.plate_text,
                    detection_confidence=p.detection_confidence,
                    ocr_confidence=p.ocr_confidence,
                    processing_duration_ms=p.processing_duration_ms,
                )
                for p in result.plates
            ],
            processing_duration_ms=result.processing_duration_ms,
            status="success",
        )

    return app
