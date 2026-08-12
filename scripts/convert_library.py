#!/usr/bin/env python3
"""Batch-convert an existing audiobook library to faststart-enabled .m4b files.

Runs with nothing but the standard library plus the ffmpeg/ffprobe binaries, so
it can be mounted straight into the abs-library-tools container.

Per-file behaviour:
    .m4b / .m4a            lossless remux, adds +faststart (no re-encode)
    .mp4                   remuxed to .m4b, audio copied when already AAC
    .mp3 / .flac / .wav    encoded to AAC .m4b

Chapters, metadata and embedded cover art are preserved. Source files are kept
unless --delete-source is given, and are only removed after a successful
conversion.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import functools
import json
import pathlib
import shutil
import subprocess
import sys
import typing as t

if t.TYPE_CHECKING:
    import collections.abc as cabc

REMUX_FORMATS = {".m4b", ".m4a"}
MAYBE_COPY_FORMATS = {".mp4"}
ENCODE_FORMATS = {".mp3", ".flac", ".wav"}
SUPPORTED_FORMATS = REMUX_FORMATS | MAYBE_COPY_FORMATS | ENCODE_FORMATS

COVER_ART_CODECS = {"mjpeg", "png", "bmp", "gif", "webp"}

LIBFDK_ARGS = ["-c:a", "libfdk_aac", "-vbr", "5"]
NATIVE_AAC_ARGS = ["-c:a", "aac", "-q:a", "2"]
COPY_ARGS = ["-c:a", "copy"]

TMP_MARKER = ".convert.tmp"


class Action(enum.Enum):
    REMUX = "remux"
    REMUX_TO_M4B = "remux-to-m4b"
    ENCODE = "encode"


@dataclasses.dataclass
class Totals:
    remuxed: int = 0
    encoded: int = 0
    skipped: int = 0
    failed: int = 0


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        sys.exit(f"error: {binary} not found on PATH")

    return path


@functools.cache
def _ffmpeg() -> str:
    return _require("ffmpeg")


@functools.cache
def _ffprobe() -> str:
    return _require("ffprobe")


@functools.cache
def _encode_args() -> tuple[str, ...]:
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "libfdk_aac" in result.stdout:
        print("Using libfdk_aac encoder.")
        return tuple(LIBFDK_ARGS)

    print("libfdk_aac unavailable, using native aac encoder.")
    return tuple(NATIVE_AAC_ARGS)


def _probe(file: pathlib.Path) -> dict:
    result = subprocess.run(
        [_ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _streams(probe: dict, codec_type: str) -> list[dict]:
    return [s for s in probe.get("streams", []) if s.get("codec_type") == codec_type]


def _plan(file: pathlib.Path) -> tuple[Action, pathlib.Path]:
    suffix = file.suffix.lower()
    if suffix in REMUX_FORMATS:
        return Action.REMUX, file

    target = file.with_suffix(".m4b")
    if suffix in MAYBE_COPY_FORMATS:
        audio = _streams(_probe(file), "audio")
        if audio and audio[0].get("codec_name") == "aac":
            return Action.REMUX_TO_M4B, target

    return Action.ENCODE, target


def _build_args(file: pathlib.Path, tmp: pathlib.Path, action: Action) -> list[str]:
    # Only carry a video stream over when it is genuine cover art, otherwise a
    # real video track would be mislabelled as an attached picture.
    has_cover = any(s.get("codec_name") in COVER_ART_CODECS for s in _streams(_probe(file), "video"))

    args = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(file), "-map", "0:a"]
    if has_cover:
        args += ["-map", "0:v", "-c:v", "copy", "-disposition:v", "attached_pic"]
    else:
        args += ["-vn"]

    codec = COPY_ARGS if action is not Action.ENCODE else list(_encode_args())

    return [*args, "-map_metadata", "0", "-map_chapters", "0", *codec, "-movflags", "+faststart", "-f", "mp4", str(tmp)]


def _convert(file: pathlib.Path, *, delete_source: bool, dry_run: bool, totals: Totals) -> None:
    action, target = _plan(file)

    if target != file and target.exists():
        print(f"==> {file}\n    skipping, '{target}' already exists")
        totals.skipped += 1
        return

    print(f"==> {file} [{action.value}]")
    if dry_run:
        return

    tmp = target.with_name(target.name + TMP_MARKER)
    result = subprocess.run(_build_args(file, tmp, action), capture_output=True, text=True, check=False)

    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        print(f"    failed: {detail[-1] if detail else 'unknown error'}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        totals.failed += 1
        return

    tmp.replace(target)

    if action is Action.REMUX:
        totals.remuxed += 1
        return

    totals.encoded += 1
    if delete_source and target != file:
        file.unlink(missing_ok=True)
        print("    removed source")


def _iter_files(directory: pathlib.Path) -> cabc.Iterator[pathlib.Path]:
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS and TMP_MARKER not in path.name:
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=pathlib.Path, nargs="?", default=pathlib.Path())
    parser.add_argument("--delete-source", action="store_true", help="remove source files after a successful encode")
    parser.add_argument("--dry-run", action="store_true", help="only report what would happen")
    args = parser.parse_args()

    directory = args.directory
    if not directory.is_dir():
        sys.exit(f"error: '{directory}' is not a directory")

    totals = Totals()
    _encode_args()
    for file in _iter_files(directory):
        _convert(file, delete_source=args.delete_source, dry_run=args.dry_run, totals=totals)

    print(
        f"\nDone. Remuxed {totals.remuxed}, converted {totals.encoded}, "
        f"skipped {totals.skipped}, failed {totals.failed}.",
    )

    return 1 if totals.failed else 0


if __name__ == "__main__":
    sys.exit(main())
