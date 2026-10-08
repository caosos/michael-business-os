#!/usr/bin/env bash
# archive-wal.sh <dest-dir> <wal-path> <wal-name> — PostgreSQL archive_command (D-09 part a).
# Copies one WAL segment into <dest-dir> durably and idempotently. Exit 0 ONLY when an identical file is safely
# there; PostgreSQL then recycles the segment. Anything else exits non-zero and PostgreSQL retries.
# The destination is a plain directory today (local, NFS, a mounted/rclone-synced remote); the off-box target
# only changes this one argument (see docs/state/OWNER_QUESTION_BACKUPS.md).
set -euo pipefail
dest=${1:?dest}; src=${2:?path}; name=${3:?name}
mkdir -p "$dest"
if [[ -e "$dest/$name" ]]; then
  cmp -s "$src" "$dest/$name" && exit 0                       # already archived (retry after a crash): fine
  echo "archive-wal: refusing to overwrite a DIFFERENT $name" >&2; exit 1
fi
tmp=$(mktemp "$dest/.tmp.XXXXXX")
trap 'rm -f "$tmp"' EXIT
cp -- "$src" "$tmp"
sync "$tmp"                                                    # data on disk before it becomes visible
mv -n -- "$tmp" "$dest/$name"
sync "$dest"                                                   # the rename itself is durable
cmp -s "$src" "$dest/$name"
chmod 0440 "$dest/$name"
