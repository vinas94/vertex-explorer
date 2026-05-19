# vertex-explorer

Terminal UI for browsing Google Vertex AI Pipelines (schedules and runs) across multiple GCP regions.

## Install

```bash
uv tool install git+https://github.com/<org>/vertex-explorer.git
```

Or with pipx:

```bash
pipx install git+https://github.com/<org>/vertex-explorer.git
```

Either way you get the `ve` command on your `PATH`.

## First-run setup

1. Authenticate with gcloud:
   ```bash
   gcloud auth application-default login
   ```
2. Run `ve`.
3. Press `s` to open settings. Set your **Project** and **Regions**, then press `shift+enter` to save.

## Keybindings

- **Tabs**: `tab` to cycle between Overview and Tracker.
- **Overview**: `f` filter, `r` cycle region, `a` only active, `o` open in console, `O` open parent schedule.
- **Tracker**: `f` filter, `r` cycle region, `a/d/c` toggle running/failed/cancelled, `o` open run, `O` open parent schedule.
- **Global**: `R` refresh, `s` settings, `q` quit.

## Development

```bash
git clone https://github.com/<org>/vertex-explorer.git
cd vertex-explorer
uv sync
uv run ve
```

```bash
make test     # run pytest
make lint     # run ruff
make format   # apply ruff fixes
```
