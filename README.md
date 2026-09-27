# GitHub stores small edits as huge deltas

If you push small edits to many similar, large files, one push at a time, a fresh clone from GitHub ends up about 3x larger than it needs to be.

Git normally stores a changed file as a small patch against its previous version. Here, GitHub often stores it as a patch against a *different* file instead. That patch is almost as big as the whole file.

## Why this matters

A full clone of [openclaw/openclaw](https://github.com/openclaw/openclaw) is 6.2 GB. After `git repack -a -d -f` it's 1.2 GB. Most of the waste is in 20 translation files of a few MB each, which a bot updates several times a day.

## Run it

You need bash, awk and git, plus an empty GitHub repo you can push to.

```
./repro.sh git@github.com:<you>/<empty-repo>.git
```

The script creates 20 similar files of about 2 MB each. It then makes 30 commits, each changing two lines per file, and pushes after every commit. Finally it clones the repo fresh and compares GitHub's pack with a local repack. It takes about 4 minutes.

## Results

| | Clone size | After local repack |
|---|---|---|
| 30 commits, 30 pushes | 82 MiB | 28 MiB |
| 30 commits, 1 push | 16 MiB | 28 MiB |

The files and commits are the same in both rows. Only the number of pushes differs. To try the single push yourself, run `./repro.sh <url> run-once 20 8000 30 once`.

What we know:

- Git sends each change as a patch of a few hundred bytes against the same file. The damage happens later, on GitHub's side.
- It takes about 10 or more pushes. 3 pushes weren't enough.
- It takes many files (20 reproduced it, 5 didn't) of a few MB each (files of about 1 MB didn't reproduce it).

What we don't know is why GitHub does this. Only GitHub can see that.
