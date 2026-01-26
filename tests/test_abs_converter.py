# :author: Sasan Jacob Rasti <sasan_jacob.rasti@tu-dresden.de>
# :license: MIT

from __future__ import annotations

import typing as t

import pytest

from alt.abs_converter import CHAPTER_LENGTH_TOLERANCE_MS
from alt.abs_converter import M4B_CONVERT_PARAMS
from alt.abs_converter import MP3_COPY_PARAMS
from alt.abs_converter import ABSConverter
from alt.abs_converter import ChapterInfo
from alt.abs_converter import ExternalChapters
from alt.abs_converter import _parse_timestamp_to_ms

if t.TYPE_CHECKING:
    import pathlib


class TestParseTimestampToMs:
    def test_simple_timestamp(self) -> None:
        result = _parse_timestamp_to_ms("1", "30", "45", None)
        assert result == 1 * 3600000 + 30 * 60000 + 45 * 1000

    def test_timestamp_with_fraction(self) -> None:
        result = _parse_timestamp_to_ms("0", "01", "58", "329")
        assert result == 1 * 60000 + 58 * 1000 + 329

    def test_timestamp_with_short_fraction(self) -> None:
        result = _parse_timestamp_to_ms("0", "07", "49", "6")
        assert result == 7 * 60000 + 49 * 1000 + 600

    def test_zero_timestamp(self) -> None:
        result = _parse_timestamp_to_ms("0", "00", "00", None)
        assert result == 0

    def test_large_timestamp(self) -> None:
        result = _parse_timestamp_to_ms("6", "37", "07", "06")
        assert result == 6 * 3600000 + 37 * 60000 + 7 * 1000 + 60


class TestParseExternalChapters:
    @pytest.fixture
    def converter(self, tmp_path: pathlib.Path) -> ABSConverter:
        return ABSConverter(
            input_directory_path=tmp_path / "input",
            export_directory_path=tmp_path / "export",
        )

    def test_parse_valid_chapter_file(self, converter: ABSConverter, tmp_path: pathlib.Path) -> None:
        chapter_content = """\
# total-length 6:37:07.06
0:00:00.000 Kapitel 1
0:01:58.329 Kapitel 2
0:03:04.924 Kapitel 3
"""
        chapter_file = tmp_path / "audiobook.chapters.txt"
        chapter_file.write_text(chapter_content)

        result = converter._parse_external_chapters(chapter_file)

        assert result is not None
        assert result.total_length_ms == 6 * 3600000 + 37 * 60000 + 7 * 1000 + 60
        assert len(result.chapters) == 3
        assert result.chapters[0].title == "Kapitel 1"
        assert result.chapters[0].start_ms == 0
        assert result.chapters[1].title == "Kapitel 2"
        assert result.chapters[1].start_ms == 1 * 60000 + 58 * 1000 + 329
        assert result.chapters[2].title == "Kapitel 3"
        assert result.chapters[2].start_ms == 3 * 60000 + 4 * 1000 + 924

    def test_parse_nonexistent_file(self, converter: ABSConverter, tmp_path: pathlib.Path) -> None:
        result = converter._parse_external_chapters(tmp_path / "nonexistent.txt")
        assert result is None

    def test_parse_empty_file(self, converter: ABSConverter, tmp_path: pathlib.Path) -> None:
        chapter_file = tmp_path / "empty.txt"
        chapter_file.write_text("")

        result = converter._parse_external_chapters(chapter_file)
        assert result is None

    def test_parse_file_without_total_length(self, converter: ABSConverter, tmp_path: pathlib.Path) -> None:
        chapter_content = """\
0:00:00.000 Kapitel 1
0:01:58.329 Kapitel 2
"""
        chapter_file = tmp_path / "no_total.txt"
        chapter_file.write_text(chapter_content)

        result = converter._parse_external_chapters(chapter_file)
        assert result is None

    def test_parse_file_without_chapters(self, converter: ABSConverter, tmp_path: pathlib.Path) -> None:
        chapter_content = "# total-length 1:00:00.000\n"
        chapter_file = tmp_path / "no_chapters.txt"
        chapter_file.write_text(chapter_content)

        result = converter._parse_external_chapters(chapter_file)
        assert result is None

    def test_parse_file_with_blank_lines(self, converter: ABSConverter, tmp_path: pathlib.Path) -> None:
        chapter_content = """\
# total-length 1:00:00.000

0:00:00.000 Chapter 1

0:30:00.000 Chapter 2

"""
        chapter_file = tmp_path / "blank_lines.txt"
        chapter_file.write_text(chapter_content)

        result = converter._parse_external_chapters(chapter_file)
        assert result is not None
        assert len(result.chapters) == 2


