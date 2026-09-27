# GitHub pack delta repro

Small edits to many similar multi-MB files, pushed one commit per push, come back from GitHub as large cross-file deltas. A fresh clone gets a pack about 3x larger than the same history after a local `git repack -a -d -f`.

Found while investigating why a full clone of [openclaw/openclaw](https://github.com/openclaw/openclaw) is 6.2 GB when a local repack brings it to 1.2 GB. There, a bot pushes changes to 20 locale translation-memory files (2-4 MB of JSONL each) several times a day, changing a line or two per file.

## Run it

`repro.sh` needs bash, awk, sort and git. Point it at an empty GitHub repository you can push to:

```
./repro.sh git@github.com:<you>/<empty-repo>.git [branch] [files=20] [lines=8000] [commits=30] [push=each|once]
```

It generates similar JSONL files (shared keys, English text and text hashes; per-file translations, cache keys and line order), commits and pushes them, then makes commits that each change one line and insert one line in every file. With `push=each` every commit is its own `git push`. With `push=once` all commits go in one push. Finally it fresh-clones the branch, counts blobs stored as deltas against a different file, repacks locally and counts again.

A default run takes about 4 minutes and pushes about 45 MB.

## Results

Runs from 2026-09-27, git 2.50.1 on macOS, pushing over SSH. 20 files x 8000 lines (about 2.2 MB each), 30 commits:

| | cross-file deltas in GitHub's pack | GitHub's pack | after local `repack -a -d -f` |
|---|---|---|---|
| `push=each` (30 pushes) | 87 (56.6 MB) | 82.4 MiB | 28.4 MiB, 0 cross-file deltas |
| `push=once` (1 push) | 18 (11.7 MB) | 16.0 MiB | 28.3 MiB, 0 cross-file deltas |

Same commits, same data. The blowup only appears when the history arrives in many pushes.

An earlier Python version of this repro (`repro.py` in this repository's git history) also rebuilt the pack each `git push` sends, using `pack-objects --revs --thin`. The client sent every changed file as a delta of a few hundred bytes against the previous version of the same file, with no cross-file deltas. That version pushed once per commit and varied the sizes:

| files x lines | pushes | cross-file deltas served | served vs repacked pack | reproduced |
|---|---|---|---|---|
| 20 x 8000 | 30 | 133-141 | 87-93 vs 26 MiB | yes |
| 20 x 8000 | 10 | 30 | 20.1 vs 16.8 MiB | yes |
| 20 x 8000 | 3 | 0 | 12.3 vs 13.3 MiB | no |
| 20 x 4000 | 10 | 0 | 6.2 vs 8.4 MiB | no |
| 20 x 2000 | 30 | 0 | 3.2 vs 6.6 MiB | no |
| 10 x 8000 | 10 | 9 | 6.4 vs 8.4 MiB | unclear |
| 5 x 8000 | 30 | 0 | 3.5 vs 5.5 MiB | no |
| 2 x 8000 | 30 | 0 | 1.7 vs 4.4 MiB | no |

The effect needs many similar files, files of a few MB, and many pushes. Every clone was taken within minutes of the last push.

## Open question

The client sends good deltas, and a local repack produces good deltas. Something on GitHub's side between receiving many pushes and serving a clone replaces some of them with cross-file deltas. This repo can't show whether that is storage maintenance triggered by the pushes or how the pack for the clone is generated.
