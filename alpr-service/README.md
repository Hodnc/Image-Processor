# ALPR Service

A self-contained, containerised Python service for **Automatic Licence Plate Recognition (ALPR)**. It runs entirely offline using local ONNX models — no external API key or internet connection is required at runtime.

Contributions, bug reports, and feature requests are welcome — see [Contributing](#contributing) below.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Project structure](#project-structure)
3. [Prerequisites](#prerequisites)
4. [Quick start — Docker Compose](#quick-start--docker-compose)
5. [Development — VS Code Dev Container](#development--vs-code-dev-container)
6. [Using the directory watcher](#using-the-directory-watcher)
7. [Using the REST API](#using-the-rest-api)
8. [Testing with Postman](#testing-with-postman)
9. [Testing with curl](#testing-with-curl)
10. [Reading the CSV logs](#reading-the-csv-logs)
11. [Configuration reference](#configuration-reference)
12. [API reference](#api-reference)
13. [Error handling behaviour](#error-handling-behaviour)
14. [How the ALPR pipeline works](#how-the-alpr-pipeline-works)
15. [Troubleshooting](#troubleshooting)
16. [Contributing](#contributing)
17. [License](#license)

---

## How it works

The service has two parallel modes of operation running inside a single container at the same time:

| Mode | How to trigger | What happens |
|---|---|---|
| **Directory watcher** | Copy an image into `data/input/` | File is processed automatically, result logged, file moved to `data/processed/` |
| **REST API** | `POST /api/process` with an image | Returns JSON with detected plates immediately |

Every processing event — whether a plate was found, no plate was found, or an error occurred — is appended to a daily rolling CSV log file in `data/logs/`.

---

## Project structure

```
alpr-service/
│
├── alpr_service/               Python package — all application code lives here
│   ├── __init__.py             Marks the directory as a Python package (empty)
│   ├── main.py                 Entry point — wires everything together and starts the service
│   ├── config.py               All configuration, read from environment variables
│   ├── processor.py            Wraps the fast-alpr library; runs detection + OCR
│   ├── logger.py               Thread-safe daily-rolling CSV logger
│   ├── watcher.py              Watches INPUT_DIR for new images using PollingObserver
│   └── api.py                  FastAPI HTTP endpoints (/health and /api/process)
│
├── data/                       Runtime data directories (mounted as Docker volumes)
│   ├── input/                  Drop images here for automatic processing
│   ├── processed/              Processed images are moved here automatically
│   └── logs/                   Daily CSV log files are written here
│
├── .devcontainer/
│   └── devcontainer.json       VS Code Dev Container configuration
│
├── .github/
│   ├── ISSUE_TEMPLATE/         Bug report and feature request templates
│   └── PULL_REQUEST_TEMPLATE.md
│
├── Dockerfile                  Builds the container image
├── docker-compose.yml          Defines the service, ports, and volume mounts
├── requirements.txt            Python package dependencies
├── CONTRIBUTING.md             How to contribute
├── LICENSE                     MIT licence
└── README.md                   This file
```

---

## Prerequisites

| Tool | Minimum version | Purpose |
|---|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 4.x | Build and run the container |
| [Docker Compose](https://docs.docker.com/compose/) | v2 (bundled with Docker Desktop) | Orchestrate the container |
| [VS Code](https://code.visualstudio.com/) + [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) | Any recent version | Optional — for interactive development |
| [Postman](https://www.postman.com/downloads/) | Any | Optional — for testing the API visually |

---

## Quick start — Docker Compose

This is the recommended way to run the service.

```bash
# 1. Clone the repository
git clone https://github.com/your-username/alpr-service.git
cd alpr-service

# 2. Build the Docker image and start the container.
#    The first build takes ~2-3 minutes because it downloads the ONNX models.
#    Subsequent builds are much faster because Docker caches the layers.
docker compose up --build

# You should see output like:
#   alpr-service-1 | Starting ALPR Service…
#   alpr-service-1 | ALPR models loaded successfully.
#   alpr-service-1 | Watcher started (polling every 3s)…
#   alpr-service-1 | Uvicorn running on http://0.0.0.0:8080
```

To run in the background (detached mode):

```bash
docker compose up --build -d

# View the logs at any time:
docker compose logs -f
```

To stop the service:

```bash
docker compose down
```

---

## Development — VS Code Dev Container

The Dev Container mounts your source code directly into the container. This means you can edit files in VS Code and see changes take effect immediately (after restarting the Python process) without rebuilding the Docker image.

**Steps:**

1. Open the `alpr-service/` folder in VS Code (`File → Open Folder…`).
2. VS Code will detect the `.devcontainer/devcontainer.json` file and show a prompt: **"Reopen in Container"** — click it.
   - Alternatively: press `Ctrl+Shift+P` and run `Dev Containers: Reopen in Container`.
3. VS Code will build the image and reopen the window inside the container. This takes a minute the first time.
4. Open a terminal inside VS Code (`Terminal → New Terminal`). You are now inside the Linux container.
5. Start the service:

   ```bash
   cd /workspace
   python -m alpr_service.main
   ```

6. The API is available at `http://localhost:8080` on your host machine.
7. Edit any file under `app/` in VS Code, stop the terminal process (`Ctrl+C`), and rerun `python -m app.main` to pick up the changes.

> **API-only development mode** (with auto-reload):
> ```bash
> cd /workspace
> uvicorn app.api:app --reload --host 0.0.0.0 --port 8080
> ```
> This restarts the API server automatically when you save a file. Note: the directory watcher does not run in this mode.

---

## Using the directory watcher

The watcher polls `data/input/` every 3 seconds. Any supported image file copied there will be processed automatically.

**Supported formats:** `.jpg` `.jpeg` `.png` `.bmp` `.tiff` `.tif` `.webp`

**Steps:**

```bash
# Copy an image into the input directory while the container is running
cp /path/to/your/car.jpg data/input/

# Within ~3 seconds you will see log output like:
#   Watcher: processing 'car.jpg'
#   Found 1 plate(s) in 'car.jpg': ['ABC123']
```

After processing:
- The image is moved to `data/processed/car.jpg`
- A row is appended to `data/logs/alpr_YYYY-MM-DD.csv`
- If a file with the same name is already in `processed/`, it is renamed `car_1.jpg`, `car_2.jpg`, etc.

**Files already in `input/` when the container starts** are processed immediately at startup before the live polling begins.

---

## Using the REST API

The API accepts images via HTTP POST and returns JSON. It is available at `http://localhost:8080` while the container is running.

Interactive documentation (Swagger UI) is available at:
```
http://localhost:8080/docs
```
This page lets you test every endpoint directly in the browser — no Postman or curl required.

---

## Testing with Postman

1. Open Postman and create a new request.
2. Set the method to **POST**.
3. Set the URL to `http://localhost:8080/api/process`.
4. Click the **Body** tab.
5. Select **form-data**.
6. In the key field, type `file`.
7. Hover over the key field — a dropdown appears on the right side. Change it from **Text** to **File**.
8. In the value column, click **Select Files** and choose an image from your computer.
9. Click **Send**.

**Example successful response:**

```json
{
    "filename": "car.jpg",
    "plates": [
        {
            "plate_text": "ABC123",
        "detection_confidence": 0.9912,
        "ocr_confidence": 0.9871,
            "processing_duration_ms": 148.3
        }
    ],
    "processing_duration_ms": 148.3,
    "status": "success"
}
```

**Example response when no plate is found:**

```json
{
    "filename": "landscape.jpg",
    "plates": [],
    "processing_duration_ms": 112.4,
    "status": "no_plate_found"
}
```

**Testing the health endpoint:**

1. Create a new request in Postman.
2. Set method to **GET**, URL to `http://localhost:8080/health`.
3. Click Send.

Expected response:
```json
{ "status": "ok" }
```

---

## Testing with curl

If you prefer the command line, use `curl` to send requests.

**Health check:**
```bash
curl http://localhost:8080/health
```

**Upload an image:**
```bash
curl -X POST http://localhost:8080/api/process \
     -F "file=@/path/to/your/car.jpg"
```

**Upload and pretty-print the JSON response** (requires `jq`):
```bash
curl -s -X POST http://localhost:8080/api/process \
     -F "file=@/path/to/your/car.jpg" | jq .
```

**Test with an intentionally bad file** (should return a 415 error):
```bash
curl -X POST http://localhost:8080/api/process \
     -F "file=@/path/to/document.pdf"
```

---

## Reading the CSV logs

Log files are written to `data/logs/` on your host machine. A new file is created each day at midnight.

**File naming:** `alpr_YYYY-MM-DD.csv` (e.g. `alpr_2026-06-21.csv`)

**Columns:**

| Column | Example value | Description |
|---|---|---|
| `timestamp` | `2026-06-21T03:32:54+00:00` | UTC time the image was processed (ISO 8601) |
| `filename` | `car.jpg` | Original filename |
| `source` | `api` or `watcher` | How the image was submitted |
| `plate_text` | `ABC123` | Detected plate text (empty if none found) |
| `detection_confidence` | `0.9912` | Detector confidence 0.0–1.0 (empty if no plate) |
| `ocr_confidence` | `0.9871` | OCR confidence 0.0–1.0 (empty if no plate) |
| `processing_duration_ms` | `148.3` | How long the ALPR pipeline took, in milliseconds |
| `status` | `success` | `success`, `no_plate_found`, `plate_found_unreadable`, or `error` |
| `error` | _(empty)_ | Error message when status is `error`, otherwise empty |

**Important:** if an image contains two licence plates, **two rows** are written — one per plate. Both rows share the same `timestamp` and `filename`.

**View today's log from the terminal:**
```bash
cat data/logs/alpr_$(date +%Y-%m-%d).csv
```

**On Windows PowerShell:**
```powershell
Get-Content "data\logs\alpr_$(Get-Date -Format 'yyyy-MM-dd').csv"
```

---

## Configuration reference

All settings are controlled by environment variables. You can override them in `docker-compose.yml` under the `environment:` key.

| Variable | Default | Description |
|---|---|---|
| `INPUT_DIR` | `/data/input` | Directory the watcher monitors for new images |
| `PROCESSED_DIR` | `/data/processed` | Where processed images are moved after ALPR |
| `LOG_DIR` | `/data/logs` | Directory for daily CSV log files |
| `HOST` | `0.0.0.0` | Network interface the API server binds to |
| `PORT` | `8080` | TCP port the API server listens on |

**Example — change the API port to 9000:**

In `docker-compose.yml`:
```yaml
ports:
  - "9000:9000"
environment:
  - PORT=9000
```

---

## API reference

### `GET /health`

Returns `200 OK` when the service is running.

```
GET http://localhost:8080/health
```

Response:
```json
{ "status": "ok" }
```

---

### `POST /api/process`

Process an uploaded image and return all detected licence plates.

```
POST http://localhost:8080/api/process
Content-Type: multipart/form-data
```

**Request field:**

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | binary | Yes | Image file to process |

**Accepted file extensions:** `.jpg` `.jpeg` `.png` `.bmp` `.tiff` `.tif` `.webp`

**Response body:**

```json
{
  "filename": "string",
  "plates": [
    {
      "plate_text": "string",
      "detection_confidence": 0.0,
      "ocr_confidence": 0.0,
      "processing_duration_ms": 0.0
    }
  ],
  "processing_duration_ms": 0.0,
  "status": "success | no_plate_found | plate_found_unreadable"
}
```

**Status values:**

| Value | Meaning |
|---|---|
| `success` | One or more plates were found and read |
| `no_plate_found` | The image was valid but contained no detectable plate |
| `plate_found_unreadable` | A plate was detected, but OCR could not read any text |

**HTTP error codes:**

| Code | Meaning |
|---|---|
| `400 Bad Request` | No filename provided, or the file body was empty |
| `415 Unsupported Media Type` | The file extension is not in the accepted list |
| `422 Unprocessable Entity` | The file could not be decoded as an image (possibly corrupt) |

---

## Error handling behaviour

| Scenario | Watcher behaviour | API behaviour |
|---|---|---|
| Corrupt or unreadable image | Logged as `error`, file moved to `processed/` | Returns HTTP 422 |
| Image with no plates | Logged as `no_plate_found`, file moved to `processed/` | Returns 200 with `plates: []` |
| Plate detected but OCR unreadable | Logged as `plate_found_unreadable`, file moved to `processed/` | Returns 200 with `plates: []` |
| Unsupported file extension in `input/` | File silently ignored (not moved, not logged) | Returns HTTP 415 |
| Filename conflict in `processed/` | Renamed `file_1.jpg`, `file_2.jpg`, … | N/A |
| CSV write failure | Error printed to stdout, processing continues | Error printed to stdout |
| ALPR model exception | Caught, result marked as error, file moved | Caught, returns HTTP 422 |

---

## How the ALPR pipeline works

Processing an image takes two stages:

**Stage 1 — Plate detection** (`yolo-v9-t-384-license-plate-end2end`)

A YOLOv9 neural network scans the entire input image and outputs a list of bounding boxes — rectangular regions that the model believes contain a licence plate. This model was trained on a large dataset of vehicle images and can handle plates at various angles, distances, and lighting conditions.

**Stage 2 — OCR** (`cct-s-v2-global-model`)

Each bounding box from Stage 1 is cropped out of the image and fed into a MobileViT model that reads the characters on the plate. The result includes the plate text plus two confidence values: detector confidence for the plate box and OCR confidence for the text read. Higher confidence (closer to 1.0) means the model is more certain.

Both models are ONNX format and run on CPU via ONNX Runtime — no GPU is required.

---

## Troubleshooting

**Container builds but models fail to download**

The Dockerfile downloads models from Hugging Face during `docker compose build`. This requires internet access at build time. If you are behind a corporate proxy, set the `HTTP_PROXY` and `HTTPS_PROXY` environment variables in your shell before building.

**Images dropped into `data/input/` are not being processed**

- Check the container logs: `docker compose logs -f`
- On Docker Desktop for Windows/Mac, ensure file sharing is enabled for the drive containing the project (`Settings → Resources → File Sharing`).
- The watcher polls every 3 seconds — wait a moment after dropping the file.

**The API returns 422 for a valid image**

The image file may be corrupt or in a format OpenCV cannot decode even though the extension is supported. Try opening the file in an image viewer to confirm it is valid.

**Port 8080 is already in use**

Change the host port in `docker-compose.yml`:
```yaml
ports:
  - "8090:8080"   # Maps host port 8090 to container port 8080
```
Then access the service at `http://localhost:8090`.

**`onnxruntime` not found error during build**

This is a known issue where `fast-alpr` does not declare `onnxruntime` as a required dependency. It is already listed explicitly in `requirements.txt` to fix this, but if you see the error after editing `requirements.txt`, ensure the line `onnxruntime>=1.18.0` is present.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to report bugs, suggest features, and submit pull requests.

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

You are free to use, modify, and distribute this software. The ONNX models used at runtime are subject to their own licences:
- [open-image-models](https://github.com/ankandrew/open-image-models) — see that repository for licence details
- [fast-plate-ocr](https://github.com/ankandrew/fast-plate-ocr) — see that repository for licence details
