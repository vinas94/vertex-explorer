# vertex-explorer

A terminal UI for browsing Google Cloud Vertex AI Pipelines — schedules and their runs — across multiple GCP regions. Built with [Textual](https://textual.textualize.io).

Faster than clicking through the Cloud Console when you want to:

- See all your runs & schedules across regions at a glance
- Hunt for a specific run across every schedule via a flat tracker view
- Filter with substring matching plus `&` / `|` / parentheses
- Jump to the Cloud Console for any row with one keystroke

Two tabs:

- **Overview** — schedules on the left, runs of the selected schedule on the right. Synthetic "Unscheduled runs" bucket appears for runs without a parent schedule.
- **Tracker** — flat list of every run across every schedule, with the parent schedule's details (cron, next run, recent run history) inline when available. Multi-line filter (each line OR'd), state toggles for running / failed / cancelled.

Settings (project, regions, lookback windows) stored in `~/.config/vertex-explorer/settings.json` and are editable inline or via the settings menu.

## Install

```bash
uv tool install git+https://github.com/vinas94/vertex-explorer.git
```

Or with pipx:

```bash
pipx install git+https://github.com/vinas94/vertex-explorer.git
```

Either way you get the `ve` command on your `PATH`.

> **Tip:** pairs very nicely with [Ghostty](https://ghostty.org)'s drop-down terminal.

## First-run setup

1. Authenticate with gcloud:
   ```bash
   gcloud auth application-default login
   ```
2. Run `ve`.
3. Press `s` to open settings. Set your **Project** and **Regions**, then press `shift+enter` to save.

## Settings

Press `s` to open the settings menu. Each field:

- **Project** — your GCP project ID (e.g. `my-project-prod`). Required.
- **Regions** — comma-separated list of regions to query (e.g. `europe-west3, europe-west4`). One Vertex API call per region per fetch. Required.
- **Runs Days** — time window for fetching pipeline runs. Anything created in the last N days is included.
- **Schedules Days** — time window for fetching schedules. Schedules whose next-run time is no older than N days ago are included.
- **Short Regions** — when enabled, region cells render as `west3` instead of `europe-west3` to save horizontal space.

Settings persist to `~/.config/vertex-explorer/settings.json`. Tracker filter text is also saved there.

Navigate with arrow keys, `enter` to edit a field, `shift+enter` to save and close, `escape` to revert the focused field or close without saving.

## Keybindings

- **Tabs**: `tab` to cycle between Overview and Tracker.
- **Overview**: `f` filter, `r` cycle region, `a` toggle active, `o` open selected.
- **Tracker**: `f` filter, `r` cycle region, `a/d/c` toggle running/failed/cancelled, `o` open run, `O` open schedule.
- **Global**: `R` refresh, `s` settings, `q` quit.
