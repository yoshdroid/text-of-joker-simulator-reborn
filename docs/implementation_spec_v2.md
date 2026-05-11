# Text of Joker Simulator Reborn

実装仕様書 v2.0 draft

## v2 の位置づけ

`implementation_spec_v1.md` では、イベント駆動エンジンの最小実装を完了した。

v2 では、最小エンジンを「実カードを増やしながら、子プログラム同士の 1vs1 対戦を安定して回せるシミュレータ」へ育てる。

v2 の主目的は次の3つである。

- 実カード追加時に、Excel の効果文章と `ability_mapping.json` の対応を追跡できるようにする。
- trigger / intercept / choice / replay を、match runner 経由の実対戦で破綻しにくい構成にする。
- 追加カードごとに仕様テストを作り、自然言語効果の解釈ずれを早く検出する。

## v1 完了時点の前提

v1 で最小実装済み:

- Excel cardpool 読み込みと normalized JSON 生成。
- `ability_mapping.json` による手動能力対応。
- `EventStore` による逐次イベント記録。
- `GameState` / zone / card instance / unit state。
- ターン開始、ターン終了、CP、ドロー。
- unit drive。
- CIP: `SELF_CIP` / `YOUR_CIP` / `RIVAL_CIP`。
- PIG: `SELF_PIG`。
- 攻撃、ブロック、戦闘、直接攻撃。
- 効果: draw / search draw / random discard / effect damage / CP change / BP modify / recover action。
- seed 付き RNG と `random_resolved`。
- replay record の最小再実行。
- legal action 生成。
- JSON Lines protocol の土台。
- in-process `MatchRunner`。
- public state の最小隠蔽。
- trigger / intercept window runner。
- hand override と LV3 drive 時の `SELF_OC`。
- `python -m unittest -v` で 41 tests OK。

## v2 完了条件

v2 は、次を満たしたら完了とする。

- 実カードを追加しても、カードごとの仕様テストを自然に増やせる。
- `ability_mapping.json` の timing / condition / selector / effect_steps の書き方が、実装上の曖昧さなく説明されている。
- match runner で 1ターン以上の自動対戦シナリオを replay 付きで検証できる。
- child program 向け protocol の request / response / invalid fallback がテストされている。
- trigger / intercept の発動確認が match runner の action / choice と統合されている。
- 追加カードにより、少なくとも CIP / PIG / ATK / BLOCK / TURN_END / OC / trigger / intercept を横断的にテストしている。

## v2 実装方針

### 1. 実カード追加の単位

カード追加は、原則として次の順で行う。

1. Excel の対象カード行を確認する。
2. `ability_mapping.json` に能力を下書きする。
3. normalizer の report で mapping 状態を確認する。
4. engine の不足部品があれば、カード固有ではなく汎用 effect / selector / condition として実装する。
5. そのカード専用の仕様テストを追加する。
6. 既存回帰テストを実行する。

カード追加時のテスト名は、カード名と期待動作が読める形にする。

例:

- `test_happaloid_self_cip_draws_one_card`
- `test_mummy_self_pig_discards_random_opponent_hand`
- `test_trigger_draw_card_fires_after_unit_entered`

### 2. ability_mapping の仕様厳密化

v2 では `ability_mapping.json` を、Excel 自然言語効果とエンジン処理をつなぐ唯一の手動仕様として扱う。

各 ability は最低限次を持つ。

- `ability_key`
- `ability_name`
- `status`
- `timing`
- `optional`
- `effect_steps`
- 必要なら `condition`
- 必要なら `selector`
- Excel 効果文章との対応を示す `source_text` または `notes`

timing は、エンジンの発動確認と一致する固定キーワードにする。

現在使用中または想定中の timing:

- `SELF_CIP`
- `YOUR_CIP`
- `RIVAL_CIP`
- `SELF_PIG`
- `YOUR_PIG`
- `RIVAL_PIG`
- `SELF_ATK`
- `SELF_BLOCK`
- `SELF_TURN_END`
- `SELF_OC`
- `TRIGGER_ANY`
- `TRIGGER_<EVENT_TYPE>`
- `INTERCEPT_ANY`
- `INTERCEPT_<WINDOW>`

