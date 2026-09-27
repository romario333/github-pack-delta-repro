#!/usr/bin/env bash
# Minimal repro: small edits to many similar multi-MB files come back from GitHub
# as large cross-file deltas.
# Usage: ./repro.sh <url-of-empty-github-repo> [branch] [files=20] [lines=8000] [commits=30] [push=each|once]
set -euo pipefail
remote=$1 branch=${2:-run-$(date +%Y%m%d-%H%M%S)} files=${3:-20} lines=${4:-8000} commits=${5:-30} push=${6:-each}
work=$(mktemp -d) && cd "$work"
git init -q -b "$branch" src && cd src && mkdir data

# Files share keys, English text and its hash; translations, cache keys and line
# order differ per file. Random hex and letters keep the data hard to compress.
for i in $(seq -w 1 "$files"); do
  awk -v n="$lines" -v f="$i" '
    function hex(len,  s) { s = ""; while (length(s) < len) s = s sprintf("%08x", int(rand() * 4294967296)); return s }
    function word(  s, j) { s = ""; for (j = int(rand() * 8) + 3; j > 0; j--) s = s sprintf("%c", 97 + int(rand() * 26)); return s }
    BEGIN {
      for (k = 1; k <= n; k++) {
        srand(k); en = word(); for (w = 0; w < 5; w++) en = en " " word(); th = hex(64)
        srand(f * 1000003 + k); tr = word(); for (w = 0; w < 5; w++) tr = tr " " word(); ck = hex(64)
        printf "%s {\"cache_key\":\"%s\",\"key\":\"k%06d\",\"text\":\"%s\",\"text_hash\":\"%s\",\"translated\":\"%s\",\"updated_at\":\"2026-01-01\"}\n", ck, ck, k, en, th, tr
      } }' | sort | cut -d' ' -f2- > "data/f$i.jsonl"
done
git add data && git commit -qm initial && git push -q "$remote" "HEAD:refs/heads/$branch"

# Each commit changes one line and inserts one line in every file.
for c in $(seq 1 "$commits"); do
  for f in data/*.jsonl; do
    awk -v c="$c" -v n="$lines" -v seed="$c$RANDOM" 'BEGIN { srand(seed); a = int(rand() * n) + 1; b = int(rand() * n) + 1 }
      NR == a { sub(/"updated_at":"[^"]*"/, "\"updated_at\":\"commit-" c "\"") }
      NR == b { print "{\"key\":\"new" c "\",\"text\":\"new string " c "\",\"translated\":\"x\",\"updated_at\":\"commit-" c "\"}" }
      { print }' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  done
  git commit -qam "commit $c"
  if [ "$push" = each ]; then git push -q "$remote" "HEAD:refs/heads/$branch"; fi
done
if [ "$push" = once ]; then git push -q "$remote" "HEAD:refs/heads/$branch"; fi

# Count blobs stored as deltas against a different file.
stats() {
  git -C "$1" rev-list --objects --all | awk '$2 ~ /^data\// { print $1, $2 }' > "$work/paths"
  git -C "$1" verify-pack -v "$1"/.git/objects/pack/*.idx | awk 'NF >= 7 && $2 == "blob" { print $1, $7, $4 }' > "$work/deltas"
  awk 'NR == FNR { p[$1] = $2; next } ($1 in p) && ($2 in p) && p[$1] != p[$2] { n++; s += $3 }
    END { printf "cross-file deltas: %d (%.1f MB), ", n, s / 1e6 }' "$work/paths" "$work/deltas"
  git -C "$1" count-objects -vH | grep size-pack
}
git clone -q --no-checkout --single-branch --branch "$branch" "$remote" "$work/clone"
echo "GitHub fresh clone:     $(stats "$work/clone")"
git -C "$work/clone" repack -a -d -f -q
echo "after repack -a -d -f:  $(stats "$work/clone")"
rm -rf "$work"
