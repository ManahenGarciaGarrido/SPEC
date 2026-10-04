#!/usr/bin/env bash
# Clone the benchmark corpus at the commits pinned in queries.json (dev-time network).
# Usage: tools/bench/fetch_corpus.sh <destination-dir>
set -euo pipefail
dest="${1:?destination directory}"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$dest"
python3 - "$here/queries.json" <<'PY' | while read -r name url commit; do
import json, sys
for repo in json.load(open(sys.argv[1]))["corpus"]:
    print(repo["name"], repo["url"], repo["commit"])
PY
  if [ ! -d "$dest/$name/.git" ]; then
    git init -q "$dest/$name"
    git -C "$dest/$name" remote add origin "$url"
  fi
  git -C "$dest/$name" fetch -q --depth 1 origin "$commit"
  git -C "$dest/$name" checkout -q --detach "$commit"
  echo "$name @ $(git -C "$dest/$name" rev-parse HEAD)"
done
