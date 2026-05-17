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
- 右側: replay event log。現在 frame の event は `>` で示す。
- 下部: Play / Prev / Next / seek bar。

カード画像が見つからない場合は、card no と card name のテキストタイルで表示する。
