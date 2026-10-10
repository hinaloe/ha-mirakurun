# Mirakurun Home Assistant インテグレーション 設計

- 日付: 2026-10-11
- 状態: レビュー待ち

## 1. 目的と前提

Mirakurun（日本のテレビチューナーサーバー）を Home Assistant から扱えるようにするカスタムインテグレーションを作る。
HACS で配布する。

### 要求（合意済み）

- チューナーの使用状況と番組情報を HA のエンティティとして扱えること。
- 将来的にライブ TS 再生を扱えること。
- 自宅の環境に限らず、任意の Mirakurun に設定画面から接続できること。
- EPGStation（HACS 版インテグレーション）と併存すること。機能の重複は許容し、互いに依存しない。
- 品質は HA 本体の Integration Quality Scale にできるだけ近づける。
- API クライアントはインテグレーションに同梱し、PyPI パッケージには切り出さない。

### 段階

| 段階 | 内容 | この仕様での扱い |
|---|---|---|
| 1 | 土台：接続設定、チューナー状況、サーバー状態、番組情報、更新通知 | 詳細を定める |
| 2 | メディアソース：チャンネルを「メディアを閲覧」に並べ、DLNA 機器などに送る | 方針のみ。着手時に別の仕様を書く |
| 3 | HA 画面内での再生：ts-live などを使うカスタムカード | 方針のみ。着手時に別の仕様を書く |

### 非目標

- 録画・予約の操作（EPGStation の担当）。
- Mirakurun の設定変更（チャンネルスキャン、チューナー設定、再起動、プロセス停止）。
- 認証付きのリバースプロキシ越しの接続。Mirakurun 本体は認証を持たないため、段階 1 では URL だけで接続する。
- HA 本体への取り込み。

## 2. 調査結果（実機 Mirakurun 4.0.0-beta.18）

設計の根拠とした事実を記録する。

- `GET /api/version` は `{"current", "latest"}` を返す。更新エンティティに使える。
- `GET /api/status` はストリーム数（`streamCount`）、エラー数（`errorCount`、うち `tunerDeviceRespawn` が 1747）、EPG 取得中のネットワーク（`epg.gatheringNetworks`）、保持番組数（`epg.storedEvents` = 26,849）を返す。
- `GET /api/tuners` はチューナーごとに `index`、`name`、`types`、`users[]`（`id`、`priority`、`streamSetting.channel`）、`isAvailable`、`isFree`、`isUsing`、`isFault` を返す。実機は PT3 の 4 本。
- `GET /api/services` は 139 件（GR 35 / BS 51 / CS 53）。各サービスは `id`、`serviceId`、`networkId`、`name`、`type`、`remoteControlKeyId`（地上波の主要局のみ）、`channel`、`hasLogoData` を持つ。
- `GET /api/programs?networkId=&serviceId=` は 1 サービスあたり約 500 件を返す。全件取得は重いため使わない。
- `GET /api/events/stream` は番組・サービス・チューナーの変化を JSON 配列のストリームで流す。`resource` と `type` で絞り込める。番組の更新が絶えず流れる。
- `GET /api/services/{id}/stream` は `video/MP2T` を返す。`X-Mirakurun-Priority` ヘッダと `decode` クエリを受け付け、空きチューナーがなければ 503 を返す。
- `GET /api/docs` で OpenAPI（Swagger 2.0）が取れる。
- 認証はない。

Mirakurun 3.x は実機で確認していない。
段階 1 で使うエンドポイントは 3.x にも存在するはずだが、互換性は「4.x で検証、3.x は未検証」と README に明記する。

## 3. 全体構成

```
custom_components/mirakurun/
├── __init__.py          # セットアップ、runtime_data、不要デバイスの削除
├── manifest.json
├── api.py               # 同梱 API クライアント（HA に依存しない）
├── models.py            # API レスポンスの dataclass
├── coordinator.py       # StatusCoordinator / ProgramCoordinator / VersionCoordinator
├── config_flow.py       # 設定・再設定・オプション
├── entity.py            # 共通基底クラスと DeviceInfo
├── sensor.py
├── binary_sensor.py
├── calendar.py
├── update.py
├── diagnostics.py
├── const.py
├── strings.json
├── icons.json
├── quality_scale.yaml
└── translations/{en,ja}.json
tests/
hacs.json
README.md
```

### 3.1 API クライアント（`api.py`、`models.py`）

