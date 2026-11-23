#!/usr/bin/env bash
# Assemble the files a Hugging Face Space needs into one folder: the Gradio app, its README
# (which carries the Space configuration) and requirements, plus the stage package itself, so
# the Space runs exactly the code of this commit without installing it from Git.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
out="${1:-$root/space-bundle}"
rm -rf "$out"
mkdir -p "$out"
cp "$here/app.py" "$here/README.md" "$here/requirements.txt" "$out/"
cp -R "$root/src/stage" "$out/stage"
find "$out" -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "bundle ready in $out:"
(cd "$out" && find . -type f | sort)
