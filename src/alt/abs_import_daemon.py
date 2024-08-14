# :author: Sasan Jacob Rasti <sasan_jacob.rasti@tu-dresden.de>
# :license: MIT

from __future__ import annotations

import asyncio
import pathlib

import attrs

from alt.file_watcher import FileWatcher


@attrs.define(auto_attribs=True, kw_only=True, slots=False)
class Daemon:
    input_direcory_path: pathlib.Path
    export_directory_path: pathlib.Path

    def run(self) -> None:
        fw = FileWatcher(
            watched_directory_path=self.input_direcory_path,
            export_directory_path=self.export_directory_path,
        )
        asyncio.run(fw.watch())
