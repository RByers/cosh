#!/bin/bash
# Lossless repack of chromium-patchsets.git in groups of packs, keeping the old packs.
# Each group: pack-objects --stdin-packs --local (what `repack --geometric -l` runs),
# then verify-pack of the new pack. Run under the extract lock.
# Usage: chunked-repack.sh <git_dir> <before-list> <group size> <log>
set -uo pipefail
g=$1; before=$2; size=$3; log=$4
export GIT_NO_LAZY_FETCH=1
cd "$g" || exit 1
mapfile -t packs < "$before"
n=${#packs[@]}; i=0; grp=0; fail=0
while [ $i -lt $n ]; do
  grp=$((grp + 1))
  chunk=("${packs[@]:i:size}")
  i=$((i + size))
  echo "group $grp: ${#chunk[@]} packs, start $(date +%H:%M:%S)" >> "$log"
  out=$(printf '%s\n' "${chunk[@]}" | nice -n 5 git -c pack.threads=1 -c pack.windowMemory=1g \
        -c pack.deltaCacheSize=128m pack-objects --stdin-packs --local --delta-base-offset \
        --quiet objects/pack/pack 2>> "$log")
  rc=$?
  if [ $rc -ne 0 ] || [ -z "$out" ]; then
    echo "group $grp pack-objects FAILED exit $rc" >> "$log"; fail=1; break
  fi
  sz=$(stat -c %s "objects/pack/pack-$out.pack")
  if git -c pack.threads=2 verify-pack "objects/pack/pack-$out.idx" >> "$log" 2>&1; then
    echo "group $grp new pack-$out.pack $sz bytes, verified, $(date +%H:%M:%S)" >> "$log"
  else
    echo "group $grp new pack-$out.pack VERIFY FAILED" >> "$log"; fail=1; break
  fi
done
echo "all done fail=$fail $(date)" >> "$log"
exit $fail
