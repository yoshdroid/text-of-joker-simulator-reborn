# 2026-05-11 v1 window runner

## Goal

Implement the minimal v1 trigger / intercept window runner, replacing the previous candidate-only window with executable processing.

## Implemented

- Added `process_trigger_window`.
  - Starts from the turn player.
  - Checks trigger zone left-to-right.
  - Activates one matching trigger, then switches to the opponent side.
  - Stops after both sides have no matching trigger.
- Added `process_intercept_window`.
  - Alternates confirmation from turn player to opponent.
  - Supports `activate_intercept` and `pass_window`.
  - Closes after two consecutive passes.
- Added event records:
  - `trigger_window_opened`
  - `trigger_activated`
  - `intercept_window_opened`
  - `intercept_activated`
  - `intercept_passed`
- Added timing keys:
  - `TRIGGER_ANY`
  - `INTERCEPT_ANY`
  - `INTERCEPT_ATTACK`
- Added tests for trigger order and intercept pass closure.

## Remaining Notes

- The runner is still an explicit API. A future match-runner step should decide which game events automatically open trigger and intercept windows.
- Trigger timing currently supports `TRIGGER_ANY` and `TRIGGER_<EVENT_TYPE>`.
- Intercept timing currently supports `INTERCEPT_ANY` and `INTERCEPT_<WINDOW>`.

## Verification

```text
python -m unittest -v
Ran 39 tests
OK
```
