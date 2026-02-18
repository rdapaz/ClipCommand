# Changelog

All notable changes to ClipCommand are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.2.0] — 2025
### Added
- **Chain builder UI** — dynamic list of pipeline steps, each with its own
  dropdown, `[+]` (insert below) and `[−]` (remove) buttons. Step labels
  update automatically ("Step 1:" / "Then:").
- **Chain definitions in transforms.ini** — define named multi-step pipelines;
  they appear in the Step 1 dropdown prefixed with `⛓` and auto-expand into
  rows on selection.
- **Per-transform config overrides via transforms.ini** — set `BOOKMARK`,
  `HEADING_ROWS`, `DELIMITER`, or any other module-level constant without
  editing the script. Values are auto-coerced to int/float where applicable.
- **Dry run mode** — toggle with `🔍 Dry Run` button; status dot turns orange.
  Final pipeline output goes to a dedicated preview pane instead of the
  clipboard. Preview pane has Copy and Clear buttons.
- **Reload All** — hot-reloads every script in the current chain simultaneously.
- Stats bar now shows the full chain as `step1 → step2 → step3`.
- `transforms.ini` sample file with example chains and overrides.

### Changed
- Single-transform mode is unchanged in behaviour; chain rows simply collapse
  to one row.
- `_run_transform()` replaced by `_run_chain()` which handles 1..N steps.

---


## [1.1.0] — 2025
### Added
- **Transform folder picker** — scan `./transforms/` on startup and expose all
  scripts via a dropdown combobox; no restart needed to switch transforms.
- **Rescan button** — pick up newly added scripts without restarting.
- **Description strip** — module docstring displayed below the dropdown and as
  a hover tooltip so you always know what the active transform does.
- **Broken-script reporting** — scripts that fail to load appear in the dropdown
  with a `⚠` prefix and their load error shown in the description area.
- `--transforms` CLI flag to point at a custom folder.
- `--script` flag is now optional (pre-selects a script; falls back to first found).
- Selection memory across rescans — the active transform is re-selected after
  a folder rescan if it still exists.

### Changed
- Static script-path label replaced by the combobox selector.
- Stats bar now shows the active script name.
- Re-seeds `last_clip` on transform switch and on Resume to prevent spurious
  triggers.

---

## [1.0.0] — 2025
### Added
- Initial release.
- Dark-themed Tkinter UI with live activity log.
- Clipboard polling mode (configurable interval via `--poll`).
- Optional hotkey trigger mode via `--hotkey` (requires `keyboard` package).
- Pause / Resume toggle.
- Hot-reload of the active script without restarting (`⟳ Reload` button).
- `make_transforms.py` — generates 16 ready-to-use example transform scripts.
- Inspired by the Perl Monks `clipcommand.pl` by [Various Authors].