v2 では、実カード追加のたびに timing の追加が必要かを確認する。

### 3. replay とイベントログ

v2 では、replay を「不具合調査の基盤」として扱う。

方針:

- action / choice / random の結果は、すべてイベントログから追跡できるようにする。
- replay record は `initial_state`、`intents`、`events`、`final_state` を持つ。
- match runner 経由の対戦でも replay record を作れるようにする。
- replay 失敗時、event_no と差分の原因を追いやすい検証関数を追加する。

追加したいテスト:

- 同じ seed / 同じ intents で event log が一致する。
- 不正 response の fallback も replay で一致する。
- window での intercept 選択も replay で一致する。

### 4. choice / selector

v1 では selector の最小実装として、候補列挙と先頭合法候補 fallback を実装した。

v2 では、子プログラムが対象を選ぶ形へ近づける。

必要なもの:

- `choice_requested` の payload schema 固定。
- `choice_selected` の payload schema 固定。
- 対象候補の public / private 情報の整理。
- 不正 choice response の `invalid_response`。
- required choice と optional choice の違い。
- 対象不在時に ability を発動しない場合と、発動して効果だけ不発にする場合の区別。

未決:

- choice request は protocol message として player に送るか、match runner 内部の callback とするか。
- 複数 selector を持つ ability の選択順。

### 5. trigger / intercept window

v1 では、window runner と match runner 接続を最小実装した。

v2 では、実カードの timing に合わせて window を広げる。

現在:

- trigger は `TRIGGER_ANY` または `TRIGGER_<EVENT_TYPE>`。
- intercept は `INTERCEPT_ANY` または `INTERCEPT_<WINDOW>`。
- `unit_attacked` 後に `attack` intercept window を開く。
- trigger は強制発動。
- intercept はターンプレイヤー側から交互に発動 / pass を確認し、2連続 pass で閉じる。

v2 で確認したいこと:

- どのイベント後に intercept window を開くか。
- trigger 発動によって新しいイベントが増えたとき、その新イベントに対する trigger 確認をどこまで再帰的に行うか。
- trigger / intercept の効果解決後、同じ原因イベントに戻って残り候補を確認する順序。
- 複数回使用可能な intercept の公開情報と zone 上の保持方法。

### 6. match runner / child program protocol

v2 では、子プログラム同士の 1vs1 対戦に向けて protocol を固める。

想定 message:

- `hello`
- `deck_submit`
- `state_update`
- `request_action`
- `action_selected`
- `choice_request`
- `choice_selected`
- `game_over`
- `error`

必要な仕様:

- request_id の採番。
- timeout 時の扱い。
- JSON decode 失敗時の扱い。
- legal action 以外の response への fallback。
- private state と public state の差分。
- trigger / intercept / choice request の player 視点。

v2 の最小ゴール:

- in-process player で 1ターン以上の対戦を実行できる。
- JSON Lines の入出力形式で同じ action payload を送受信できる。
- 不正応答テストがある。

### 7. public state

v1 では opponent trigger zone の count / colors / items を返す最小形を実装した。

v2 では、カード種類追加に合わせて public state を整理する。

公開するもの:

- 自分の hand / deck / trigger zone / discard pile。
- 相手の hand count。
- 相手の deck count。
- 相手 trigger zone の count と左から順の color。
- 公開済みカードの card_no / name / category。
- battlefield の unit 情報。
- life / CP / turn player / round / turn。

未決:

- discard pile は常に完全公開でよいか。
- deck 枚数以外の情報を公開しないことでよいか。
- 一度公開された trigger / intercept の visible metadata をどこに保持するか。

### 8. deck refresh

v1 では、`initial_deck_card_nos` から deck を再生成し shuffle する最小実装を入れた。

v2 で決めたいこと:

- deck refresh 時に discard pile の card instance をどう扱うか。
- 新規 card instance を作る仕様で確定するか。
- refresh 後の deck order は `deck_shuffled` / `deck_refreshed` のどちらで表すか。
- deck refresh が発生したことを replay でどこまで検証するか。

