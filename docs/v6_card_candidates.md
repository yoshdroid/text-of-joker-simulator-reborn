# v6 追加カード候補

v5 では、カードを大量追加する前に player protocol と replay / viewer の足場を固めた。
v6 では、現在の engine が持つ能力処理を横断的に確認しつつ、不足している仕様を早めに発見できるカードを優先する。

## 1. 候補選定の方針

- 既存の supported effect を使い、すぐ仕様テスト化できるカードを先に使う。
- 新しい engine effect が必要なカードは、Excel 効果文と `ability_mapping.json` の対応を確認してから 1-3 枚ずつ追加する。
- 「対象選択」「window」「optional」「duration」「ランダム」「公開情報」のどれかを強く検証できるカードを優先する。
- 追加カードは decklist / replay viewer で人間が挙動確認しやすいものにする。

## 2. まずテスト強化に使う既存 supported カード

次のカードはすでに `ability_mapping.json` で supported になっているため、v6 冒頭では新規カード追加より先に仕様テストとサンプル decklist を厚くする。

| card_no | card_name | 検証したいこと |
| --- | --- | --- |
| `1-0-001` | ブラッドハウンド | OC 時の対象選択、効果ダメージ、choice target 表示 |
| `1-0-004` | ランサー | 攻撃時能力、対象選択、BP / damage 表示 |
| `1-0-005` | ヘルハウンド | 相手 trigger zone の非公開情報、ランダム破壊、公開後情報 |
| `1-0-027` | ミイラくん | PIG 順序、相手手札ランダム discard、replay 再現性 |
| `1-0-029` | カラスマドウ | PIG 順序、category draw、deck refresh 連携 |
| `1-0-043` | グラインドビートル | CP 変化、同一カード複数 ability、条件付き draw |
| `1-0-045` | リーフィア | block 時 BP modifier、turn duration 解除 |
| `1-0-061` | 新品の鎧 | trigger window、trigger 強制発動、category draw |
| `1-0-097` | 追い風 | intercept window、optional pass/use、CP 変化 |
| `1-0-099` | ハウリング | intercept optional、draw 2、choice / replay 表示 |

## 3. v6 で追加したい新規カード枠

### 3.1 cost 付き unit ability

目的:
「そうした場合」系の cost 支払い能力を、battlefield unit で検証する。
不知火伍式とフォクスコマンドーは、手札枚数が足りているとき強制的に発動し、cost 対象だけを player が選ぶ。

必要な仕様:

- cost を支払える場合、「使う / 使わない」は選ばせず、cost 対象のみ `choice_request` で選ばせる。
- cost を支払えない場合、`ability_cost_failed` を記録し、後続効果は解決しない。

### 3.2 複数 target / target 条件

目的:
selector が 1 つだけの前提を崩し、子プログラムに十分な対象情報を渡せるか確認する。

必要な仕様:

- 複数対象を選ぶ能力で、同じ対象を複数回選べるか。
    たとえば 2体の敵ユニットを選択するケースで 敵の場に 1体のみ存在した時、選択は 1回のみになる。
    v6 の最初の複数対象カードは 1-0-003 バク・ダルマン とし、`selector.count: "all"` で相手全ユニットを対象にする。
    複数対象 + 対象条件の確認カードは 1-0-023 ラグエル とし、相手の行動済ユニット全てを対象にする。
- 対象条件がカード属性、BP、種族、行動権、damage などに依存する場合の schema 表現。
    v6 の最初の対象条件カードは 1-0-018 ヤシオノトクリ とし、`selector.exhausted: true` で行動済ユニットだけを候補にする。
    レベル条件の確認カードは 1-0-030 ドン・ペロッツァーノ とし、`selector.min_level: 2` で相手のレベル2以上ユニットだけを候補にする。
- 対象不在時に ability 自体を不発にするか、発動して効果だけ不発にするか。
    視認上わかりやすさを優先し、発動して効果が不発、となるようにする。

### 3.3 discard pile / deck search / reveal

目的:
公開領域と非公開領域の境界をさらに検証する。

必要な仕様:

- deck search 時、検索対象候補を player にどこまで見せるか。
    全く見せない。対象を必要枚数サーチドローし、プレイヤーはその結果のみ知る。
    確認用カードは 1-0-020 カイム とし、CIP でデッキ内のトリガーカード1枚だけを手札に加える。
    `draw_card_by_category` はデッキ順を内部で走査するが、子プログラムにはデッキ内容一覧を渡さず、移動結果のみ replay / private hand に現れる。
- hand reveal は相手に一時公開するのか、以後公開済みカードとして扱うのか。
    一時公開とする。まだこの効果を必要とするカードは提示していないかもしれない。
- discard pile からの移動は card instance を維持するか、新しい instance として扱うか。
    維持する。
    最初の確認用カードは 1-0-033 ヴァイパー とし、CIP で自分の捨札のユニットカード1枚をランダムに手札へ戻す。
    `move_random_discard_to_hand` は公開領域である discard pile から既存 card instance id を維持して hand へ移動する。

### 3.4 duration が異なる BP 修正

目的:
現在の `duration: "turn"` 以外の BP modifier を追加し、解除タイミングを確認する。
確認用カードは 1-0-042 ケロール・キッド とし、相手ユニット1体の基本BPを永続的に -3000 する。
内部表現では基礎BPが千単位のため、mapping の `amount` は `-3` とする。

必要な仕様:

- 永続 BP 修正、戦闘中のみ、次の自分ターンまで、などの duration 候補。
    `modify_base_bp` は `duration: "permanent"` として扱い、ターン終了では解除しない。
- level / OC / 破壊 / 手札戻りで modifier を引き継ぐか。
    OC、またはlevel 変更時、ダメージはクリアされる。基礎 BP変動はターンを超えて残る。
    破壊時、手札戻り時は ユニットがバトルフィールドに残らず、modifierをクリアする。
    

## 4. 推奨する v6 実装順

1. 既存 supported カードの仕様テストを増やす。
2. v6 用 decklist を作り、match CLI と replay viewer で確認しやすくする。
3. cost 付き unit ability の候補カードを Excel から選び、mapping と engine テストを追加する。
4. 複数 target または target 条件を持つカードを 1 枚追加する。
5. discard pile / deck search / reveal のどれか 1 系統を選び、公開情報 schema を先に決める。

## 5. 追加で確認したい仕様

- cost 付き unit ability の候補カードをどれにするか。
    1-0-010 不知火伍式 
    1-0-041 フォクスコマンドー
    どちらも「使う / 使わない」は選ばせず、手札枚数が足りていれば強制発動する。
    不知火伍式は手札1枚、フォクスコマンドーは手札2枚の cost choice 検証カードとする。
- deck search / reveal の private / public view の境界。
    デッキ内のカード状態はエンジンのみ把握し、プレイヤーが中を見れるのは一部効果のみ。
    まだこの効果を必要とするカードは提示していない。
- discard pile から移動したカードの instance id の扱い。
- BP modifier の duration 種類と解除タイミング。
