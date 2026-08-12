# abs-library-tools

Converts audio files into chaptered `.m4b` audiobooks for
[Audiobookshelf](https://www.audiobookshelf.org/).

A daemon watches an import directory for new audio files, waits until a download
has settled, then converts each book with FFmpeg and writes the result to the
export directory.

## How it works

```
/data/import/{author}/{book}/*.mp3  ->  /data/export/{author}/{book}/audiobook.m4b
```

- Supported inputs: `.flac`, `.mp3`, `.wav`, `.mp4`, `.m4b`, `.m4a`
- Chapters are derived from the individual input files (or an external chapter file)
- Audio above 192 kbit/s is re-encoded with `libfdk_aac` (VBR quality 5), otherwise it is copied

## Running with Docker

The image is published to the GitHub Container Registry:

```bash
docker run -d \
  --name abs-library-tools \
  -v /host/import:/data/import \
  -v /host/export:/data/export \
  ghcr.io/sasanjac/abs-library-tools:latest
```

Building locally:

```bash
docker build -t abs-library-tools .
```

The application is baked into the image at build time and runs as an
unprivileged user. FFmpeg is compiled from source so that the non-free
`libfdk-aac` encoder is available.

## Development

This project uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync                    # install dependencies
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy .              # type check
uv run pytest              # run tests
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/);
releases are tagged `vX.Y.Z` via `uv run cz bump`.

## License

[MIT](LICENSE)
