# Contributing

Thank you for your interest. Stage is built in small, measured steps, and contributions
are held to the same standard as the code: every change has a reason and a test.

## Set up

```bash
git clone https://github.com/danielomoteshohacks/stage-spatial-audio.git
cd stage-spatial-audio
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
ruff check . && pytest -q
```

## Workflow

1. Open or pick an issue. Experiments use the **Experiment** template: hypothesis, metric,
   pass condition, method.
2. Create a short branch: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `test/<topic>`.
3. Make small commits using [Conventional Commits](https://www.conventionalcommits.org/):
   `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`, `chore:`.
4. Open a pull request. CI must be green. Squash-merge.

## Rules of the project

- **No audio, models or datasets in Git.** Record them in a manifest with source and licence.
- **No Spotify content.** Do not use Spotify audio, previews or API data in code, tests, demos or training.
- **Every claim has a measurement.** Results are reported with sample sizes and intervals.
- **Comments explain why, not what.**
- **The Python implementation is the reference.** Other implementations must match its golden files.
