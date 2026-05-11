# V4 Replay Viewer

## 実装内容

- `mulligan_performed` を replay viewer の内部 state tracker に反映するようにした。
- `--event-type <type>` を追加し、指定した event type だけ表示できるようにした。
- `--only-state` を追加し、turn end / match end の state snapshot だけ確認できるようにした。

## テスト

- mulligan 後の hand / deck count が viewer の state 表示へ反映されること。
- `event_types` filter と `only_state` を同時に使えること。
- 既存 engine / protocol テスト全体。

## 確認コマンド

```powershell
python -m unittest tests.test_engine tests.test_protocol -v
```
