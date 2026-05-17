# match CLI v7

v7 では sample bot、batch smoke、ruleset 定数、integrity check、replay / GUI の可観測性を追加した。

## sample bot

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:random --p2 sample:aggressive --seed 7 --max-turns 10 --replay test_output/v7_replay.json --verify-replay --check-integrity
```

- `sample:random`: seed と player id から deterministic RNG を作り、合法手をランダム選択する。
- `sample:aggressive`: attack、block、intercept、evolve、drive、trigger set を優先する。

## batch smoke

```powershell
python -m tojs_reborn.io.match_batch_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:random --p2 sample:aggressive --seeds 1-10 --max-turns 10 --verify-replay --check-integrity
```

結果は seed ごとに JSON Lines で出力する。
失敗時、または `--save-all-replays` 指定時は `BattleLogs/` に replay を保存する。

## ruleset / integrity

v7 の ruleset 定数は `tojs_reborn.engine.rules` に集約している。

- hand 上限: 7
- battlefield unit 上限: 5
- trigger zone 上限: 4
- CP 上限: 12
- 初期手札: 4
- 初期 LIFE: 7

`--check-integrity` を付けると、match runner が主要な状態遷移後に `assert_game_state_integrity` を実行する。

## replay viewer

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/v7_replay.json --show-actions --no-payload
```

`--show-actions` は replay intent に記録された selected action と legal action summary を表示する。
