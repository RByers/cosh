#!/usr/bin/env bash
# strip Gerrit XSSI prefix: strip.sh <file.body>  -> stdout JSON
tail -c +6 "$1"
