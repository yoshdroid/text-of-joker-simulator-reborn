# first implementation spec ver.8

## GUI 微修正

P1/P1とも Handと Triggerとの順番を入れ替え、Triggerを上側、Handを下側に配置して。

Handのカードに LVに加えて、ユニットドライブに必要なCPを表示して。

TriggerZoneにセットされたカードにも LVと、発動に必要CPを表示して。インターセプトカードやトリガーカードの中には LV参照し処理が変わるものが予定されている。

Battlefieldのカードの "TAP" テキスト表示は削除して。

各カード画像サイズの比率はそのまま、倍率指定で大小を調整できる引数を追加して。現状をデフォルトの 1とし、x1.5や x2が渡せるとよい。


## g_b_controlbeat vs r_g_beatdown GUI replay feedback

seed 7のリプレイで発生した要修正動作

### トリガーゾーンに 2枚おかれた CIPトリガーカードが片方発動していない
0110 unit_entered に反応し、
0111 trigger_window_opened が起動する。
0112 trigger_activated で新品の鎧が起動するところまで正しい。
新品の鎧の効果解決後、隣に置いてあったサプライズボックスが起動していない。
新品の鎧発動によってサプライズボックスが左に一つずれたことで起動確認の判定が漏れている可能性がある。

### 進化ユニットの行動権は 進化前ユニットの行動権を引き継ぐ
0146 魔槍のリリムを evolveさせたところで、
進化元となった ランサーは attack済みで行動権を失い TAPしているが、
リリムは TAPせず表示されている。期待動作は 登場時点で TAPしていること。
GUI側のみの問題かもしれず切り分けが必要。

### アタック時発動効果が発動していない、《魔槍のリリム》の効果が未実装かもしれない
0190 unit_attacked で魔槍のリリムの SELF_ATKが発動し、相手のトリガーゾーンのカード破壊が発生するのが期待動作。
相手のトリガーゾーンにカードがなければ発動しないのは正しいが、この時点で 相手のトリガーゾーンにはムーンセイヴァーが置かれているので、破壊される。

なお 0150 unit_entered で SELF_CIPが発動していないのは 対象相手ユニットがいないので正しいが、
魔槍のリリムの効果が SELF_CIP デーモンスピア、SELF_ATK トリガーロスト のどちらも未実装な可能性がある。

### 《冥王ハデス》の効果が未実装かもしれない
0230 unit_entered で冥王ハデスの SELF_CIP LV2以上相手ユニット全破壊が発生するのが期待動作。
相手の場にユニットがいないか、すべて LV1であれば発動しないのは正しいが、相手の魔槍のリリムは LV2なので、破壊される。

### あなたのユニットが攻撃した時、の プレイヤーへの ムーンセイヴァー 発動可否確認が出ていないかもしれない
0234 unit_attacked契機の 発動確認が起きているか、要確認。
インターセプトカードのため、プレイヤーが使用しない選択をした可能性もある。もしそうならば、イベントログにも出力できないか検討すること。

### あなたのユニットが戦闘した時、の 両プレイヤーへの ダーク・アーマー/悪の覚醒/不可侵防壁 発動可否確認がでていないかもしれない
0236 battle_started景気の 発動確認が起きているか、要確認。
アタック側、ブロック側の順に判定を進めているか検証して。
インターセプトカードのため、プレイヤーが使用しない選択をした可能性もある。もしそうならば、イベントログにも出力できないか検討すること。

## RNGを最初のデッキシャッフルにも共通で適用したい 方針案
ゲームエンジンが match_startedよりも前のイベントを取り扱うことで、別のRNGを持たせなくても再現可能な共通乱数にできるのでは、と考える。
たとえば下記のような実装とすることが可能か検討して。問題がみつかったら報告して。

1. engine started
    「A.C.T.I.S.起動」
2. first player entered
    名前や戦績、JOKER種別などプレイヤー情報（未実装）を engineに渡す
3. second player entered
    名前や戦績、JOKER種別などプレイヤー情報（未実装）を engineに渡す
4. first player deck registered
    使用するデッキリストを engineに提出する
    レギュレーションに準拠した内容構成であることをここでチェックする
5. second player deck registered
    使用するデッキリストを engineに提出する
    レギュレーションに準拠した内容構成であることをここでチェックする
6. pre-judge
    登録情報に不備があれば、この時点で不戦勝、不戦敗、無効試合として終了する
7. battle field deployed
    両プレイヤーのデッキをセットし、ここでシャッフルし、初期手札を配布する。
    その他情報初期化をおこなう
8. match started
9. first player mulligan
10. second player mulligan


# second implementation spec ver.8

ここまでの確認修正実装が完了したら、v8として続けるべき実装アイテムを検討し、この下に追記して。

## RNG 方針メモ

v8 では、ゲーム開始時の初期デッキシャッフルを `GameState.rng` に統一する。
これにより、初期シャッフル、マリガン、デッキリフレッシュ、ランダム対象選択が同じ seed 由来のエンジン RNG を順に消費する。

一方で、`match_started` より前に `engine_started` / `deck_registered` / `battle_field_deployed` などのイベントを正式に持たせる場合、replay の `initial_state` と intents の境界を再設計する必要がある。
現行 replay は match setup 後の状態を初期スナップショットとして保存しているため、pre-match event を単純に event log へ追加すると replay 再現時のイベント列がずれる。
このため、pre-match event 化は v8 の追加討議候補として残し、まずは RNG 共通化のみを実装対象とする。

## v8 追加候補

1. pre-match event model
   - `engine_started` / `player_entered` / `deck_registered` / `battle_field_deployed` を event log と replay intents のどちらに置くかを決める。
   - `initial_state` を「engine 起動直後」に寄せるか、「battle_field_deployed 後」のままにするかを整理する。
   - deck registration 時点で strict deck rule、プレイヤー情報、JOKER 種別を検証できるようにする。

2. 通常 match replay 由来のシナリオ化
   - `g_b_controlbeat_vs_r_g_beatdown` で発生した重要イベントを、固定 GUI シナリオへ切り出す。
   - まずは `サプライズボックス`、`魔槍のリリム`、`冥王ハデス`、`ムーンセイヴァー`、`悪の覚醒/ダーク・アーマー/不可侵防壁` を個別シナリオ化する。
   - 通常 match の seed が変わっても、カード単位の確認導線が失われないようにする。

3. intercept / trigger window の GUI 視認性
   - pass した intercept window もイベントログ上で「発動しない」を読みやすく表示する。
   - window open 時に、候補カードと発動不能理由（CP不足、同色ユニット不在、対象なし）をデバッグ表示できるモードを検討する。

4. v8 以降のカード効果追加
   - controlbeat / beatdown デッキ内で未実装のカード効果を洗い出し、match replay で遭遇しやすい順に実装する。
   - 実装単位は「カード1枚 + engine test + scenario replay + GUI確認表更新」を基本とする。
