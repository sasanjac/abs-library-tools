# :author: Sasan Jacob Rasti <sasan_jacob.rasti@tu-dresden.de>
# :license: MIT

from __future__ import annotations

import asyncio
import itertools
import pathlib
import re
import typing as t

import attrs
import ffmpeg
import loguru

MAX_BITRATE = 192000
CHAPTER_LENGTH_TOLERANCE_MS = 5000

M4B_COPY_PARAMS = ["-c:a", "copy", "-c:v", "copy", "-disposition:v", "attached_pic"]
M4B_CONVERT_PARAMS = ["-c:a", "libfdk_aac", "-vbr", "5", "-c:v", "copy", "-disposition:v", "attached_pic"]
MP3_COPY_PARAMS = ["-c:a", "copy", "-c:v", "copy", "-id3v2_version", "3"]

SUPPORTED_FORMATS = [
    ".flac",
    ".mp3",
    ".wav",
    ".mp4",
    ".m4b",
    ".m4a",
]

CHAPTER_FILE_NAME = "audiobook.chapters.txt"
TIMESTAMP_PATTERN = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s+(.+)$")
TOTAL_LENGTH_PATTERN = re.compile(r"^#\s*total-length\s+(\d+):(\d{2}):(\d{2})(?:\.(\d+))?")


def _parse_timestamp_to_ms(hours: str, minutes: str, seconds: str, fraction: str | None) -> int:
    """Convert timestamp components to milliseconds."""
    ms = int(hours) * 3600000 + int(minutes) * 60000 + int(seconds) * 1000
    if fraction:
        ms += int(fraction.ljust(3, "0")[:3])

    return ms


def _natural_sort_key(path: pathlib.Path) -> list[object]:
    """Return a key that sorts embedded numbers numerically (e.g. Chapter 2 before Chapter 10)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.stem)]


def _escape_concat_path(path: pathlib.Path) -> str:
    """Escape a path for use in an FFmpeg concat demuxer list."""
    return str(path).replace("'", "'\\''")


def _select_audio_stream(probe: dict[str, t.Any]) -> dict[str, t.Any]:
    """Return the first audio stream from an ffmpeg probe, falling back to the first stream."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream

    return probe["streams"][0]


