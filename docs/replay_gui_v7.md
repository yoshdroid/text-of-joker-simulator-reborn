# replay GUI v7

保存済み replay を、イベント単位でシークできる GUI として確認できる。
V7-5 の可観測性強化として、両プレイヤーの手札、トリガーゾーン、捨札、デッキ、盤面、LIFE、CP、各 zone count、現在 event、event log を同じ画面に表示する。

## 起動

```powershell
python -m tojs_reborn.io.replay_gui --cards carddata/generated/cards.normalized.json --images carddata/images --replay test_output/replay.json
```

特定の event から開く場合:

```powershell
python -m tojs_reborn.io.replay_gui --cards carddata/generated/cards.normalized.json --images carddata/images --replay test_output/replay.json --start-event-no 42
```

GUI を開けない環境で、指定 frame の summary だけ確認する場合:

```powershell
python -m tojs_reborn.io.replay_gui --replay test_output/replay.json --start-event-no 42 --no-window
```

## 表示内容

- 左側: 両プレイヤーの status と各 zone。
- 右側: replay event log。現在 frame の event は `>` で示す。初期状態では画面幅の約半分を使い、境界はドラッグで変更できる。
- 下部: Play / Prev / Next / seek bar。

カード画像が見つからない場合は、card no と card name のテキストタイルで表示する。
既定のカード幅は 36px とし、手札などは以前の 72px 表示に対して面積がおよそ 1/4 になる。
大きく表示したい場合は `--card-width` で指定できる。
Battlefield の unit は 72px 幅で LV / BP を表示し、行動権を失っている場合は 90 度タップ表示にする。
Hand のカードは LV を表示する。
Deck / Discard はさらに半分のサイズで表示する。
右ペインの event log では、replay intent に記録された player action summary と `choice_selected` の選択内容を、対応する event の発生位置に太字で表示する。

## replay viewer の action 表示

`match_cli` / `match_batch_cli` で保存する replay intent には、選択時の `legal_actions` と `response` が残る。
テキスト viewer では `--show-actions` を付けると、各選択の selected action と legal action summary を確認できる。

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json --show-actions --no-payload
```
