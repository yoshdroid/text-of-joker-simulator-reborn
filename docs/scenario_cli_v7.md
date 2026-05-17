# scenario CLI v7

個別機能や個別カード効果を GUI で確認するため、固定シナリオから replay を生成する。

## 生成

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario all --verify
```

既定では `test_output/scenarios/` に replay を出力する。

利用できる scenario:

- `hand_limit_draw`: 手札 3 枚 / 2 枚からターン冒頭ドローを繰り返し、6->7 と 7->7 の手札上限制御を確認する。
- `new_armor_trigger`: `1-0-061` 新品の鎧が unit enter 後に強制発動し、deck から intercept を探して引く。
- `lina_discard_choice`: `1-0-031` 見習い魔導士リーナの OC で、捨札選択と `choice_selected` 表示を確認する。

## GUI で開く

単体シナリオは `--open-gui` で replay 生成後にそのまま開ける。

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --images carddata/images --scenario new_armor_trigger --verify --open-gui
```

既に生成した replay を開く場合:

```powershell
python -m tojs_reborn.io.replay_gui --cards carddata/generated/cards.normalized.json --images carddata/images --replay test_output/scenarios/hand_limit_draw.json
```
