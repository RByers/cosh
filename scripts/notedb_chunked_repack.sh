#!/bin/bash
# Lossless chunked repack of a NoteDb repo, swapped in at the end while others read it.
#  1. pack-objects --stdin-packs over groups of the current packs (about GROUP_BYTES of
#     pack each, oldest first), writing to a staging dir outside objects/pack, so
#     readers never see a half-done state. verify-pack each new pack.
#  2. Check every object id in the old packs is in a new pack (NoteDb has no alternates).
#  3. Swap: move the new packs in (.idx last), write a multi-pack index over only the
#     new packs (one atomic rename: from then on lookups go to them), then move the old
#     packs aside (.idx first). A reader that still has an old pack open keeps it; one
#     that finds it gone rescans and finds the object through the new index.
#  4. Rewrite and verify the index, then walk every ref with --missing=print; on any
#     missing object, move the old packs back.
# Nothing is pruned or deleted: the old packs stay in <workdir>/old-packs until a
# person deletes them after checking. Loose objects are left alone.
# Usage (holds the extract lock so no fetch adds packs meanwhile):
#   flock -n data/private/extract.lock scripts/notedb_chunked_repack.sh <git_dir> <workdir>
set -uo pipefail
g=$(realpath "$1"); mkdir -p "$2"; W=$(realpath "$2"); GROUP_BYTES=${GROUP_BYTES:-1500000000}
export GIT_NO_LAZY_FETCH=1 LC_ALL=C
P=$g/objects/pack; S=$W/stage; A=$W/old-packs
log() { echo "$(date '+%F %T') $*"; }
# mvpack <from> <to> <base> <idx-first|idx-last>: a pack is visible to git once its .idx is.
mvpack() {
  local f=$1 t=$2 b=$3
  [ "$4" = idx-first ] && mv "$f/$b.idx" "$t/"
  mv "$f/$b.pack" "$t/"
  [ -e "$f/$b.rev" ] && mv "$f/$b.rev" "$t/"
  [ "$4" = idx-last ] && mv "$f/$b.idx" "$t/"
  return 0
}
mkdir -p "$S" "$A"
cd "$P" || exit 1
[ -z "$(ls "$S")" ] || { log "staging dir $S is not empty; refusing"; exit 1; }
ls *.keep 2>/dev/null && { log ".keep packs present; refusing"; exit 1; }

# 1. groups
ls -tr *.pack > "$W/before.txt"
log "before: $(wc -l < "$W/before.txt") packs, $(du -sb . | cut -f1) bytes in objects/pack"
grp=0; cur=(); bytes=0
flush() {
  [ ${#cur[@]} -eq 0 ] && return 0
  grp=$((grp + 1))
  log "group $grp: ${#cur[@]} packs, $bytes bytes"
  out=$(printf '%s\n' "${cur[@]}" | nice -n 5 git --git-dir "$g" -c pack.threads=2 \
        -c pack.windowMemory=512m -c pack.deltaCacheSize=128m \
        pack-objects --stdin-packs --delta-base-offset --quiet "$S/pack")
  rc=$?
  if [ $rc -ne 0 ] || [ -z "$out" ]; then log "group $grp pack-objects FAILED exit $rc"; exit 1; fi
  if ! nice -n 5 git --git-dir "$g" verify-pack "$S/pack-$out.idx" > /dev/null; then
    log "group $grp pack-$out VERIFY FAILED"; exit 1; fi
  log "group $grp -> pack-$out $(stat -c %s "$S/pack-$out.pack") bytes, verified"
  cur=(); bytes=0
}
while read -r p; do
  cur+=("$p"); bytes=$((bytes + $(stat -c %s "$p")))
  [ $bytes -ge "$GROUP_BYTES" ] && flush
done < "$W/before.txt"
flush

# 2. coverage
while read -r p; do git show-index < "${p%.pack}.idx" | cut -d' ' -f2; done < "$W/before.txt" \
  | sort -S 1G -T "$W" -u > "$W/old.ids"
for i in "$S"/*.idx; do git show-index < "$i" | cut -d' ' -f2; done | sort -S 1G -T "$W" -u > "$W/new.ids"
miss=$(comm -23 "$W/old.ids" "$W/new.ids" | wc -l)
log "coverage: old $(wc -l < "$W/old.ids") ids, new $(wc -l < "$W/new.ids") ids, old not in new: $miss"
[ "$miss" -eq 0 ] || { log "COVERAGE FAILED; nothing swapped"; exit 1; }

# 3. swap. A new pack can only share an old one's name if it has the same content;
# such a pack stays where it is, and the identical staged copy is removed.
(cd "$S" && ls *.pack) | sort > "$W/new.txt"
sort "$W/before.txt" > "$W/before.sorted"
comm -12 "$W/new.txt" "$W/before.sorted" > "$W/same.txt"
comm -23 "$W/new.txt" "$W/before.sorted" > "$W/in.txt"
comm -23 "$W/before.sorted" "$W/new.txt" > "$W/out.txt"
log "swap: $(wc -l < "$W/in.txt") in, $(wc -l < "$W/out.txt") out, $(wc -l < "$W/same.txt") unchanged"
while read -r p; do mvpack "$S" "$P" "${p%.pack}" idx-last; done < "$W/in.txt"
while read -r p; do b=${p%.pack}; rm -f "$S/$b.idx" "$S/$b.pack" "$S/$b.rev"; done < "$W/same.txt"
cat "$W/in.txt" "$W/same.txt" | sed 's/\.pack$/.idx/' \
  | git --git-dir "$g" multi-pack-index write --stdin-packs || { log "midx write FAILED"; exit 1; }
log "multi-pack index now covers only the new packs"
while read -r p; do mvpack "$P" "$A" "${p%.pack}" idx-first; done < "$W/out.txt"
git --git-dir "$g" multi-pack-index write && git --git-dir "$g" multi-pack-index verify \
  || log "midx rewrite/verify FAILED"
log "old packs moved to $A; objects/pack: $(ls *.pack | wc -l) packs, $(du -sb . | cut -f1) bytes"

# 4. every object reachable from every ref
missing=$(nice -n 5 git --git-dir "$g" rev-list --objects --all --missing=print | grep -c '^?')
log "rev-list --objects --all: $missing missing"
if [ "$missing" -ne 0 ]; then
  log "RESTORING old packs"
  while read -r p; do mvpack "$A" "$P" "${p%.pack}" idx-last; done < "$W/out.txt"
  git --git-dir "$g" multi-pack-index write
  exit 1
fi
log "DONE"
