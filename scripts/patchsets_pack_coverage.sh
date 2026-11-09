#!/bin/bash
# Which old packs are fully covered by (new packs ∪ shared clone)?
# Usage: coverage.sh <git_dir> <before-list> <workdir>
# Prints "REMOVABLE <pack>" / "KEEP <pack> <n missing>" and a summary. Read-only.
set -euo pipefail
g=$1; before=$2; w=$3
export GIT_NO_LAZY_FETCH=1 LC_ALL=C
mkdir -p "$w"; cd "$g/objects/pack"
ls | grep '\.pack$' | grep -vxFf "$before" > "$w/new.txt"
echo "new packs: $(wc -l < "$w/new.txt")"
for p in $(cat "$w/new.txt"); do git show-index < "${p%.pack}.idx" | cut -d' ' -f2; done \
  | sort -S 1G -u > "$w/new.ids"
echo "objects in new packs: $(wc -l < "$w/new.ids")"
for p in $(cat "$before"); do git show-index < "${p%.pack}.idx" | cut -d' ' -f2; done \
  | sort -S 1G -u > "$w/old.ids"
echo "objects in old packs: $(wc -l < "$w/old.ids")"
comm -23 "$w/old.ids" "$w/new.ids" > "$w/notnew.ids"
echo "old objects not in new packs: $(wc -l < "$w/notnew.ids")"
# Of those, which are missing from the shared clone too?
git -C ~/projects/shared/chromium cat-file --batch-check='%(objectname) %(objecttype)' \
  < "$w/notnew.ids" | awk '$2=="missing"{print $1}' > "$w/missing.ids"
echo "in neither new packs nor shared clone: $(wc -l < "$w/missing.ids")"
for p in $(cat "$before"); do
  n=$(git show-index < "${p%.pack}.idx" | cut -d' ' -f2 | sort -S 256M | comm -12 - "$w/missing.ids" | wc -l)
  if [ "$n" -eq 0 ]; then echo "REMOVABLE $p"; else echo "KEEP $p $n"; fi
done > "$w/decision.txt"
echo "removable: $(grep -c '^REMOVABLE' "$w/decision.txt" || true), keep: $(grep -c '^KEEP' "$w/decision.txt" || true)"