class TestBuildChapterString:
    @pytest.fixture
    def converter(self, tmp_path: pathlib.Path) -> ABSConverter:
        return ABSConverter(
            input_directory_path=tmp_path / "input",
            export_directory_path=tmp_path / "export",
        )

    def test_build_from_external_chapters(self, converter: ABSConverter) -> None:
        external_chapters = ExternalChapters(
            total_length_ms=180000,
            chapters=[
                ChapterInfo(start_ms=0, title="Chapter 1"),
                ChapterInfo(start_ms=60000, title="Chapter 2"),
                ChapterInfo(start_ms=120000, title="Chapter 3"),
            ],
        )

        chapter_str, total_length = converter._build_chapter_string([], external_chapters)

        assert ";FFMETADATA1" in chapter_str
        assert "TIMEBASE=1/1000" in chapter_str
        assert "title=Chapter 1" in chapter_str
        assert "title=Chapter 2" in chapter_str
        assert "title=Chapter 3" in chapter_str
        assert "START=0" in chapter_str
        assert "START=60000" in chapter_str
        assert "START=120000" in chapter_str
        assert "END=59999" in chapter_str  # end is start of next - 1
        assert "END=119999" in chapter_str
        assert "END=180000" in chapter_str  # last chapter ends at total length
        assert total_length == 180000

    def test_chapter_end_times_are_correct(self, converter: ABSConverter) -> None:
        external_chapters = ExternalChapters(
            total_length_ms=100000,
            chapters=[
                ChapterInfo(start_ms=0, title="First"),
                ChapterInfo(start_ms=50000, title="Second"),
            ],
        )

        chapter_str, _ = converter._build_chapter_string([], external_chapters)

        # First chapter should end at 49999 (start of second - 1)
        assert "START=0" in chapter_str
        assert "END=49999" in chapter_str
        # Second chapter should end at total length
        assert "START=50000" in chapter_str
        assert "END=100000" in chapter_str


class TestGetEncodingSettings:
    @pytest.fixture
    def converter(self, tmp_path: pathlib.Path) -> ABSConverter:
        return ABSConverter(
            input_directory_path=tmp_path / "input",
            export_directory_path=tmp_path / "export",
        )

    def test_mp3_format_returns_mp3_copy(self, converter: ABSConverter) -> None:
        settings = converter._get_encoding_settings(".mp3", [])

        assert settings.output_suffix == ".mp3"
        assert settings.codec_args == MP3_COPY_PARAMS
        assert "without re-encoding" in settings.log_message

    def test_flac_format_returns_m4b_convert(self, converter: ABSConverter) -> None:
        settings = converter._get_encoding_settings(".flac", [])

        assert settings.output_suffix == ".m4b"
        assert settings.codec_args == M4B_CONVERT_PARAMS
        assert "Converting" in settings.log_message

    def test_wav_format_returns_m4b_convert(self, converter: ABSConverter) -> None:
        settings = converter._get_encoding_settings(".wav", [])

        assert settings.output_suffix == ".m4b"
        assert settings.codec_args == M4B_CONVERT_PARAMS
        assert "Converting" in settings.log_message


class TestChapterLengthTolerance:
    def test_tolerance_is_5_seconds(self) -> None:
        assert CHAPTER_LENGTH_TOLERANCE_MS == 5000
