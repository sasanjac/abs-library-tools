# Copilot Instructions for abs-library-tools

## Project Overview

This is a Python-based audiobook library tool (ALT) that automatically converts audio files into `.m4b` audiobook format with chapter metadata. It monitors a directory for new audio files, waits for downloads to complete, then processes them using FFmpeg.

## Architecture

```
src/alt/
├── daemons.py          # Entry point - configures logging, starts daemon
├── abs_import_daemon.py # Daemon wrapper that runs the FileWatcher
├── file_watcher.py     # Async directory monitoring with nested artist/book structure
└── abs_converter.py    # Core FFmpeg conversion logic
```

**Data Flow:** `Daemon` → `FileWatcher` (watches `/data/import`) → `ABSConverter` → outputs to `/data/export/{author}/{book}/audiobook.m4b`

## Code Patterns & Conventions

### attrs for Data Classes
All classes use `@attrs.define(auto_attribs=True, kw_only=True, slots=False)`:
```python
@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class ABSConverter:
    input_directory_path: pathlib.Path
    export_directory_path: pathlib.Path
```

### Async Architecture
- All I/O operations are async using `asyncio`
- `asyncio.TaskGroup` for concurrent directory watching
- `asyncio.create_subprocess_exec` for FFmpeg execution
- Polling-based file watching with `SLEEP_TIME = 60` seconds

### Type Annotations
- Use `from __future__ import annotations` at file top
- Import typing as `t` and collections.abc as `cabc`
- Use `TYPE_CHECKING` guard for type-only imports

### Logging
Use `loguru.logger` (not stdlib logging):
```python
from loguru import logger

logger.info(f"Converting {directory!s}...")
```

### Path Handling
Always use `pathlib.Path`, never string concatenation for paths.

## Key Constants

- `MAX_BITRATE = 192000` - Files above this get re-encoded
- `SUPPORTED_FORMATS = [".flac", ".mp3", ".wav", ".mp4", ".m4b", ".m4a"]`
- FFmpeg uses `libfdk_aac` codec with VBR quality 5

## Development Commands

```bash
uv sync          # Install dependencies
ruff check .     # Lint (uses ALL rules with specific ignores)
ruff format .    # Format code
mypy .           # Type check
pytest           # Run tests
```

## Ruff Configuration Notes

- Line length: 120 characters
- Single-line imports enforced (`force-single-line = true`)
- Docstrings: pep257 convention (but D100-D107 ignored)

## Docker / Deployment

The container image is built from the repo-root `Dockerfile` and published to
GitHub Container Registry (GHCR), not Docker Hub.

- Base image `python:3.12-alpine`; FFmpeg is compiled from source with non-free
  `libfdk-aac` enabled.
- The app is baked into the image at build time with `uv sync --frozen --no-dev`
  (installed into `/app/.venv`) — there is no runtime git clone.
- Runs as the unprivileged `app` user; entrypoint is
  `python /app/src/alt/daemons.py`.
- Bind/volume mount host directories to `/data/import` and `/data/export`.
- CI (`.github/workflows/docker.yml`) runs `checks.yml`, then builds, pushes,
  and cosign-signs the image with SBOM + provenance attestations.

```bash
docker build -t abs-library-tools .
docker run --rm -v /host/import:/data/import -v /host/export:/data/export abs-library-tools
```
