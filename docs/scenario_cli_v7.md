# scenario CLI v7

個別機能・個別カード効果を GUI で目視確認するため、固定テストシナリオから replay を生成する CLI。

## 生成

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario all --verify
```

既定では `test_output/scenarios/` に replay を出力する。

## テストシナリオ一覧

| scenario | 確認対象 | 期待する目視ポイント | v7 |
| --- | --- | --- | --- |
| `bishamon_evolve_destroy_all` | 毘沙門 | 左からスカルウォーカー、ライマル、ミイラくんで開始し、真ん中の `1-0-021` ライマルを元に `1-0-026` 毘沙門を進化ドライブする。ミイラくんで P2 手札1枚をランダム破壊し、スカルウォーカーで進化元ライマルを手札へ戻し、カラスマドウで P2 が intercept をサーチドローする。最後に毘沙門でアタックし、P2 LIFE が減る。 | ✓ |
| `bloodhound_level3_damage` | ブラッドハウンド | `1-0-001` ブラッドハウンドを手札オーバーライドで LV3 にしてドライブし、OC の対象選択、4000ダメージ、相手ユニット破壊を確認する。 | ✓ |
| `dartagnan_cip_attack_draw` | ダルタニャン | `1-0-047` ダルタニャンをドライブしてCIPでCPが増え、P1/P2が一度ターンエンドした後のP1ターンにアタック時効果でデッキトップを1枚引き、P2 LIFEが減る。 | ✓ |
| `display_stand_trigger_draw` | ディスプレイスタンド | `1-0-062` ディスプレイスタンドが owner unit enter 後に強制発動し、デッキトップを1枚引く。 | ✓ |
| `goliath_level3_life_damage` | ゴライアス | `1-0-007` ゴライアスを手札オーバーライドでLV3にしてドライブし、OCで相手LIFEが1減る。 | ✓ |
| `happaloid_cip_draw` | ハッパロイド | `1-0-040` ハッパロイドをドライブし、CIP でデッキトップのカードが手札に移る。 | ✓ |
| `hand_limit_draw` | 手札上限 | 自分の手札3枚、相手の手札2枚から開始し、ターン冒頭ドローで 6->7 は増え、7->7 は `draw_skipped` になって手札上限7を超えない。 | ✓ |
| `howling_intercept_draw_two` | ハウリング | `1-0-099` ハウリングを intercept window で任意発動し、デッキトップから2枚ドローして捨札へ移動する。 | ✓ |
| `jumpoo_bounce_hand_limit` | ジャンプー | `1-0-019` ジャンプーを2回ドライブし、1体目の相手ユニットはLV1に戻って手札へ、2体目は相手手札上限によりLV1に戻って捨札へ移動する。 | ✓ |
| `kaim_cip_trigger_search` | カイム | `1-0-020` カイムをドライブし、デッキ内の trigger だけを探して手札に加え、unit / intercept がデッキに残る。 | ✓ |
| `leafia_block_bp_modifier` | リーフィア | P1 の `1-0-001` ブラッドハウンド LV1/LV2/LV3 と `1-0-032` 中忍月影 LV3 が4回アタックし、`1-0-045` リーフィアがすべてブロックする。1/2回目は戦闘勝利で LV2/LV3 へ上がりダメージ回復、3/4回目は LV3 から上がらずダメージが蓄積し、ターン終了でブロックBP修正と累積ダメージが解消され LV3 基礎BPになる。 | ✓ |
| `new_armor_trigger` | 新品の鎧 | `1-0-061` 新品の鎧が unit enter 後に強制発動し、deck から intercept を探して手札に加える。 | ✓ |
| `raguel_exhausted_damage` | ラグエル | `1-0-023` ラグエルをドライブし、相手の疲弊ユニット2体だけにダメージが入り、待機ユニットにはダメージが入らない。 |  |
| `rairyu_evolve_damage` | 雷龍 | `1-0-024` 雷龍を黄ユニットに進化ドライブし、進化元が捨札へ移動し、疲弊した相手ユニットへ7000ダメージを与えて破壊する。 | ✓ |
| `tailwind_intercept_cp` | 追い風 | `1-0-097` 追い風を intercept window で任意発動し、CPが4増えて捨札へ移動する。 |  |
| `lina_discard_choice` | 見習い魔導士リーナ | デッキ5枚の先頭を `1-0-033` ヴァイパーにして開始し、CP7で1枚ドローする。`1-0-031` 見習い魔導士リーナを手札オーバーライドで LV3 にした後、ヴァイパーで捨札のリーナを回収し、LV3リーナのOCでもリーナを回収する。最後に手札のリーナ2枚をオーバーライドしてLV2にする。 | ✓ |
| `viper_discard_unit_recover` | バイパー | `1-0-033` バイパーをドライブし、捨札の unit だけが候補になって同じカードインスタンスが手札へ戻る。 | ✓ |

## GUI で開く

単体シナリオは `--open-gui` で replay 生成後にそのまま開ける。

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --images carddata/images --scenario new_armor_trigger --verify --open-gui
```

画面サイズに依存しにくい状態で確認を始めたい場合は `--fullscreen` を追加する。

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --images carddata/images --scenario lina_discard_choice --verify --open-gui --fullscreen
```

既に生成した replay を開く場合:

```powershell
python -m tojs_reborn.io.replay_gui --cards carddata/generated/cards.normalized.json --images carddata/images --replay test_output/scenarios/hand_limit_draw.json
```

## シナリオの初期デッキ規約

- テストシナリオでも、初期配置される手札・場・捨札・トリガーゾーン・デッキ上のカードは、すべて `initial_deck_card_nos` に含まれていたカードとして扱う。
- `initial_deck_card_nos` 上の同名カードは3枚までとする。
- 純粋なドローでデッキが空の場合は、`initial_deck_card_nos` をシャッフルし、新しいカードインスタンスとしてデッキを再生成してからドローする。このとき既存の手札・場・捨札は戻さない。
- カテゴリサーチはデッキリフレッシュのきっかけにならない。デッキが空ならサーチは不発になり、`cards_drawn.count` は0になる。
