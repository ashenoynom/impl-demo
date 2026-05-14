# GOCE constellation streaming demo

Python scripts that stream GOCE-style telemetry (from a CSV replay) and simulated satellite logs into [Nominal](https://nominal.io). Timestamps in the CSV are replayed with preserved spacing so the stream behaves like live data.

## Prerequisites

- Python 3.11+ (3.13 works)
- **[Git LFS](https://git-lfs.com)** — required to get the full telemetry CSV from this repository (see [Checkout and full dataset](#checkout-and-full-dataset-git-lfs) below)
- A Nominal account and API token configured as a **named profile** on your machine

Configure Nominal once (install the CLI with `pip install nominal` if needed):

```bash
nominal config
```

Create a profile (for example `goce_streamer`) and note the profile name. The scripts default to `goce_streamer`; override with `--profile` if you use another name.

## Checkout and full dataset (Git LFS)

The full export `data/goce_72h_anomalous_recent.csv` (~90MB) is tracked with **Git LFS** (see `goce_constellation/.gitattributes`). Without LFS you only get a small pointer file, not the real CSV.

1. Install Git LFS: [git-lfs.com](https://git-lfs.com) (macOS: `brew install git-lfs`).
2. **Once per machine:** `git lfs install`.
3. Clone or pull this repo as usual. After clone, from the **repository root** (the `impl-demo` repo that contains `goce_constellation/`):

   ```bash
   git lfs pull
   ```

   If you already cloned before installing LFS, run `git lfs install` then `git lfs pull` from the same root.

4. **Confirm the full file** (optional but useful). From `goce_constellation/`:

   ```bash
   wc -c data/goce_72h_anomalous_recent.csv
   ```

   You want on the order of **tens of millions** of bytes (~90M). If you see only **~130 bytes**, you still have an LFS pointer — run `git lfs pull` from the repo root again.

**Without LFS:** use the committed sample only (`data/goce_72h_anomalous_sample.csv`), or copy any compatible full CSV to `data/goce_72h_anomalous_recent.csv` yourself. The sample matches the full export’s columns and timestamp format.

## Setup

From **this directory** (`goce_constellation/`):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Data files

| File | Purpose |
|------|---------|
| `data/goce_72h_anomalous_sample.csv` | Small slice (~5k rows), committed as normal git content for quick dry-runs without LFS. |
| `data/goce_72h_anomalous_recent.csv` | Full ~72h export (~90MB), **Git LFS** — follow [Checkout and full dataset](#checkout-and-full-dataset-git-lfs) above. |

The CSV streamer **defaults** to the full file when `data/goce_72h_anomalous_recent.csv` is present and non-trivial on disk; otherwise it uses the sample. You can always pass an explicit path:

```bash
python goce_csv_streamer.py --dry-run --csv data/goce_72h_anomalous_sample.csv
python goce_csv_streamer.py --dry-run --csv data/goce_72h_anomalous_recent.csv
```

## Run the CSV telemetry streamer

Dry-run (no API calls; validates CSV load and timing loop):

```bash
python goce_csv_streamer.py --dry-run
```

Stream to Nominal (creates or uses a dataset unless you pass a connection RID):

```bash
python goce_csv_streamer.py --profile goce_streamer
```

Useful options:

```text
--csv PATH          CSV file (default: full LFS file if present, else sample)
--profile NAME      Nominal profile (default: goce_streamer)
--speed-up FLOAT    Playback speed (default: 10.0 in script constants)
--num-satellites N  Override multi-satellite count
--connection-rid R  Stream to an existing connection instead of dataset mode
--dry-run           No Nominal writes
--test              Run the built-in phase-shift test and exit
```

Press Ctrl+C to stop streaming.

## Run the log streamer

Simulated log lines tagged like the telemetry stream (`satellite`, `shell`, etc.):

```bash
python goce_log_streamer.py --profile goce_streamer --dry-run
python goce_log_streamer.py --profile goce_streamer
```

Options: `--speed-up`, `--num-satellites`, `--dry-run`.

## Adding or updating the LFS file (maintainers)

After changing the large CSV, from the **impl-demo** repo root:

```bash
git lfs install   # once per machine
git add goce_constellation/.gitattributes goce_constellation/data/goce_72h_anomalous_recent.csv
git commit -m "chore: refresh GOCE LFS dataset"
git push          # uploads the LFS object to the remote LFS store
```

First-time contributors need push access and sufficient LFS quota on the hosting provider (GitHub, GitLab, etc.).

## Configuration

Behavior such as channel names, shells, phase shift, and batch size still lives in the `CONFIGURATION` section at the top of each script. Command-line flags override the most environment-specific values (paths, profile, speed, satellite count).
