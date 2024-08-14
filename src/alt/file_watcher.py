# :author: Sasan Jacob Rasti <sasan_jacob.rasti@tu-dresden.de>
# :license: MIT

from __future__ import annotations

import asyncio
import pathlib
import typing as t

import attrs
from loguru import logger

from alt.abs_converter import ABSConverter

if t.TYPE_CHECKING:
    import collections.abc as cabc

SLEEP_TIME = 60


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class DirectorySnapshot:
    directory_path: pathlib.Path

    def __attrs_post_init__(self) -> None:
        self.subdirectories = [subdirectory for subdirectory in self.directory_path.iterdir() if subdirectory.is_dir()]
        self.size_mapping = {file: file.stat().st_size for file in self.directory_path.iterdir() if file.is_file()}

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DirectorySnapshot):
            return self.size_mapping == other.size_mapping

        return NotImplemented


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class FileWatcher:
    watched_directory_path: pathlib.Path
    export_directory_path: pathlib.Path

    async def watch(self) -> None:
        snapshot = DirectorySnapshot(directory_path=self.watched_directory_path)
        await self._watch(snapshot.subdirectories)
        while True:
            await asyncio.sleep(SLEEP_TIME)
            snapshot_new = DirectorySnapshot(directory_path=self.watched_directory_path)
            subdirectories = [
                subdirectory
                for subdirectory in snapshot_new.subdirectories
                if subdirectory not in snapshot.subdirectories
            ]
            await self._watch(subdirectories)
            snapshot = snapshot_new

    async def _watch(self, subdirectories: cabc.Sequence[pathlib.Path]) -> None:
        async with asyncio.TaskGroup() as tg:
            for subdirectory in subdirectories:
                logger.info(f"Watching {subdirectory.name}...")
                tg.create_task(self.watch_artist_dir(subdirectory))

    async def watch_artist_dir(self, directory: pathlib.Path) -> None:
        snapshot = DirectorySnapshot(directory_path=directory)
        await self._watch_artist_dir(snapshot.subdirectories)
        while any(directory.iterdir()):
            await asyncio.sleep(SLEEP_TIME)
            snapshot_new = DirectorySnapshot(directory_path=directory)
            subdirectories = [
                subdirectory
                for subdirectory in snapshot_new.subdirectories
                if subdirectory not in snapshot.subdirectories
            ]
            await self._watch_artist_dir(subdirectories)
            snapshot = snapshot_new

        directory.rmdir()

    async def _watch_artist_dir(self, subdirectories: cabc.Sequence[pathlib.Path]) -> None:
        async with asyncio.TaskGroup() as tg:
            for book_dir in subdirectories:
                logger.info(f"Watching {book_dir.name}...")
                tg.create_task(self.process_bookdir(book_dir))

    async def download_finished(self, directory: pathlib.Path) -> None:
        logger.info(f"Waiting {SLEEP_TIME} s for download to finish for {directory!s}...")
        snapshot = DirectorySnapshot(directory_path=directory)
        await asyncio.sleep(SLEEP_TIME)
        while True:
            snapshot_new = DirectorySnapshot(directory_path=directory)
            if snapshot_new == snapshot:
                logger.info(f"Download finished for {directory!s}")
                break

            logger.info(f"Waiting {SLEEP_TIME} s for download to finish for {directory!s}...")
            snapshot = snapshot_new
            await asyncio.sleep(SLEEP_TIME)

    async def process_bookdir(self, directory: pathlib.Path) -> None:
        await self.download_finished(directory)
        await self.convert_book(directory)

    async def convert_book(self, directory: pathlib.Path) -> None:
        logger.info(f"Converting {directory!s}...")
        absc = ABSConverter(input_directory_path=directory, export_directory_path=self.export_directory_path)
        await absc.convert()
        logger.info(f"Conversion finished for {directory!s}. Removing directory...")

        directory.rmdir()
        logger.info(f"Removed {directory!s}")
