# v3 Match CLI 実行手順

## 1. decklist JSON

v3 の decklist は下記形式で作成する。

```json
{
  "deck_name": "sample",
  "cards": [
    { "card_no": "1-0-040", "count": 3 },
    { "card_no": "1-0-004", "count": 3 }
  ]
}
```

デフォルトではテスト用の小さいデッキを許可する。

正式デッキルールを検証したい場合は `--strict-deck-rule` を指定する。

## 2. sample player 同士の match

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:first --p2 sample:pass --seed 1 --max-turns 20 --replay test_output/replay.json --verify-replay
```

`sample:first` は、提示された legal action のうち `pass` / `no_block` / `pass_window` 以外を優先して選ぶ。

`sample:pass` は、可能なら `pass` / `no_block` / `pass_window` を選ぶ。

## 3. 外部子プロセス player

`cmd:<command line>` を指定すると、外部プロセスを JSON Lines player として起動する。

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 "cmd:python -m tojs_reborn.io.sample_player --mode first" --p2 "cmd:python -m tojs_reborn.io.sample_player --mode pass" --max-turns 20 --replay test_output/replay.json --verify-replay
```

子プロセスが timeout、invalid JSON、illegal action を返した場合は fallback action を使って match を継続し、`player_response_fallback` event を記録する。

## 4. replay 検証

match CLI で保存した replay は、下記で検証できる。

```powershell
python -m tojs_reborn.io.replay_cli --cards carddata/generated/cards.normalized.json --replay test_output/replay.json
```

event log が一致すれば終了コード 0 を返す。

## 5. 現時点の未実装

- mulligan。
- `state_update` / `private_view.hand` の本格送信。
- first turn attack restriction の engine rule。
- JOKER / キャラクター固有能力。
- 全カード能力。
