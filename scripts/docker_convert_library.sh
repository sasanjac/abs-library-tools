#!/usr/bin/env bash
#
# Run the library converter on a server using the abs-library-tools image.
#
# The image already ships ffmpeg built with libfdk-aac, so nothing has to be
# installed on the host besides Docker. The converter script is mounted into
# the container, which means this works with the published image as-is.
#
# Usage:
#   scripts/docker_convert_library.sh /path/to/library [--dry-run] [--delete-source]
#
# Environment:
#   ALT_IMAGE   image to use (default: ghcr.io/sasanjac/abs-library-tools:latest)

set -euo pipefail

IMAGE="${ALT_IMAGE:-ghcr.io/sasanjac/abs-library-tools:latest}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 || "${1}" == "-h" || "${1}" == "--help" ]]; then
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

LIBRARY_DIR="$1"
shift

if [[ ! -d "${LIBRARY_DIR}" ]]; then
  echo "error: '${LIBRARY_DIR}' is not a directory" >&2
  exit 1
fi

LIBRARY_DIR="$(cd -- "${LIBRARY_DIR}" && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker not found on PATH" >&2
  exit 1
fi

tty_flag=()
[[ -t 1 ]] && tty_flag=(-t)

# Run as the invoking user so converted files keep the library's ownership
# instead of being written as the image's `app` user.
exec docker run --rm "${tty_flag[@]}" \
  --user "$(id -u):$(id -g)" \
  -v "${LIBRARY_DIR}:/data/library" \
  -v "${SCRIPT_DIR}/convert_library.py:/opt/convert_library.py:ro" \
  "${IMAGE}" \
  python /opt/convert_library.py /data/library "$@"