現時点の方針:

- discard pile を空にする。
- ゲーム開始時に登録された decklist から deck を復活させる。
- shuffle する。
- `deck_refreshed` を記録する。

### 9. overclock / override

v1 では hand override と LV3 drive 時の `SELF_OC` を最小実装した。

v2 で整理すること:

- battlefield 上の unit が LV2 から LV3 になる効果。
- LV3 drive 時の攻撃制限解除。
- 先攻1ターン目の攻撃制限。
- unit 破壊時に level 情報や素材扱いをどう discard pile へ反映するか。
- `overclock_unit` 互換 API を残すか削除するか。

現時点の方針:

- hand 内 override は、重ねられる側と重ねる側を区別する。
- 重ねる側は level 1 に戻して discard pile 先頭へ移動する。
- hand 内で LV3 になっても OC ability は発動しない。
- LV3 card を drive し、CIP 関連処理が終わった後に `unit_overclocked` と `SELF_OC` を処理する。

## v2 推奨マイルストーン

### V2-A: ability_mapping schema の確定

目的:

実カードを増やす前に、timing / selector / condition / effect_steps の書き方を固定する。

作業:

- `docs/ability_mapping_schema.md` を v2 実装に合わせて更新する。
- timing keyword 一覧を normalizer と一致させる。
- supported / deferred / unsupported の運用を明確化する。
- `source_text` / `notes` の使い方を決める。

完了条件:

- 新しいカード能力を追加するとき、どの欄を書けばよいか迷わない。
- normalizer が未知 timing / effect を report できる。

実装状況:

- `TRIGGER_<EVENT_TYPE>` / `INTERCEPT_<WINDOW>` の prefix 形式を normalizer で許可する。
- `supported` ability に `source_text` / `notes` のどちらもない場合、warning を出す。
- `docs/ability_mapping_schema.md` に v2 の window timing と source reference 方針を追記する。

### V2-B: 実カード追加 第1群

目的:

v1 で合成カードとして確認した window / selector / effect を実カードで検証する。

候補:

- 何でも屋の陳列台
- 新品の鎧
- ランサー
- ブラッドハウンド
- キャットムル
- ギガマムート

完了条件:

- 各カードに仕様テストがある。
- `ability_mapping.json` の該当カードが `supported` になっている。
- normalized JSON に期待する ability が出力される。

実装状況:

- `何でも屋の陳列台` を `TRIGGER_UNIT_ENTERED` / `draw_cards` として supported 化する。
- `新品の鎧` を `TRIGGER_UNIT_ENTERED` / `draw_card_by_category: intercept` として supported 化する。
- trigger が発動後 discard pile へ移動することを仕様テストで確認する。
- search-draw 対象が deck にない場合でも trigger は発動済みになり、0枚 draw として記録することを確認する。
- `追い風` を `INTERCEPT_UNIT_ENTERED` / `change_cp +4` として supported 化する。
- `ハウリング` を `INTERCEPT_UNIT_ENTERED` / `draw_cards 2` として supported 化する。
- unit_entered intercept は、カード所有者の unit enter のときだけ候補になることを確認する。
- `ランサー` / `ブラッドハウンド` / `キャットムル` / `ギガマムート` は実カード名で仕様テストを補強する。
- `ブラッドハウンド` は LV3 drive 後の `SELF_OC` で対戦相手ユニットに4000ダメージを与えることを確認する。
- `ギガマムート` はターン終了時に行動権を回復することを確認する。

### V2-C: match runner replay

目的:

子プログラム対戦の実行結果を replay で検証できるようにする。

作業:

- `MatchRunner` から replay record を生成する。
- action / block / intercept / choice を intent として記録する。
- 不正 response fallback も replay で一致させる。

完了条件:

- 1ターン以上の match runner 実行を replay できる。
- event log と final state が一致する。

実装状況:

- `MatchRunner` は `match_turn_action` intent として turn action / block action / window action の response 列を記録する。
- `replay_match_record` は記録された response 列を使って match runner を再実行する。
- window choice と不正応答 fallback を含む replay テストを追加する。