- HA に依存しない純粋な async クライアントとする。将来切り出す場合に備え、HA の import を持たせない。
- `aiohttp.ClientSession` を外から受け取る。HA からは `async_get_clientsession(hass)` を渡す（Quality Scale の inject-websession）。
- メソッド: `get_version()`、`get_status()`、`get_tuners()`、`get_services()`、`get_programs(network_id, service_id)`。
- 返り値は `models.py` の frozen dataclass。未知のフィールドは無視し、欠けた任意フィールドは `None` にする。
- 例外は `MirakurunConnectionError`（接続失敗・タイムアウト）と `MirakurunResponseError`（想定外のステータスや JSON）の 2 種に揃える。共通の基底は `MirakurunError`。
- タイムアウトは 1 リクエスト 10 秒。

### 3.2 コーディネーター（`coordinator.py`）

| 名前 | 取得するもの | 間隔 | 理由 |
|---|---|---|---|
| `StatusCoordinator` | `/status` と `/tuners` | 30 秒 | チューナーの使用状況は変化が速い |
| `ProgramCoordinator` | 選択されたサービスごとの `/programs` | 30 分 | EPG の取得は毎時 20 分と 50 分に走る |
| `VersionCoordinator` | `/version` | 12 時間 | 最新版の確認は頻繁に要らない |

- サービス一覧（`/services`）はセットアップ時と `ProgramCoordinator` の更新時に取得する。
- 「現在の番組」は `ProgramCoordinator` が保持する番組データから算出する。API は呼ばない。番組の切り替わりに合わせて状態を更新するため、各エンティティは次の切り替わり時刻に `async_track_point_in_utc_time` で再描画を予約する。
- `/api/events/stream` によるプッシュ更新は段階 1 では使わない。チューナー状況の即時性が足りないと分かった時点で、`resource=tuner` に絞って追加する。

### 3.3 設定フロー（`config_flow.py`）

- **ユーザー設定**: URL を 1 つ入力する（既定値の例示は `http://<host>:40772`）。末尾の `/` と `/api` は正規化して取り除く。`get_version()` で接続を確認する。
- **一意性**: Mirakurun は機器固有の ID を返さない。正規化した URL で既存エントリとの重複を弾く（`_async_abort_entries_match`）。
- **再設定**: URL の変更を受け付ける（reconfigure フロー）。
- **オプション**: 番組情報を出すサービスを複数選択する。既定値は「地上波のリモコン番号（`remoteControlKeyId`）ごとに、`type` が `1`（テレビ）のサービスのうち `serviceId` が最小のもの」とする。実機では 9 件（NHK 総合から TOKYO MX まで）になる。地上波の 35 件はすべて `remoteControlKeyId` を持ち、サブチャンネルやワンセグ（`type` が `192`）も含むため、リモコン番号の有無だけでは絞れない。全 139 件を既定で出すと、デバイスとエンティティが多すぎる。
- 発見（zeroconf など）は持たない。Mirakurun は告知を行わない。

### 3.4 デバイスとエンティティ

デバイスは 3 種類とする。

**サーバー（1 台）**

| エンティティ | 種類 | 内容 | 既定 |
|---|---|---|---|
| 使用中チューナー数 | sensor | `isUsing` の数 | 有効 |
| 空きチューナー数 | sensor | `isFree` の数 | 有効 |
| ストリーム数 | sensor | `streamCount.tunerDevice` | 有効（診断） |
| 保持番組数 | sensor | `epg.storedEvents` | 無効（診断） |
| チューナー再起動回数 | sensor | `errorCount.tunerDeviceRespawn`（累積） | 有効（診断） |
| その他のエラー数 | sensor | `uncaughtException` など各項目 | 無効（診断） |
| 番組表取得中 | binary_sensor | `epg.gatheringNetworks` が空でない | 有効（診断） |
| Mirakurun | update | `current` と `latest`。インストール機能は持たず、リリースノートの URL を示す | 有効 |

**チューナー（`/tuners` の要素ごと、`via_device` はサーバー）**

| エンティティ | 種類 | 内容 |
|---|---|---|
| 状態 | sensor（enum） | `fault` / `in_use` / `free` / `unavailable` |
| 視聴中のチャンネル | sensor | `users` のうち最も優先度の高い利用者の `streamSetting.channel.name`。未使用なら `None` |
| 利用者 | sensor | 最も優先度の高い利用者の `id`。属性に全利用者の `id` と `priority` |
| 故障 | binary_sensor（problem） | `isFault` |

チューナーの識別子は `index` を使う。`/tuners` から消えたチューナーのデバイスは削除する（stale-devices）。

**放送サービス（オプションで選んだものごと、`via_device` はサーバー）**

| エンティティ | 種類 | 内容 |
|---|---|---|
| 番組表 | calendar | 番組をイベントとして返す。カレンダートリガーで「番組開始時」のオートメーションが書ける |
| 現在の番組 | sensor | 番組名。属性に開始・終了時刻、説明、ジャンル |
| 次の番組 | sensor | 番組名。属性に開始時刻 |

