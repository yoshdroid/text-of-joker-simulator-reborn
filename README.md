# Text of Joker Simulator Reborn

Text of Joker Simulator Reborn is a Python prototype for simulating a
Code of Joker-like card game, generating deterministic replays, and reviewing
matches with a small GUI.

As of the end of v8, the project is already playable:

- 100 card pool entries are normalized from card data.
- Unit drive, evolve, override, trigger/intercept windows, battle, blocking,
  clock up, deck refresh, mulligan, and replay verification are implemented.
- GUI replay review shows board state, hands, trigger zones, event logs,
  highlighted cards, tapped units, LV/BP display, and colored ability logs.
- Scenario replays are available for focused visual checks.
- v9 is now focused on card-addition workflow and smaller missing game rules.

## Requirements

- Python 3.11 or later
- Optional: Pillow, for card image rendering in the replay GUI

The project is usually run directly from the repository root with `python -m`.

## Quick Start

Run a match between the Codex yellow deck/player and the imported
`g_b_controlbeat` deck:

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/codex_yellow_v1_0.json --deck2 decklists/g_b_controlbeat.json --p1 "cmd:python -m tojs_reborn.io.player_codex" --p2 sample:aggressive --seed 9001 --max-turns 20 --max-actions-per-turn 30 --strict-deck-rule --verify-replay --check-integrity --replay test_output/matches/codex_yellow_v1_0_vs_g_b_controlbeat_seed9001.json
```

Open the generated replay in the GUI:

```powershell
python -m tojs_reborn.io.replay_gui --replay test_output/matches/codex_yellow_v1_0_vs_g_b_controlbeat_seed9001.json --cards carddata/generated/cards.normalized.json --images carddata/images --fullscreen
```

If you only want to check that the GUI model can be built without opening a
window:

```powershell
python -m tojs_reborn.io.replay_gui --replay test_output/matches/codex_yellow_v1_0_vs_g_b_controlbeat_seed9001.json --cards carddata/generated/cards.normalized.json --no-window
```

## Replay And Scenario Workflow

Generate and verify every GUI scenario:

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario all --verify
```

Open one scenario directly in the GUI:

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario v8_remaining_intercepts --open-gui
```

Regenerate the scenario catalog:

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario all --catalog-markdown docs/scenario_catalog.md
```

Useful documents:

- `docs/scenario_catalog.md`: generated list of available scenarios
- `docs/scenario_cli_v7.md`: visual-check notes and scenario status
- `docs/impl_spec_v8.md`: v8 implementation notes
- `docs/impl_spec_v9.md`: v9 plan and card-addition foundation
- `docs/card_status_v9.md`: generated card implementation status

## Decks And Players

Decks live in `decklists/`.

Current notable decks:

- `codex_yellow_v1_0.json`: yellow/colorless deck used by `player_codex`
- `g_b_controlbeat.json`: imported green/blue control-beat deck
- `r_g_beatdown.json`: imported red/green beatdown deck

Player specs accepted by `match_cli`:

- `sample:first`
- `sample:pass`
- `sample:random`
- `sample:aggressive`
- `sample:intercept_all`
- `cmd:<command>` for an external JSON Lines player process

The Codex player can be run as:

```powershell
python -m tojs_reborn.io.player_codex
```

In `match_cli`, use it through `cmd:`:

```powershell
--p1 "cmd:python -m tojs_reborn.io.player_codex"
```

## Replay GUI Notes

The replay GUI is designed for visual debugging and game review.

Useful options:

- `--fullscreen`: start maximized/fullscreen
- `--start-event-no <N>`: jump to an event
- `--play-delay-ms <N>`: control playback speed
- `--card-width <N>` and `--card-scale <N>`: adjust card display size
- `--no-window`: print a frame summary instead of opening Tk

Ability log lines are colored by source card color. Intercept cards that are
visible but cannot activate can show compact inactive reasons such as CP
shortage or missing same-color unit.

## Tests

Run the core pytest suite:

```powershell
python -m pytest tests/test_cardpool_normalizer.py tests/test_decklist.py tests/test_engine.py tests/test_protocol.py -q
```

Run unittest discovery:

```powershell
python -m unittest discover
```

Run scenario verification:

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario all --verify
```

On some Windows environments, pytest may print `.pytest_cache` permission
warnings. They are cache write warnings and do not necessarily indicate test
failure.

## Card Data Development

The current v9 direction is to make card additions easier and safer:

- keep card definitions in data where possible
- split future `ability_mapping.json` files by card set/sheet
- generate status reports and scenario catalogs
- add focused engine tests and GUI scenarios per card or mechanic
- commit each small verified unit

The main generated card pool is:

```text
carddata/generated/cards.normalized.json
```

The current manual ability mapping is:

```text
carddata/manual/ability_mapping.json
```

Future split mappings are expected to use a structure like:

```text
carddata/manual/abilities/1-0/ability_mapping.json
carddata/manual/abilities/1-0-EX/ability_mapping.json
carddata/manual/abilities/1-1/ability_mapping.json
```

## Project Status

v8 is treated as the first broadly playable milestone. v9 is the ongoing
iteration for cleaner card addition, better diagnostics, and remaining game
rules.
