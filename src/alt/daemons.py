# :author: Sasan Jacob Rasti <sasan_jacob.rasti@tu-dresden.de>
# :license: MIT

from __future__ import annotations

import pathlib
import sys

from loguru import logger

from alt.abs_import_daemon import Daemon

logger.remove()
logger.add(sys.stderr, colorize=True, format="<level>{message}</level>")

input_direcory_path = pathlib.Path("/data/import")
export_directory_path = pathlib.Path("/data/export")


d = Daemon(
    input_direcory_path=input_direcory_path,
    export_directory_path=export_directory_path,
)

d.run()