サービスの識別子は Mirakurun の `id`（`networkId` と `serviceId` の合成値）を使う。
オプションから外したサービスのデバイスは削除する。

**共通**

- `unique_id` は `{config_entry_id}_{種別}_{識別子}_{キー}` とする。URL を含めない（再設定で URL が変わっても維持するため）。
- エンティティ名とアイコンは `strings.json` と `icons.json` で翻訳する（`has_entity_name = True`）。英語と日本語を用意する。

### 3.5 番組データの扱い

- `startAt` と `duration` はミリ秒。UTC の `datetime` に変換する。
- `duration` が `1` 以下の番組は終了時刻が未定とみなす。この場合、終了時刻は次の番組の開始時刻とする。次の番組もなければ開始から 1 時間とする。Mirakurun は未定の継続時間を `1` で表すと理解しているが、実機の NHK 総合 497 件には該当がなく、未検証である。実装時に Mirakurun のソースで確かめる。
- ジャンルは ARIB の大分類（`lv1`）を日本語・英語の名前に変換する。中分類は属性に数値のまま残す。
- カレンダーの `async_get_events` は保持データの範囲内で返す。範囲外を要求されても API は呼ばない。

### 3.6 エラー処理

- 初回の取得に失敗したら `ConfigEntryNotReady` を送出し、HA の再試行に任せる。
- 2 回目以降の失敗は `UpdateFailed` にする。該当コーディネーターのエンティティは利用不可になる。
- 利用不可になったときと復帰したときに 1 回ずつログを出す（log-when-unavailable）。
- `ProgramCoordinator` は一部のサービスだけ失敗した場合、失敗したサービスの前回データを保持して他を更新する。全サービスが失敗したら `UpdateFailed` にする。
- 例外メッセージは翻訳キーで出す（exception-translations）。

### 3.7 診断（`diagnostics.py`）

設定内容と、各コーディネーターの最新データを返す。
URL のホスト部分はマスクする。
番組データは件数だけを返す（量が多いため）。

## 4. EPGStation との併存

- ドメインは `mirakurun` で、EPGStation のエンティティとは独立している。
- 段階 1 はチューナーを確保しない（ストリームを開かない）。EPGStation の録画を妨げない。
- 段階 2 以降でストリームを開く場合は `X-Mirakurun-Priority` を低く設定する。録画が始まれば Mirakurun が視聴側を切る。

## 5. 段階 2・3 の方針

### 段階 2: メディアソース

- `media_source` プラットフォームを実装し、GR / BS / CS の階層でサービスを並べる。サムネイルにはロゴを使う。
- 再生 URL は `/api/services/{id}/stream` とする。MIME タイプは `video/mp2t`。
- 再生機器から Mirakurun に直接届かない環境のために、HA を経由する中継も検討する。中継は認証付きの署名 URL にする。
- Chromecast は HTTP で直接送る MPEG-2 の TS を再生できない見込みが高い。対応機器の範囲は実機で確かめてから README に書く。

### 段階 3: HA 画面内での再生

- ts-live や TSPlay のようなブラウザ内デコーダを使うカスタムカードを、別のフロントエンドパッケージとして作る。
- ストリームは段階 2 の中継経由で受け取る。外出先からも HA 経由で見られる。

## 6. 品質の目標

Integration Quality Scale のうち、次を満たす。
各ルールの達成状況は `quality_scale.yaml` で管理する。

- **Bronze**: すべて。
- **Silver**: すべて。
- **Gold**: discovery 系（Mirakurun が告知しないため対象外）を除くすべて。diagnostics、reconfigure-flow、entity-translations、entity-category、entity-disabled-by-default、icon-translations、exception-translations、stale-devices を含む。
- **Platinum**: async-dependency、inject-websession、strict-typing（mypy strict）。

## 7. テスト

- `pytest-homeassistant-custom-component` を使う。
- API クライアントは、実機から取った JSON をフィクスチャにしてテストする。フィクスチャは件数を絞り、チューナーのコマンド行やプロセス情報など環境固有の値は置き換える。
- 設定フローはすべての分岐を網羅する（Quality Scale の config-flow-test-coverage）。
- エンティティの状態は syrupy のスナップショットで検証する。
- 番組の切り替わり、終了時刻未定の番組、一部サービスの取得失敗を個別にテストする。
- CI（GitHub Actions）で hassfest、HACS の検証、ruff、mypy、pytest を回す。

## 8. 未決事項

なし。段階 2・3 の詳細は、それぞれ着手時に別の仕様で決める。
