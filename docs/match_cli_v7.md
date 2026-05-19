# match CLI v7

v7 では sample bot、match smoke、integrity check、replay verify、replay GUI による通常 match 確認を整備した。

## sample match

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:random --p2 sample:aggressive --seed 7 --max-turns 10 --replay test_output/v7_replay.json --verify-replay --check-integrity
```

- `sample:random`: match seed と player id から deterministic RNG を作り、合法手をランダム選択する。
- `sample:aggressive`: attack、block、intercept、evolve、drive、trigger set を優先する。
- `sample:intercept-all`: window 中は発動可能な intercept を最優先で発動し、それ以外は aggressive と同じ優先順で行動する。
- `--verify-replay`: 保存した intent と event log を再実行して一致を確認する。
- `--check-integrity`: 主要 action 後に state integrity を検査する。

## batch smoke

```powershell
python -m tojs_reborn.io.match_batch_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:random --p2 sample:aggressive --seeds 1-10 --max-turns 10 --verify-replay --check-integrity
```

結果は seed ごとの JSON Lines で出力する。`--save-all-replays` を付けると `BattleLogs/` に replay を保存する。

## imported v7 decks

旧開発版の `configs/decks/gb_controlbeat.json` と `configs/decks/rg_beatdown.json` を、カード名指定の 40 枚デッキとして取り込んだ。

- `decklists/g_b_controlbeat.json`
- `decklists/r_g_beatdown.json`

## v7 baseline replay

v8 の通常 match 挙動確認のベースラインとして、次のコマンドで replay を生成する。

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/g_b_controlbeat.json --deck2 decklists/r_g_beatdown.json --p1 sample:random --p2 sample:aggressive --seed 7 --max-turns 20 --replay test_output/g_b_controlbeat_vs_r_g_beatdown.json --verify-replay --check-integrity --strict-deck-rule
```

2026-05-19 時点の生成結果:

- replay: `test_output/g_b_controlbeat_vs_r_g_beatdown.json`
- winner: `P2`
- reason: `life_zero`
- turn_count: `12`
- event_count: `277`

## replay viewer

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/g_b_controlbeat_vs_r_g_beatdown.json --show-actions --no-payload
```

`--show-actions` は replay intent に記録された selected action と legal action summary を表示する。

## replay GUI

通常 match の replay も scenario replay と同じ GUI で確認できる。

```powershell
python -m tojs_reborn.io.replay_gui --cards carddata/generated/cards.normalized.json --images carddata/images --replay test_output/g_b_controlbeat_vs_r_g_beatdown.json --fullscreen
```

- `--play-delay-ms`: Play のコマ送り間隔をミリ秒で指定する。デフォルトは `225`。
- `--fullscreen`: 起動時に最大化する。
- `--start-event-no`: 指定 event の frame から開く。

## ruleset / integrity memo

v7 の主要 ruleset 定数は `tojs_reborn.engine.rules` に集約している。

- hand 上限: 7
- battlefield unit 上限: 5
- trigger zone 上限: 4
- CP 上限: 12
- 初期手札: 4
- 初期 LIFE: 7

`python -m pytest tests -q` は v7 の標準確認コマンドとする。repo 直下に権限なしの `pytest-cache-files-*` が残っている場合、`python -m pytest -q` はそれらを収集しようとして失敗することがある。