def _probe_duration_ms(probe: dict[str, t.Any]) -> int:
    """Extract the audio duration in milliseconds from an ffmpeg probe."""
    stream = _select_audio_stream(probe)
    duration = stream.get("duration") or probe.get("format", {}).get("duration")
    return int(float(duration) * 1000)


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class ChapterInfo:
    start_ms: int
    title: str


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class ExternalChapters:
    total_length_ms: int
    chapters: list[ChapterInfo]


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class EncodingSettings:
    output_suffix: str
    codec_args: list[str]
    log_message: str


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class ABSConverter:
    input_directory_path: pathlib.Path
    export_directory_path: pathlib.Path

    def _get_encoding_settings(
        self,
        file_format: str,
        input_files: list[pathlib.Path],
        first_probe: dict[str, t.Any] | None = None,
    ) -> EncodingSettings:
        """Determine output suffix, codec args, and log message based on input format."""
        if file_format == ".mp3":
            return EncodingSettings(
                output_suffix=".mp3",
                codec_args=MP3_COPY_PARAMS,
                log_message="Concatenating MP3 files without re-encoding",
            )

        if file_format in [".flac", ".wav"]:
            return EncodingSettings(
                output_suffix=".m4b",
                codec_args=M4B_CONVERT_PARAMS,
                log_message="Converting audio to AAC format",
            )

        probe = first_probe if first_probe is not None else ffmpeg.probe(input_files[0])
        stream = _select_audio_stream(probe)
        bitrate_raw = stream.get("bit_rate") or probe.get("format", {}).get("bit_rate")
        bitrate = int(bitrate_raw)
        if bitrate > MAX_BITRATE:
            return EncodingSettings(
                output_suffix=".m4b",
                codec_args=M4B_CONVERT_PARAMS,
                log_message="Converting audio to AAC format",
            )

        return EncodingSettings(
            output_suffix=".m4b",
            codec_args=M4B_COPY_PARAMS,
            log_message="Copying audio stream",
        )

    def _parse_external_chapters(self, chapter_file_path: pathlib.Path) -> ExternalChapters | None:
        """Parse an external audiobook.chapters.txt file."""
        if not chapter_file_path.exists():
            return None

        total_length_ms = 0
        chapters: list[ChapterInfo] = []

        with chapter_file_path.open() as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue

                if match := TOTAL_LENGTH_PATTERN.match(line):
                    total_length_ms = _parse_timestamp_to_ms(
                        match.group(1),
                        match.group(2),
                        match.group(3),
                        match.group(4),
                    )
                elif match := TIMESTAMP_PATTERN.match(line):
                    start_ms = _parse_timestamp_to_ms(
                        match.group(1),
                        match.group(2),
                        match.group(3),
                        match.group(4),
                    )
                    chapters.append(ChapterInfo(start_ms=start_ms, title=match.group(5)))

        if not chapters or total_length_ms == 0:
            return None

        return ExternalChapters(total_length_ms=total_length_ms, chapters=chapters)

    def _build_chapter_string(
        self,
        input_files: list[pathlib.Path],
        external_chapters: ExternalChapters | None,
        durations: dict[pathlib.Path, int] | None = None,
    ) -> tuple[str, int]:
        """Build FFmpeg chapter metadata string. Returns chapter string and total length in ms."""
        chapter_str = ";FFMETADATA1\n"

        if external_chapters:
            total_length_ms = external_chapters.total_length_ms
            for i, chapter in enumerate(external_chapters.chapters):
                if i + 1 < len(external_chapters.chapters):
                    end_ms = external_chapters.chapters[i + 1].start_ms - 1
                else:
                    end_ms = total_length_ms
                chapter_str += (
                    f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={chapter.start_ms:.0f}\n"
                    f"END={end_ms:.0f}\ntitle={chapter.title}\n"
                )
            loguru.logger.info("Using external chapter file")
        else:
            durations = durations or {}
            total_length_ms = 0
            for file in input_files:
                length = durations[file]
                end = total_length_ms + length
                chapter_str += (
                    f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={total_length_ms:.0f}\nEND={end:.0f}\ntitle={file.stem}\n"
                )
                total_length_ms = end + 1
            loguru.logger.info("Generating chapters from file names")

        return chapter_str, total_length_ms

    async def _probe(self, file: pathlib.Path) -> dict[str, t.Any]:
        """Probe a file without blocking the event loop."""
        return await asyncio.to_thread(ffmpeg.probe, str(file))

    def _build_ffmpeg_args(
        self,
        process_file: pathlib.Path,
        chapter_file: pathlib.Path,
        output_file_path: pathlib.Path,
        codec_args: list[str],
    ) -> list[str]:
        """Build FFmpeg command arguments."""
        return [
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(process_file),
            "-i",
            str(chapter_file),
            "-map",
            "0:a",
            "-map",
            "0:v?",
            "-map_metadata",
            "1",
            *codec_args,
            str(output_file_path),
        ]

    async def convert(self) -> None:
        input_files_formats = [list(self.input_directory_path.glob(f"*{_format}")) for _format in SUPPORTED_FORMATS]
        if sum(any(input_files) for input_files in input_files_formats) > 1:
            msg = "Multiple files with different formats found."
            raise ValueError(msg)

        input_files = list(itertools.chain.from_iterable(input_files_formats))
        if not input_files:
            return

        input_files = sorted(input_files, key=_natural_sort_key)
        output_directory_path = (
            self.export_directory_path / self.input_directory_path.parent.name / self.input_directory_path.name
        )
        output_directory_path.mkdir(parents=True, exist_ok=True)

        process_file = self.input_directory_path / "input"
        chapter_file = self.input_directory_path / "FFMETADATAFILE"
        external_chapter_file = self.input_directory_path / CHAPTER_FILE_NAME

        probes = {file: await self._probe(file) for file in input_files}
        durations = {file: _probe_duration_ms(probes[file]) for file in input_files}

        # Check for external chapter file and validate length
        external_chapters = self._parse_external_chapters(external_chapter_file)
        if external_chapters:
            total_audio_length_ms = sum(durations.values())
            length_diff = abs(external_chapters.total_length_ms - total_audio_length_ms)
            if length_diff > CHAPTER_LENGTH_TOLERANCE_MS:
                loguru.logger.warning(
                    "External chapter file length ({external_length}ms) doesn't match audio length "
                    "({audio_length}ms), difference: {diff}ms. Using file-based chapters instead.",
                    external_length=external_chapters.total_length_ms,
                    audio_length=total_audio_length_ms,
                    diff=length_diff,
                )
                external_chapters = None

        chapter_str, _ = self._build_chapter_string(input_files, external_chapters, durations)

        loguru.logger.info(chapter_str)

        with chapter_file.open(mode="w") as chapter_list:
            chapter_list.write(chapter_str)

        with process_file.open(mode="w") as input_list:
            input_list.write("\n".join(f"file '{_escape_concat_path(file)}'" for file in input_files))

        file_format = input_files[0].suffix
        settings = self._get_encoding_settings(file_format, input_files, probes[input_files[0]])
        output_file_path = (output_directory_path / "audiobook").with_suffix(settings.output_suffix)

        codec_args = settings.codec_args

        loguru.logger.info(f"{settings.log_message} to file {{output_file_path}}", output_file_path=output_file_path)

        args = self._build_ffmpeg_args(
            process_file,
            chapter_file,
            output_file_path,
            codec_args,
        )

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if stdout:
            loguru.logger.info(stdout.decode())

        if stderr:
            loguru.logger.info(stderr.decode())

        if process.returncode != 0:
            loguru.logger.error(
                "FFmpeg failed with exit code {code} for {directory}. Keeping source files.",
                code=process.returncode,
                directory=str(self.input_directory_path),
            )
            return

        for file in self.input_directory_path.iterdir():
            if file.is_file():
                file.unlink()
