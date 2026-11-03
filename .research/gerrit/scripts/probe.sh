#!/usr/bin/env bash
# Usage: probe.sh <name> <url>
# Polite single GET: gzip, 1.5s sleep after, logs request count + size + timing.
set -u
OUT=/home/rbagent/projects/cosh/.research/gerrit/responses
LOG=$OUT/_requests.log
name="$1"; url="$2"
curl -sS --compressed -A "cosh-research/0.1 (one-off probe)" \
  -D "$OUT/$name.headers" -o "$OUT/$name.body" \
  -w "%{http_code} size_download=%{size_download} time=%{time_total}\n" "$url" | tee -a /dev/stderr | \
  { read line; echo "$(date -u +%FT%TZ) $name $line $url" >> "$LOG"; }
sleep 1.5
echo "requests so far: $(wc -l < $LOG)"
