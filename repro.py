#!/usr/bin/env python3
"""Minimal repro: GitHub serves small edits to similar files as large cross-file deltas.

Creates N similar JSONL files (same keys and English text, different "translations",
each sorted by a per-file hash), then pushes a series of commits that change 1-2 lines
in every file. For each commit it records how the client's push pack deltifies the new
blobs, then fresh-clones the branch and reports how GitHub serves them.
"""
import argparse
import hashlib
import json
import os
import random
import string
import subprocess
import tempfile
from datetime import datetime, timezone


def git(*args, cwd, stdin=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, input=stdin, check=True, capture_output=True
    ).stdout


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def words(rng, count):
    return [
        "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 10)))
        for _ in range(count)
    ]


def generate(root, nfiles, nlines):
    base_rng = random.Random(0)
    vocab = words(base_rng, 3000)
    english = [" ".join(base_rng.choices(vocab, k=base_rng.randint(2, 8))) for _ in range(nlines)]
    os.makedirs(f"{root}/data", exist_ok=True)
    for i in range(nfiles):
        lang = f"lang{i:02d}"
        rng = random.Random(1000 + i)
        lang_vocab = words(rng, 3000)
        rows = [
            {
                "cache_key": sha(f"{k}:{lang}"),
                "segment_id": f"segment.{k}",
                "text": text,
                "text_hash": sha(text),
                "tgt_lang": lang,
                "translated": " ".join(rng.choices(lang_vocab, k=len(text.split()))),
                "updated_at": "2026-01-01T00:00:00.000Z",
            }
            for k, text in enumerate(english)
        ]
        write_rows(f"{root}/data/{lang}.jsonl", rows)


def write_rows(path, rows):
    rows.sort(key=lambda row: row["cache_key"])
    with open(path, "w") as out:
        for row in rows:
            out.write(json.dumps(row, separators=(",", ":")) + "\n")


