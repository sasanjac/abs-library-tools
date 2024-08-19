# :author: Sasan Jacob Rasti <sasan_jacob.rasti@tu-dresden.de>
# :license: MIT

from __future__ import annotations

import asyncio
import itertools
import pathlib

import attrs
import ffmpeg
import loguru

MAX_BITRATE = 192000

SUPPORTED_FORMATS = [
    ".flac",
    ".mp3",
    ".wav",
    ".mp4",
    ".m4b",
    ".m4a",
]


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class ABSConverter:
    input_directory_path: pathlib.Path
    export_directory_path: pathlib.Path

    async def convert(self) -> None:
        input_files_formats = [list(self.input_directory_path.glob(f"*{_format}")) for _format in SUPPORTED_FORMATS]
        if sum(any(input_files) for input_files in input_files_formats) > 1:
            msg = "Multiple files with different formats found."
            raise ValueError(msg)

        input_files = list(itertools.chain.from_iterable(input_files_formats))
        if any(input_files):
            input_files = sorted(input_files, key=lambda x: x.stem)
            output_directory_path = (
                self.export_directory_path / self.input_directory_path.parent.name / self.input_directory_path.name
            )
            output_directory_path.mkdir(parents=True, exist_ok=True)
            output_file_path = output_directory_path / "audiobook.m4b"
            process_file = self.input_directory_path / "input"
            chapter_file = self.input_directory_path / "FFMETADATAFILE"
            chapter_str = ";FFMETADATA1\n"
            start = 0
            for file in input_files:
                probe = ffmpeg.probe(file)
                length = int(probe["streams"][0]["duration"] * 1000)
                end = start + length
                chapter_str += f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start:.0f}\nEND={end:.0f}\ntitle={file.stem}\n"
                start = end + 1

            loguru.logger.info(chapter_str)

            with chapter_file.open(mode="w") as chapter_list:
                chapter_list.write(chapter_str)

            with process_file.open(mode="w") as input_list:
                input_list.write("\n".join(f"file '{file!s}'" for file in input_files))

            _format = input_files[0].suffix
            if _format in [".flac", ".wav"]:
                convert = True
            else:
                probe = ffmpeg.probe(input_files[0])
                bitrate = probe["streams"][0]["bit_rate"]
                convert = bitrate > MAX_BITRATE

            if convert:
                args = [
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
                    "0",
                    "-map_metadata",
                    "1",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "libfdk_aac",
                    "-vbr",
                    "5",
                    str(output_file_path),
                ]

            else:
                args = [
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
                    "0",
                    "-map_metadata",
                    "1",
                    "-c",
                    "copy",
                    str(output_file_path),
                ]
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            for file in self.input_directory_path.iterdir():
                if file.is_file():
                    file.unlink()
