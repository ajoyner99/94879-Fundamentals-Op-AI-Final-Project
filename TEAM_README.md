# Team README: 94-879 Track B Project

Team: Vidhi Kothari, Anastasia Joyner, Stephen Mai, Lauren Johnson

This repo contains the instructor-provided starter kit, the Track B challenge
package, and our team's work on challenges B1, B2, and B3.

## Tags (reference points)

| Tag            | Meaning                                                        |
|----------------|----------------------------------------------------------------|
| `base-package` | Starter kit + instructor Track B package. **Our starting point.** |

To see every change our team made:

```
git diff base-package --stat   # list of changed files
git diff base-package          # full changes
```

## Branches

| Branch         | Owner(s)     | Purpose                        |
|----------------|--------------|--------------------------------|
| `main`         | everyone     | Stable, working code only      |
| `b1`           | Ana & Lauren | B1: Falling Behind             |
| `B2---Stephen` | Stephen      | B2: Green but Broken           |
| [B3 branch]    | Vidhi        | B3: Healthy but Wrong?         |

Work is merged into `main` once it runs and has been reviewed by at least one teammate.

## Setup

covered in README.md

## Working rules

- `git pull` before starting work; `git push` when you stop.
- Check your branch (`git status`) before committing.
- Commit small, with descriptive messages (e.g., "B1: batch writes, size 50").
- Message teammates before editing a shared file (e.g., `featurizer.py`).
- Never use `git push --force` on `main`.