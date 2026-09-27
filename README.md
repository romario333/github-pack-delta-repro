# GitHub pack delta repro

Small edits pushed to many similar, large files come back from GitHub as large cross-file deltas. A fresh clone gets a pack about 3.5x larger than the same history after a local `git repack -a -d -f`.

Found while investigating why a full clone of [openclaw/openclaw](https://github.com/openclaw/openclaw) is 6.2 GB when a local repack brings it to 1.2 GB. There, a bot commits 20 locale translation-memory files (2-4 MB of JSONL each) several times a day, changing a line or two per file.

## What the script does

`repro.py` needs only `git` and Python 3.

1. Generates N synthetic JSONL files that share keys and English text but have different "translations". Each file is sorted by a per-file hash, like the original locale files.
2. Pushes an initial commit to a new branch.
3. Pushes a series of commits. Each one updates one line's timestamp and inserts one new line in every file.
4. For each push, rebuilds the pack `git push` sends (`pack-objects --revs --thin`) and records how the new blobs are deltified.
5. Fresh-clones the branch and records how GitHub serves the same blobs.
6. Repacks the clone locally with `git repack -a -d -f` and records the result.

```
python3 repro.py git@github.com:<you>/<empty-repo>.git            # 20 files x 8000 lines, 30 commits
python3 repro.py <url> --files 20 --lines 8000 --commits 10 --branch my-run
```

A default run takes about 5 minutes and pushes about 50 MB.

## Results

Runs from 2026-09-27, git 2.50.1 on macOS, pushing over SSH to a private repository.

Default run, 20 files x 8000 lines (about 2.5 MB each), 30 commits, 600 new blobs:

| | same-file deltas | cross-file deltas | clone pack size |
|---|---|---|---|
| Client push packs | 600 (0.19 MB) | 0 | |
| GitHub fresh clone | 464 (0.13 MB) | 133 (82.8 MB) | 93.2 MiB |
| After local `repack -a -d -f` | 576 (0.08 MB) | 0 | 26.2 MiB |

An earlier identical run gave 141 cross-file deltas (87.8 MB) and a 87.3 MiB pack.

Every blob the client pushed was a delta of a few hundred bytes against the previous version of the same file. In the pack GitHub serves, about a quarter of them are instead deltas against another file, around 600 KB each.

Other sizes:

| files x lines | commits | cross-file deltas served | served vs repacked pack | reproduced |
|---|---|---|---|---|
| 20 x 8000 | 30 | 133-141 | 87-93 vs 26 MiB | yes |
| 20 x 8000 | 10 | 30 | 20.1 vs 16.8 MiB | yes |
| 20 x 8000 | 3 | 0 | 12.3 vs 13.3 MiB | no |
| 20 x 4000 | 10 | 0 | 6.2 vs 8.4 MiB | no |
| 20 x 2000 | 30 | 0 | 3.2 vs 6.6 MiB | no |
| 10 x 8000 | 10 | 9 | 6.4 vs 8.4 MiB | unclear |
| 5 x 8000 | 30 | 0 | 3.5 vs 5.5 MiB | no |
| 2 x 8000 | 30 | 0 | 1.7 vs 4.4 MiB | no |

The effect needs many similar files, files of a few MB, and enough pushes. It grows with the number of pushes. Every clone was taken within minutes of the last push.

A local `repack -f` also produces a few cross-file deltas, usually about one per file. Git's delta window only looks at objects sorted before the current one, so the newest version of each file is compared against the previous file's versions. That is expected Git behavior and doesn't explain the counts above.

## Open question

The client sends good deltas, and a local repack produces good deltas. Something between receiving the push and serving the clone replaces some of them with cross-file deltas. This repo can't show whether that is GitHub's storage maintenance or the pack generation for the clone.