### V2-D: protocol の対戦用整備

目的:

外部子プログラムとの JSON Lines 対戦を始められる形にする。

作業:

- request / response schema を文書化する。
- `player_runner.py` を追加する。
- timeout / invalid JSON / invalid action の fallback を実装する。
- public state と private state の差をテストする。

完了条件:

- サンプル子プログラム2つを起動し、1ターン以上進められる。
- protocol テストがある。

実装状況:

- `player_runner.py` に JSON Lines action player の最小実装を追加する。
- response timeout は既定 1.0 秒とする。
- timeout / invalid JSON / illegal action は合法手先頭へ fallback する。
- `action_selected` message helper と round-trip test を追加する。
- `sample_player.py` を追加し、`first` / `pass` の2モードで JSON Lines response を返す。
- サンプル子プログラム2つを subprocess として起動し、action を選べることをテストする。
- `choice_request` / `choice_selected` message helper を追加する。
- `JsonLinePlayer` は action と choice を同じ transport で送受信できる。
- `sample_player.py` は choice request に対して先頭合法候補を返す。

### V2-E: window の実カード統合

目的:

trigger / intercept の実カードを追加し、発動順と pass 処理を固める。

作業:

- trigger の実カードを1枚以上追加する。
- intercept の実カードを1枚以上追加する。
- `choice_request` と intercept activation を同じ player interface で扱う。
- window 由来イベントの replay をテストする。

完了条件:

- trigger / intercept を含む match runner シナリオが通る。
- 発動順が仕様テストで固定されている。

実装状況:

- trigger は `何でも屋の陳列台` と `新品の鎧` で確認済み。
- intercept は `追い風` と `ハウリング` で確認済み。
- `unit_entered` 後の intercept window を match runner から開く。
- `choice_request` と intercept activation は `JsonLinePlayer` の同じ JSON Lines transport で扱える。

## v2 で追加したいテスト観点

- normalized JSON に mapping した ability が期待通り出る。
- 実カードごとの ability timing が期待通り。
- selector 候補が public state と矛盾しない。
- choice response が不正な場合に fallback する。
- trigger がターンプレイヤー側から交互に発動する。
- intercept が2連続 pass で閉じる。
- intercept activation が discard pile へ移動する。
- deck refresh 後の draw が replay 可能。
- match runner の action が replay record から再実行できる。
- public state に非公開 card_no が漏れない。

## v2 で追加確認が必要な仕様

この節は、ユーザーが追記するための作業メモとする。

### 実カード追加順

トリガー　→ インターセプト　→ ユニットの順で実装する。

確認したいこと:

- v2 最初の追加カード群をどれにするか。
- trigger / intercept を先に増やすか、unit ability を先に増やすか。

### trigger / intercept window

任意実行トリガーカードは存在しない。

確認したいこと:

- `unit_attacked` 以外で intercept window を開くイベント。
- trigger が発動した結果のイベントに対する window 再確認の範囲。
- 任意 trigger が将来存在するか。

### child program protocol

timeoutは 1.0秒、不正応答は fallback続行する。

確認したいこと:

- 子プログラムは stdio JSON Lines でよいか。
- 1 response の timeout 秒数。
- 不正応答時、即敗北にするか、fallback で続行するか。

### deck / discard / refresh

search-drawしたときは deck内を shuffleする。
全ての deck内カードを引き切った後の drawでは refreshする。
refresh時、discard pileは空にする。

確認したいこと:

- deck refresh 後に新規 card instance を作る仕様で確定するか。
- discard pile の公開順。
- refresh 時の discard pile 内カードの扱い。

### overclock / first turn attack restriction

OC処理により行動権回復と攻撃可能になる。例外は先攻で 1ターン目であったときのみ。

確認したいこと:

- 先攻1ターン目判定に必要な match metadata。
- LV3 drive 後の行動権回復と攻撃可否の厳密条件。

## 現在の検証状況

2026-05-11 時点:

```text
python -m unittest -v
Ran 41 tests
OK
```
