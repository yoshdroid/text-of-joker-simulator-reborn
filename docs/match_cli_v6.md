# v6 Match CLI 確認手順

v6 の確認用 decklist はカード名指定で作成する。

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/v6_p1.json --deck2 decklists/v6_p2.json --p1 sample:first --p2 sample:first --seed 6 --max-turns 20 --replay test_output/v6_replay.json --verify-replay
```

replay viewer でイベントとターン終了時の盤面を確認する。

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/v6_replay.json --no-payload
```

今回の主な確認用カード:

- `1-0-042` ケロール・キッド: OC 時の永続基本BP低下。
- `1-0-041` フォクスコマンドー: OC 時の強制 cost choice。
- `1-0-010` 不知火伍式: attack 時の強制 cost choice。
- `1-0-047` ダルタニャン: CIP で CP+2、attack 時に 1 draw。
- `1-0-016` 金色の狛犬: OC 時に相手ユニットの行動権を消費する。
- `1-0-003` バク・ダルマン: 相手全ユニット対象。
- `1-0-005` ヘルハウンド: 相手 trigger zone のランダム破壊。
- `1-0-033` ヴァイパー: 捨札のユニットをランダムに手札へ戻す。
- `1-0-028` スカルウォーカー: 破壊時に捨札のユニットをランダムに手札へ戻す。
- `1-0-031` 見習い魔導士リーナ: OC 時に捨札のカードを選んで手札へ戻す。
- `1-0-020` カイム: デッキからトリガーカードだけを探して引く。
- `1-0-019` ジャンプー: 相手ユニットを手札へ戻す。手札7枚時は捨札へ送る。