def mutate(root, step, rng):
    """Mirror a locale refresh: touch one entry's timestamp and add one new entry."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for name in sorted(os.listdir(f"{root}/data")):
        path = f"{root}/data/{name}"
        with open(path) as src:
            rows = [json.loads(line) for line in src]
        rows[rng.randrange(len(rows))]["updated_at"] = stamp
        lang = name.removesuffix(".jsonl")
        text = f"new string {step}"
        rows.append(
            {
                "cache_key": sha(f"new{step}:{lang}"),
                "segment_id": f"segment.new{step}",
                "text": text,
                "text_hash": sha(text),
                "tgt_lang": lang,
                "translated": f"{lang} translation {step}",
                "updated_at": stamp,
            }
        )
        write_rows(path, rows)


def blob_paths(repo):
    paths = {}
    for line in git("rev-list", "--objects", "--all", cwd=repo).decode().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].startswith("data/"):
            paths[parts[0]] = parts[1]
    return paths


def pack_entries(pack_dir):
    """Map blob sha -> (size in pack, delta base sha or None)."""
    entries = {}
    for name in os.listdir(pack_dir):
        if not name.endswith(".idx"):
            continue
        out = git("verify-pack", "-v", f"{pack_dir}/{name}", cwd=pack_dir).decode()
        for line in out.splitlines():
            cols = line.split()
            if len(cols) >= 5 and cols[1] == "blob":
                entry = (int(cols[3]), cols[6] if len(cols) >= 7 else None)
                # index-pack --fix-thin appends thin-pack bases as full copies;
                # keep the delta the blob was actually sent as.
                if entries.get(cols[0], (0, None))[1] is None:
                    entries[cols[0]] = entry
    return entries


def classify(blobs, paths, entries):
    stats = {"full": 0, "same": 0, "cross": 0, "same_bytes": 0, "cross_bytes": 0}
    for blob in blobs:
        size, base = entries[blob]
        if base is None:
            stats["full"] += 1
        elif paths.get(base) == paths[blob]:
            stats["same"] += 1
            stats["same_bytes"] += size
        else:
            stats["cross"] += 1
            stats["cross_bytes"] += size
    return stats


def new_blobs(repo, commit):
    out = git("diff-tree", "-r", "--no-commit-id", commit, "--", "data", cwd=repo).decode()
    return [line.split()[3] for line in out.splitlines()]


def client_push_pack(repo, remote_ref, scratch):
    """Build the pack `git push` sends (send-pack runs pack-objects --revs --thin)."""
    pack = git(
        "pack-objects", "--revs", "--thin", "--delta-base-offset", "--stdout",
        cwd=repo, stdin=f"HEAD\n^{remote_ref}\n".encode(),
    )
    git("index-pack", "--fix-thin", "--stdin", cwd=scratch, stdin=pack)


def size_pack(repo):
    for line in git("count-objects", "-v", cwd=repo).decode().splitlines():
        if line.startswith("size-pack:"):
            return int(line.split()[1]) / 1024


def fmt(label, stats, count):
    return (
        f"{label:<22} {count:>5} blobs | full {stats['full']:>4} | "
        f"same-file {stats['same']:>4} ({stats['same_bytes'] / 1e6:7.2f} MB) | "
        f"cross-file {stats['cross']:>4} ({stats['cross_bytes'] / 1e6:7.2f} MB)"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("remote", help="Git URL of an empty test repository")
    parser.add_argument("--files", type=int, default=20)
    parser.add_argument("--lines", type=int, default=8000)
    parser.add_argument("--commits", type=int, default=30)
    parser.add_argument("--branch", default=f"run-{datetime.now():%Y%m%d-%H%M%S}")
    args = parser.parse_args()

    work = tempfile.mkdtemp(prefix="pack-delta-repro-")
    src, scratch, clone = f"{work}/src", f"{work}/scratch.git", f"{work}/clone"
    git("init", "-q", "-b", args.branch, src, cwd=work)
    git("init", "-q", "--bare", scratch, cwd=work)
    with open(f"{scratch}/objects/info/alternates", "w") as alt:
        alt.write(f"{src}/.git/objects\n")

    generate(src, args.files, args.lines)
    git("add", "data", cwd=src)
    git("commit", "-q", "-m", "initial data", cwd=src)
    git("remote", "add", "origin", args.remote, cwd=src)
    git("push", "-q", "origin", f"HEAD:refs/heads/{args.branch}", cwd=src)
    git("fetch", "-q", "origin", args.branch, cwd=src)
    print(f"branch {args.branch}: {args.files} files x {args.lines} lines, "
          f"{args.commits} commits, work dir {work}")

    rng = random.Random(42)
    pushed = []
    for step in range(1, args.commits + 1):
        mutate(src, step, rng)
        git("add", "data", cwd=src)
        git("commit", "-q", "-m", f"refresh {step}", cwd=src)
        client_push_pack(src, f"origin/{args.branch}", scratch)
        git("push", "-q", "origin", f"HEAD:refs/heads/{args.branch}", cwd=src)
        git("fetch", "-q", "origin", args.branch, cwd=src)
        pushed += new_blobs(src, "HEAD")

    paths = blob_paths(src)
    sent = classify(pushed, paths, pack_entries(f"{scratch}/objects/pack"))
    git("clone", "-q", "--no-checkout", "--single-branch", "--branch", args.branch,
        args.remote, clone, cwd=work)
    served = classify(pushed, paths, pack_entries(f"{clone}/.git/objects/pack"))
    served_size = size_pack(clone)
    git("repack", "-a", "-d", "-f", "-q", cwd=clone)
    repacked = classify(pushed, paths, pack_entries(f"{clone}/.git/objects/pack"))

    print(fmt("client push packs", sent, len(pushed)))
    print(fmt("GitHub fresh clone", served, len(pushed)))
    print(fmt("after repack -a -d -f", repacked, len(pushed)))
    print(f"clone size-pack: {served_size:.1f} MiB served, {size_pack(clone):.1f} MiB after local repack")


if __name__ == "__main__":
    main()
