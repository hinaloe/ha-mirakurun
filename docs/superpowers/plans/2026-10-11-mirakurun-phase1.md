# Mirakurun インテグレーション段階 1 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirakurun のチューナー状況・サーバー状態・番組情報・更新通知を Home Assistant のエンティティとして提供する HACS 向けカスタムインテグレーションを作る。

**Architecture:** HA に依存しない API クライアント（`api.py`、`models.py`）と純粋ロジック（`programs.py`、`broadcast.py`）を下層に置く。その上に 3 つの `DataUpdateCoordinator`（状態・番組・バージョン）を載せ、各プラットフォームのエンティティがそれを購読する。マルチチャンネル放送は物理チャンネル単位で「放送」にまとめ、判定結果をオプションに保存する。

**Tech Stack:** Python 3.14、Home Assistant 2026.10、aiohttp、voluptuous、pytest-homeassistant-custom-component 0.13.371、mise（ツールのバージョン管理とタスク）、uv（依存と仮想環境）、ruff、mypy（strict）。

**Spec:** `docs/superpowers/specs/2026-10-11-mirakurun-integration-design.md`

## Global Constraints

- ドメインは `mirakurun`。配布は HACS（`custom_components/mirakurun/`）。
- Python は 3.14 以上。Home Assistant は 2026.10.0 以上。
- 開発ツールは mise で固定する（`mise.toml` の `[tools]` に `python = "3.14"` と `uv`）。Python の依存は uv で管理し、コマンドは `uv run ...` で実行する。まとめた検証は `mise run lint` と `mise run test`。
- 外部の PyPI 依存を追加しない（`manifest.json` の `requirements` は空）。HTTP は HA の共有セッション（`async_get_clientsession`）を使う。
- `api.py`、`models.py`、`programs.py`、`broadcast.py` は `homeassistant` を import しない。
- API の 1 リクエストのタイムアウトは 10 秒。
- 取得間隔: 状態 既定 30 秒（10〜300 秒）、番組 既定 30 分（5〜180 分）、バージョン 12 時間固定。
- 放送の判定: `type` が `1` のサービスを物理チャンネルでまとめ、`serviceId` 最小をメインとし、メイン番組の `relatedItems`（`type: shared`）での共有率が 0.5 以上なら従属、未満なら独立。
- オプションの既定の放送は地上波（`GR`）のすべての放送。
- `unique_id` は `{entry_id}_{種別}_{識別子}_{キー}`。URL を含めない。
- 翻訳は `translations/en.json` と `translations/ja.json`。カスタムインテグレーションでは HA が `strings.json` を読まないため、仕様の `strings.json` はこの 2 ファイルで代える。
- 各ステップのコミットの前に `uv run ruff format . && uv run ruff check --fix .` を実行する。
- コミットメッセージの末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` を付ける。

## Review Focus

1. **Mirakurun が `/api/version` の `latest` を取れない（npm に届かない環境）**: 更新エンティティだけが利用不可になり、セットアップは成功すること。→ Task 4 `test_setup_succeeds_without_version`。
2. **選択した放送のメインサービスが Mirakurun から消えた（チャンネル再スキャン後）**: その放送は黙って除外され、セットアップは成功し、古いデバイスは削除されること。→ Task 3 `test_resolve_broadcasts_skips_missing_services`、Task 8 `test_stale_broadcast_device_removed`。
3. **番組表がまだ空のサービス（EPG 未取得）**: 現在の番組センサーは `unknown`、カレンダーは `off`、例外にならないこと。→ Task 7 `test_broadcast_without_programs`。
4. **ユーザーが URL に `/api/` や末尾スラッシュを付けて入力する、または同じサーバーを表記違いで二重登録する**: 正規化され、重複は `already_configured` で止まること。→ Task 1 `test_normalize_url`、Task 5 `test_user_flow_already_configured_with_different_spelling`。
5. **チューナーが後から増減する（設定変更・USB チューナーの抜き差し）**: 増えたチューナーのエンティティが再起動なしで現れ、消えたチューナーのエンティティは利用不可になること。→ Task 6 `test_new_tuner_added_dynamically`、`test_removed_tuner_becomes_unavailable`。

---

## ファイル構成

| パス | 責務 |
|---|---|
| `mise.toml` | Python と uv のバージョン、開発タスク |
| `pyproject.toml` | 開発用依存、pytest・ruff・mypy の設定 |
| `hacs.json` | HACS のメタデータ |
| `custom_components/__init__.py` | 空。テスト時に `custom_components` を通常パッケージとして解決させる |
| `custom_components/mirakurun/manifest.json` | インテグレーションのメタデータ |
| `custom_components/mirakurun/const.py` | 定数 |
| `custom_components/mirakurun/models.py` | API レスポンスの dataclass |
| `custom_components/mirakurun/api.py` | API クライアント、URL 正規化、例外 |
| `custom_components/mirakurun/programs.py` | 番組の時刻解決、現在・次の番組、ジャンル |
| `custom_components/mirakurun/broadcast.py` | 放送の判定、オプションとの変換、別番組の検出 |
| `custom_components/mirakurun/coordinator.py` | 3 つのコーディネーター、runtime data |
| `custom_components/mirakurun/__init__.py` | セットアップ、アンロード、不要デバイスの削除 |
| `custom_components/mirakurun/config_flow.py` | 設定・再設定・オプション |
| `custom_components/mirakurun/entity.py` | 基底エンティティ、デバイス情報、識別子 |
| `custom_components/mirakurun/sensor.py` | サーバー・チューナー・放送のセンサー |
| `custom_components/mirakurun/binary_sensor.py` | 番組表取得中・チューナー故障・サブチャンネル別番組中 |
| `custom_components/mirakurun/calendar.py` | 番組表カレンダー |
| `custom_components/mirakurun/update.py` | Mirakurun の更新エンティティ |
| `custom_components/mirakurun/diagnostics.py` | 診断 |
| `custom_components/mirakurun/icons.json` | アイコンの翻訳 |
| `custom_components/mirakurun/translations/{en,ja}.json` | 文言 |
| `custom_components/mirakurun/quality_scale.yaml` | 品質ルールの達成状況 |
| `tests/common.py` | テスト用の定数、番組ビルダー、モック登録、エンティティ ID 解決 |
| `tests/conftest.py` | フィクスチャ |
| `tests/fixtures/*.json` | API レスポンスの見本 |
| `.github/workflows/validate.yml` | CI |
| `README.md` | 利用者向け文書 |

---

### Task 1: 雛形と API クライアント

**Files:**
- Create: `mise.toml`, `pyproject.toml`, `hacs.json`, `.gitignore`, `custom_components/__init__.py`
- Create: `custom_components/mirakurun/manifest.json`, `custom_components/mirakurun/const.py`, `custom_components/mirakurun/models.py`, `custom_components/mirakurun/api.py`
- Create: `tests/__init__.py`, `tests/common.py`, `tests/conftest.py`
- Create: `tests/fixtures/version.json`, `tests/fixtures/status.json`, `tests/fixtures/tuners.json`, `tests/fixtures/services.json`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `api.normalize_url(url: str) -> str`（不正なら `ValueError`）
  - `api.MirakurunError`、`api.MirakurunConnectionError`、`api.MirakurunResponseError`
  - `api.MirakurunClient(session: aiohttp.ClientSession, base_url: str, *, timeout: float = 10.0)`。プロパティ `base_url: str`。メソッド `get_version() -> Version`、`get_status() -> Status`、`get_tuners() -> list[Tuner]`、`get_services() -> list[Service]`、`get_programs(network_id: int, service_id: int) -> list[Program]`
  - `models.Version(current: str, latest: str | None)`
  - `models.Status(version: str, tuner_device_streams: int, stored_events: int | None, gathering_networks: tuple[int, ...], error_counts: Mapping[str, int])`
  - `models.TunerUser(id: str, priority: int, channel_name: str | None)`
  - `models.Tuner(index: int, name: str, types: tuple[str, ...], users: tuple[TunerUser, ...], is_available: bool, is_free: bool, is_using: bool, is_fault: bool)`、プロパティ `top_user: TunerUser | None`
  - `models.ChannelRef(type: str, channel: str)`
  - `models.Service(id: int, service_id: int, network_id: int, name: str, type: int, remote_control_key_id: int | None, channel: ChannelRef, has_logo_data: bool)`
  - `models.Program(id: int, network_id: int, service_id: int, event_id: int, start: datetime, duration_ms: int, name: str | None, description: str | None, genre_lv1: int | None, shared_service_ids: frozenset[int])`、プロパティ `has_known_duration: bool`
  - `models.UNKNOWN_DURATION_MS = 1`
  - すべての model は `from_dict(data: Mapping[str, Any])` クラスメソッドを持つ
  - `const` の全定数（下記）
  - `tests/common.py`: `BASE_URL`、`ENTRY_ID`、`NOW`、`at(hour, minute=0)`、`load_fixture(name)`、`make_program(...)`、`PROGRAMS`、`NHK`、`NHK2`、`MX1`、`MX2`、`SHOP`、`TOEI`、`DEFAULT_OPTIONS`、`mock_mirakurun(...)`、`setup_integration(hass, entry)`、`entity_id(hass, platform, unique_id)`

- [ ] **Step 1: 雛形ファイルを作る**

`mise.toml`:

```toml
[tools]
python = "3.14"
uv = "latest"

[tasks.lint]
description = "Run linters and the type checker"
run = [
  "uv run ruff check .",
  "uv run ruff format --check .",
  "uv run mypy",
]

[tasks.test]
description = "Run tests with coverage"
run = "uv run pytest --cov=custom_components.mirakurun --cov-report=term-missing"
```

`pyproject.toml`:

```toml
[project]
name = "ha-mirakurun"
version = "0.1.0"
description = "Mirakurun integration for Home Assistant"
requires-python = ">=3.14"

[dependency-groups]
dev = [
  "pytest-homeassistant-custom-component==0.13.371",
  "pytest-cov",
  "ruff",
  "mypy",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.ruff.lint.isort]
force-sort-within-sections = true
known-first-party = ["custom_components"]

[tool.mypy]
python_version = "3.14"
strict = true
packages = ["custom_components.mirakurun"]
```

`hacs.json`:

```json
{
  "name": "Mirakurun",
  "homeassistant": "2026.10.0",
  "render_readme": true
}
```

`.gitignore`:

```
__pycache__/
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
```

`custom_components/__init__.py`: 空ファイル。

`tests/__init__.py`: 空ファイル。

`custom_components/mirakurun/manifest.json`:

```json
{
  "domain": "mirakurun",
  "name": "Mirakurun",
  "codeowners": ["@hinaloe"],
  "config_flow": true,
  "documentation": "https://github.com/hinaloe/ha-mirakurun",
  "integration_type": "hub",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/hinaloe/ha-mirakurun/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

`custom_components/mirakurun/const.py`:

```python
"""Constants for the Mirakurun integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "mirakurun"
MANUFACTURER: Final = "Chinachu Project"

CONF_BROADCASTS: Final = "broadcasts"
CONF_BROADCAST_MAP: Final = "broadcast_map"
CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_PROGRAM_INTERVAL: Final = "program_interval"

DEFAULT_STATUS_INTERVAL: Final = 30
MIN_STATUS_INTERVAL: Final = 10
MAX_STATUS_INTERVAL: Final = 300
DEFAULT_PROGRAM_INTERVAL: Final = 30
MIN_PROGRAM_INTERVAL: Final = 5
MAX_PROGRAM_INTERVAL: Final = 180
VERSION_INTERVAL: Final = timedelta(hours=12)

RELEASE_URL: Final = "https://github.com/Chinachu/Mirakurun/releases"
```

- [ ] **Step 2: 依存を入れる**

Run: `mise trust && mise install && uv sync`
Expected: mise が Python 3.14 と uv を入れ、`.venv` と `uv.lock` が作られる。エラーなし。`uv run python --version` が `Python 3.14.x` を表示する。

- [ ] **Step 3: フィクスチャを作る**

`tests/fixtures/version.json`:

```json
{"current": "4.0.0-beta.18", "latest": "4.1.5"}
```

`tests/fixtures/status.json`:

```json
{
  "time": 1791658441818,
  "version": "4.0.0-beta.18",
  "process": {"arch": "x64", "platform": "linux", "pid": 1},
  "epg": {"gatheringNetworks": [4, 7], "storedEvents": 26849},
  "rpcCount": 1,
  "streamCount": {"tunerDevice": 2, "tsFilter": 2, "decoder": 0},
  "errorCount": {
    "uncaughtException": 0,
    "unhandledRejection": 0,
    "bufferOverflow": 3,
    "tunerDeviceRespawn": 1747,
    "decoderRespawn": 0
  },
  "timerAccuracy": {"last": 593.288}
}
```

`tests/fixtures/tuners.json`:

```json
[
  {
    "index": 12,
    "name": "PT3-S1",
    "types": ["BS", "CS"],
    "command": "recpt1 --device /dev/pt3video0 BS01_0 - -",
    "pid": 100,
    "users": [
      {
        "id": "Mirakurun:getEPG()",
        "priority": -1,
        "disableDecoder": true,
        "streamSetting": {
          "channel": {"name": "BS:BS01_0", "type": "BS", "channel": "BS01_0", "commandVars": {}},
          "networkId": 4,
          "parseEIT": true
        },
        "streamInfo": {}
      },
      {
        "id": "EPGStation-recorder",
        "priority": 2,
        "streamSetting": {"channel": {"name": "ＢＳ朝日", "type": "BS", "channel": "BS01_0"}}
      }
    ],
    "isAvailable": true,
    "isRemote": false,
    "isFree": false,
    "isUsing": true,
    "isFault": false
  },
  {
    "index": 14,
    "name": "PT3-T1",
    "types": ["GR"],
    "command": null,
    "pid": null,
    "users": [],
    "isAvailable": true,
    "isRemote": false,
    "isFree": true,
    "isUsing": false,
    "isFault": false
  },
  {
    "index": 15,
    "name": "PT3-T2",
    "types": ["GR"],
    "command": null,
    "pid": null,
    "users": [],
    "isAvailable": true,
    "isRemote": false,
    "isFree": false,
    "isUsing": false,
    "isFault": true
  }
]
```

`tests/fixtures/services.json`:

```json
[
  {"id": 3273601024, "serviceId": 1024, "networkId": 32736, "name": "ＮＨＫ総合１・東京", "type": 1, "logoId": 0, "remoteControlKeyId": 1, "epgReady": true, "epgUpdatedAt": 1791656694129, "channel": {"type": "GR", "channel": "27"}, "hasLogoData": true},
  {"id": 3273601025, "serviceId": 1025, "networkId": 32736, "name": "ＮＨＫ総合２・東京", "type": 1, "remoteControlKeyId": 1, "channel": {"type": "GR", "channel": "27"}, "hasLogoData": true},
  {"id": 3273601408, "serviceId": 1408, "networkId": 32736, "name": "ＮＨＫ携帯Ｇ・東京", "type": 192, "remoteControlKeyId": 1, "channel": {"type": "GR", "channel": "27"}, "hasLogoData": false},
  {"id": 3239123608, "serviceId": 23608, "networkId": 32391, "name": "ＴＯＫＹＯ　ＭＸ１", "type": 1, "remoteControlKeyId": 9, "channel": {"type": "GR", "channel": "16"}, "hasLogoData": true},
  {"id": 3239123610, "serviceId": 23610, "networkId": 32391, "name": "ＴＯＫＹＯ　ＭＸ２", "type": 1, "remoteControlKeyId": 9, "channel": {"type": "GR", "channel": "16"}, "hasLogoData": true},
  {"id": 700055, "serviceId": 55, "networkId": 7, "name": "ショップチャンネル", "type": 1, "channel": {"type": "CS", "channel": "CS8"}, "hasLogoData": false},
  {"id": 700218, "serviceId": 218, "networkId": 7, "name": "東映チャンネル", "type": 1, "channel": {"type": "CS", "channel": "CS8"}, "hasLogoData": false}
]
```

- [ ] **Step 4: テスト共通部品を作る**

`tests/common.py`:

```python
"""Shared helpers for Mirakurun tests."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import (
    CONF_BROADCAST_MAP,
    CONF_BROADCASTS,
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
)

BASE_URL = "http://mirakurun.local:40772"
ENTRY_ID = "01JMIRAKURUNTESTENTRY00000"
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"

NHK = (32736, 1024)
NHK2 = (32736, 1025)
MX1 = (32391, 23608)
MX2 = (32391, 23610)
SHOP = (7, 55)
TOEI = (7, 218)


def at(hour: int, minute: int = 0) -> datetime:
    """Return a UTC time on the test day."""
    return NOW.replace(hour=hour, minute=minute)


def load_fixture(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_program(
    service: tuple[int, int],
    event_id: int,
    start: datetime,
    minutes: int | None,
    name: str,
    *,
    shared: Iterable[int] = (),
    genre: int | None = None,
) -> dict[str, Any]:
    """Build a Mirakurun program payload. ``minutes=None`` means unknown duration."""
    network_id, service_id = service
    item: dict[str, Any] = {
        "id": network_id * 10**10 + service_id * 10**5 + event_id,
        "eventId": event_id,
        "serviceId": service_id,
        "networkId": network_id,
        "startAt": int(start.timestamp() * 1000),
        "duration": minutes * 60_000 if minutes is not None else 1,
        "isFree": True,
        "name": name,
        "description": f"{name} description",
    }
    if genre is not None:
        item["genres"] = [{"lv1": genre, "lv2": 0, "un1": 15, "un2": 15}]
    shared_ids = list(shared)
    if shared_ids:
        item["relatedItems"] = [
            {"type": "shared", "serviceId": sid, "eventId": event_id}
            for sid in shared_ids
        ]
    return item


PROGRAMS: dict[tuple[int, int], list[dict[str, Any]]] = {
    NHK: [
        make_program(NHK, 1, at(11), 90, "ニュース", shared=(1024, 1025), genre=0),
        make_program(NHK, 2, at(12, 30), 30, "天気", shared=(1024, 1025), genre=0),
        make_program(NHK, 3, at(13), 60, "ドキュメント", shared=(1024, 1025), genre=8),
    ],
    NHK2: [
        make_program(NHK2, 1, at(11), 90, "ニュース", shared=(1024, 1025), genre=0),
        make_program(NHK2, 20, at(12, 30), 30, "国会中継", genre=0),
        make_program(NHK2, 3, at(13), 60, "ドキュメント", shared=(1024, 1025), genre=8),
    ],
    MX1: [
        make_program(MX1, 100, at(11, 30), 60, "MXニュース", genre=0),
        make_program(MX1, 101, at(12, 30), 60, "アニメ", genre=7),
    ],
    MX2: [make_program(MX2, 200, at(11), 120, "MX2特番", genre=5)],
    SHOP: [make_program(SHOP, 300, at(10), 240, "通販")],
    TOEI: [make_program(TOEI, 400, at(10), 240, "時代劇", genre=3)],
}

DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_BROADCAST_MAP: {
        "3273601024": [3273601025],
        "3239123608": [],
        "3239123610": [],
        "700055": [],
        "700218": [],
    },
    CONF_BROADCASTS: ["3273601024", "3239123608", "3239123610"],
    CONF_STATUS_INTERVAL: 30,
    CONF_PROGRAM_INTERVAL: 30,
}


def mock_mirakurun(
    aioclient_mock: AiohttpClientMocker,
    *,
    base_url: str = BASE_URL,
    tuners: Sequence[Mapping[str, Any]] | None = None,
    programs: Mapping[tuple[int, int], list[dict[str, Any]]] | None = None,
    fail_programs: Iterable[tuple[int, int]] = (),
    fail_status: bool = False,
    fail_version: bool = False,
    fail_services: bool = False,
) -> None:
    """Register mocked Mirakurun API responses."""
    api = f"{base_url}/api"
    failing = set(fail_programs)

    def register(path: str, payload: Any, fail: bool) -> None:
        if fail:
            aioclient_mock.get(f"{api}/{path}", exc=aiohttp.ClientError())
        else:
            aioclient_mock.get(f"{api}/{path}", json=payload)

    register("version", load_fixture("version.json"), fail_version)
    register("status", load_fixture("status.json"), fail_status)
    register(
        "tuners",
        list(tuners) if tuners is not None else load_fixture("tuners.json"),
        fail_status,
    )
    register("services", load_fixture("services.json"), fail_services)
    for (network_id, service_id), items in (programs or PROGRAMS).items():
        params = {"networkId": network_id, "serviceId": service_id}
        if (network_id, service_id) in failing:
            aioclient_mock.get(
                f"{api}/programs", params=params, exc=aiohttp.ClientError()
            )
        else:
            aioclient_mock.get(f"{api}/programs", params=params, json=items)


def create_entry(options: Mapping[str, Any] | None = None) -> MockConfigEntry:
    """Create a config entry for the mocked server."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mirakurun",
        data={CONF_URL: BASE_URL},
        options=dict(options if options is not None else DEFAULT_OPTIONS),
        entry_id=ENTRY_ID,
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Resolve an entity ID from its unique ID."""
    result = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert result is not None, unique_id
    return result
```

`tests/conftest.py`:

```python
"""Fixtures for Mirakurun tests."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import NOW, create_entry, mock_mirakurun


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture(autouse=True)
def frozen_now(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at the test reference time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def mirakurun(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a healthy Mirakurun server."""
    mock_mirakurun(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return the default config entry."""
    return create_entry()
```

- [ ] **Step 5: 失敗するテストを書く**

`tests/test_api.py`:

```python
"""Tests for the Mirakurun API client."""

from datetime import UTC, datetime

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.api import (
    MirakurunClient,
    MirakurunConnectionError,
    MirakurunResponseError,
    normalize_url,
)
from custom_components.mirakurun.models import ChannelRef, TunerUser, Version

from .common import BASE_URL, NHK, at, make_program


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://mirakurun.local:40772", "http://mirakurun.local:40772"),
        ("http://mirakurun.local:40772/", "http://mirakurun.local:40772"),
        ("http://mirakurun.local:40772/api", "http://mirakurun.local:40772"),
        (" http://mirakurun.local:40772/api/ ", "http://mirakurun.local:40772"),
        ("https://tv.example.com/mirakurun/api", "https://tv.example.com/mirakurun"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["mirakurun.local:40772", "ftp://host", "http://", ""])
def test_normalize_url_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(raw)


def _client(hass: HomeAssistant) -> MirakurunClient:
    return MirakurunClient(async_get_clientsession(hass), f"{BASE_URL}/api/")


async def test_get_version(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    client = _client(hass)
    assert client.base_url == BASE_URL
    assert await client.get_version() == Version("4.0.0-beta.18", "4.1.5")


async def test_get_status(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    status = await _client(hass).get_status()
    assert status.version == "4.0.0-beta.18"
    assert status.tuner_device_streams == 2
    assert status.stored_events == 26849
    assert status.gathering_networks == (4, 7)
    assert status.error_counts["tunerDeviceRespawn"] == 1747


async def test_get_tuners(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    tuners = await _client(hass).get_tuners()
    assert [t.index for t in tuners] == [12, 14, 15]
    first = tuners[0]
    assert first.name == "PT3-S1"
    assert first.types == ("BS", "CS")
    assert first.is_using and not first.is_free and not first.is_fault
    assert first.top_user == TunerUser("EPGStation-recorder", 2, "ＢＳ朝日")
    assert tuners[1].top_user is None
    assert tuners[2].is_fault


async def test_get_services(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    services = await _client(hass).get_services()
    assert len(services) == 7
    nhk = services[0]
    assert nhk.id == 3273601024
    assert nhk.service_id == 1024
    assert nhk.network_id == 32736
    assert nhk.name == "ＮＨＫ総合１・東京"
    assert nhk.type == 1
    assert nhk.remote_control_key_id == 1
    assert nhk.channel == ChannelRef("GR", "27")
    assert nhk.has_logo_data
    assert services[5].remote_control_key_id is None


async def test_get_programs(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    programs = await _client(hass).get_programs(*NHK)
    assert len(programs) == 3
    first = programs[0]
    assert first.id == 32736 * 10**10 + 1024 * 10**5 + 1
    assert first.event_id == 1
    assert first.start == datetime(2026, 10, 11, 11, 0, tzinfo=UTC)
    assert first.duration_ms == 90 * 60_000
    assert first.has_known_duration
    assert first.name == "ニュース"
    assert first.description == "ニュース description"
    assert first.genre_lv1 == 0
    assert first.shared_service_ids == frozenset({1024, 1025})


async def test_program_with_unknown_duration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    payload = make_program(NHK, 9, at(12), None, "未定")
    del payload["description"]
    aioclient_mock.get(
        f"{BASE_URL}/api/programs",
        params={"networkId": 32736, "serviceId": 1024},
        json=[payload],
    )
    (program,) = await _client(hass).get_programs(*NHK)
    assert program.duration_ms == 1
    assert not program.has_known_duration
    assert program.description is None
    assert program.genre_lv1 is None
    assert program.shared_service_ids == frozenset()


async def test_http_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/version", status=500)
    with pytest.raises(MirakurunResponseError):
        await _client(hass).get_version()


@pytest.mark.parametrize("exc", [TimeoutError(), aiohttp.ClientError()])
async def test_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/version", exc=exc)
    with pytest.raises(MirakurunConnectionError):
        await _client(hass).get_version()


async def test_invalid_json(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/version", text="not json")
    with pytest.raises(MirakurunResponseError):
        await _client(hass).get_version()


async def test_unexpected_payload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/tuners", json={"unexpected": True})
    with pytest.raises(MirakurunResponseError):
        await _client(hass).get_tuners()
```

- [ ] **Step 6: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'custom_components.mirakurun.api'`）

- [ ] **Step 7: models.py を実装する**

`custom_components/mirakurun/models.py`:

```python
"""Data models for Mirakurun API responses."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

UNKNOWN_DURATION_MS = 1


def _from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class Version:
    """Installed and latest Mirakurun versions."""

    current: str
    latest: str | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Version:
        latest = data.get("latest")
        return cls(current=str(data["current"]), latest=str(latest) if latest else None)


@dataclass(frozen=True, slots=True)
class Status:
    """Server status."""

    version: str
    tuner_device_streams: int
    stored_events: int | None
    gathering_networks: tuple[int, ...]
    error_counts: Mapping[str, int]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Status:
        epg = data.get("epg") or {}
        streams = data.get("streamCount") or {}
        stored = epg.get("storedEvents")
        errors = data.get("errorCount") or {}
        return cls(
            version=str(data["version"]),
            tuner_device_streams=int(streams.get("tunerDevice", 0)),
            stored_events=int(stored) if stored is not None else None,
            gathering_networks=tuple(int(n) for n in epg.get("gatheringNetworks") or ()),
            error_counts={str(key): int(value) for key, value in errors.items()},
        )


@dataclass(frozen=True, slots=True)
class TunerUser:
    """A client currently using a tuner."""

    id: str
    priority: int
    channel_name: str | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TunerUser:
        channel = (data.get("streamSetting") or {}).get("channel") or {}
        name = channel.get("name")
        return cls(
            id=str(data["id"]),
            priority=int(data.get("priority", 0)),
            channel_name=str(name) if name else None,
        )


@dataclass(frozen=True, slots=True)
class Tuner:
    """A tuner device."""

    index: int
    name: str
    types: tuple[str, ...]
    users: tuple[TunerUser, ...]
    is_available: bool
    is_free: bool
    is_using: bool
    is_fault: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Tuner:
        return cls(
            index=int(data["index"]),
            name=str(data["name"]),
            types=tuple(str(t) for t in data.get("types") or ()),
            users=tuple(TunerUser.from_dict(u) for u in data.get("users") or ()),
            is_available=bool(data.get("isAvailable", False)),
            is_free=bool(data.get("isFree", False)),
            is_using=bool(data.get("isUsing", False)),
            is_fault=bool(data.get("isFault", False)),
        )

    @property
    def top_user(self) -> TunerUser | None:
        """Return the user with the highest priority."""
        return max(self.users, key=lambda user: user.priority, default=None)


@dataclass(frozen=True, slots=True)
class ChannelRef:
    """A physical channel."""

    type: str
    channel: str


@dataclass(frozen=True, slots=True)
class Service:
    """A broadcast service."""

    id: int
    service_id: int
    network_id: int
    name: str
    type: int
    remote_control_key_id: int | None
    channel: ChannelRef
    has_logo_data: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Service:
        channel = data["channel"]
        key = data.get("remoteControlKeyId")
        return cls(
            id=int(data["id"]),
            service_id=int(data["serviceId"]),
            network_id=int(data["networkId"]),
            name=str(data["name"]),
            type=int(data["type"]),
            remote_control_key_id=int(key) if key is not None else None,
            channel=ChannelRef(type=str(channel["type"]), channel=str(channel["channel"])),
            has_logo_data=bool(data.get("hasLogoData", False)),
        )


@dataclass(frozen=True, slots=True)
class Program:
    """A program in the EPG."""

    id: int
    network_id: int
    service_id: int
    event_id: int
    start: datetime
    duration_ms: int
    name: str | None
    description: str | None
    genre_lv1: int | None
    shared_service_ids: frozenset[int]

    @property
    def has_known_duration(self) -> bool:
        """Return whether the broadcaster announced the duration."""
        return self.duration_ms > UNKNOWN_DURATION_MS

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Program:
        network_id = int(data["networkId"])
        genres = data.get("genres") or ()
        shared = frozenset(
            int(item["serviceId"])
            for item in data.get("relatedItems") or ()
            if item.get("type") == "shared"
            and int(item.get("networkId", network_id)) == network_id
        )
        return cls(
            id=int(data["id"]),
            network_id=network_id,
            service_id=int(data["serviceId"]),
            event_id=int(data["eventId"]),
            start=_from_ms(int(data["startAt"])),
            duration_ms=int(data["duration"]),
            name=data.get("name") or None,
            description=data.get("description") or None,
            genre_lv1=int(genres[0]["lv1"]) if genres else None,
            shared_service_ids=shared,
        )
```

- [ ] **Step 8: api.py を実装する**

`custom_components/mirakurun/api.py`:

```python
"""Minimal async client for the Mirakurun REST API."""

from collections.abc import Callable, Mapping
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from yarl import URL

from .models import Program, Service, Status, Tuner, Version


class MirakurunError(Exception):
    """Base error for the Mirakurun client."""


class MirakurunConnectionError(MirakurunError):
    """The server could not be reached."""


class MirakurunResponseError(MirakurunError):
    """The server returned an unexpected response."""


def normalize_url(url: str) -> str:
    """Normalize a user supplied URL to the server root without ``/api``."""
    parsed = URL(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError(f"Invalid Mirakurun URL: {url!r}")
    path = parsed.path.rstrip("/")
    path = path.removesuffix("/api")
    normalized = parsed.with_path(path or "/").with_query(None).with_fragment(None)
    return str(normalized).rstrip("/")


def _parse[T](parser: Callable[[Any], T], data: Any, what: str) -> T:
    try:
        return parser(data)
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise MirakurunResponseError(f"Unexpected {what} payload") from err


class MirakurunClient:
    """Client for a single Mirakurun server."""

    def __init__(
        self, session: ClientSession, base_url: str, *, timeout: float = 10.0
    ) -> None:
        self._session = session
        self._base_url = normalize_url(base_url)
        self._timeout = ClientTimeout(total=timeout)

    @property
    def base_url(self) -> str:
        """Return the normalized server URL."""
        return self._base_url

    async def _get_json(
        self, path: str, params: Mapping[str, int] | None = None
    ) -> Any:
        url = f"{self._base_url}/api/{path}"
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as response:
                if response.status != 200:
                    raise MirakurunResponseError(
                        f"GET {path} returned HTTP {response.status}"
                    )
                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise MirakurunResponseError(
                        f"GET {path} returned invalid JSON"
                    ) from err
        except (TimeoutError, ClientError) as err:
            raise MirakurunConnectionError(f"GET {path} failed: {err!r}") from err

    async def get_version(self) -> Version:
        data = await self._get_json("version")
        return _parse(Version.from_dict, data, "version")

    async def get_status(self) -> Status:
        data = await self._get_json("status")
        return _parse(Status.from_dict, data, "status")

    async def get_tuners(self) -> list[Tuner]:
        data = await self._get_json("tuners")
        return _parse(lambda d: [Tuner.from_dict(item) for item in d], data, "tuners")

    async def get_services(self) -> list[Service]:
        data = await self._get_json("services")
        return _parse(
            lambda d: [Service.from_dict(item) for item in d], data, "services"
        )

    async def get_programs(self, network_id: int, service_id: int) -> list[Program]:
        data = await self._get_json(
            "programs", {"networkId": network_id, "serviceId": service_id}
        )
        return _parse(
            lambda d: [Program.from_dict(item) for item in d], data, "programs"
        )
```

`get_tuners` に `{"unexpected": True}` が来た場合、反復でキー文字列が `Tuner.from_dict` に渡り、`str` の添字アクセスで `TypeError` になる。これを `_parse` が `MirakurunResponseError` に変える。

- [ ] **Step 9: テストが通ることを確かめる**

Run: `uv run pytest tests/test_api.py -v`
Expected: すべて PASS

- [ ] **Step 10: 型と書式を確かめてコミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy`
Expected: エラーなし

```bash
git add -A
git commit -m "feat: add Mirakurun API client and project scaffolding

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 番組スケジュールの計算

**Files:**
- Create: `custom_components/mirakurun/programs.py`
- Test: `tests/test_programs.py`

**Interfaces:**
- Consumes: `models.Program`
- Produces:
  - `programs.ScheduledProgram(program: Program, start: datetime, end: datetime)`
  - `programs.Schedule = tuple[ScheduledProgram, ...]`（型エイリアス）
  - `programs.build_schedule(programs: Iterable[Program]) -> Schedule`
  - `programs.current_program(schedule: Sequence[ScheduledProgram], now: datetime) -> ScheduledProgram | None`
  - `programs.next_program(schedule: Sequence[ScheduledProgram], now: datetime) -> ScheduledProgram | None`
  - `programs.programs_between(schedule: Sequence[ScheduledProgram], start: datetime, end: datetime) -> list[ScheduledProgram]`
  - `programs.next_transition(schedule: Sequence[ScheduledProgram], now: datetime) -> datetime | None`
  - `programs.genre_key(lv1: int | None) -> str | None`
  - `programs.GENRE_KEYS: dict[int, str]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_programs.py`:

```python
"""Tests for schedule helpers."""

from datetime import timedelta

from custom_components.mirakurun.models import Program
from custom_components.mirakurun.programs import (
    build_schedule,
    current_program,
    genre_key,
    next_program,
    next_transition,
    programs_between,
)

from .common import NHK, PROGRAMS, at, make_program


def _programs(*payloads: dict) -> list[Program]:
    return [Program.from_dict(p) for p in payloads]


NHK_PROGRAMS = _programs(*PROGRAMS[NHK])


def test_known_durations() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    assert [(s.start, s.end) for s in schedule] == [
        (at(11), at(12, 30)),
        (at(12, 30), at(13)),
        (at(13), at(14)),
    ]


def test_input_is_sorted() -> None:
    schedule = build_schedule(reversed(NHK_PROGRAMS))
    assert [s.program.name for s in schedule] == ["ニュース", "天気", "ドキュメント"]


def test_unknown_duration_ends_at_next_program() -> None:
    schedule = build_schedule(
        _programs(
            make_program(NHK, 1, at(11), None, "延長あり"),
            make_program(NHK, 2, at(12, 15), 30, "次"),
        )
    )
    assert schedule[0].end == at(12, 15)


def test_unknown_duration_without_next_lasts_one_hour() -> None:
    schedule = build_schedule(_programs(make_program(NHK, 1, at(11), None, "最後")))
    assert schedule[0].end == at(11) + timedelta(hours=1)


def test_current_and_next_program() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    assert current_program(schedule, at(12)).program.name == "ニュース"
    assert next_program(schedule, at(12)).program.name == "天気"
    # start is inclusive, end is exclusive
    assert current_program(schedule, at(12, 30)).program.name == "天気"
    assert current_program(schedule, at(14)) is None
    assert next_program(schedule, at(13)) is None


def test_current_program_in_gap() -> None:
    schedule = build_schedule(
        _programs(
            make_program(NHK, 1, at(11), 30, "前"),
            make_program(NHK, 2, at(12), 30, "後"),
        )
    )
    assert current_program(schedule, at(11, 45)) is None
    assert next_program(schedule, at(11, 45)).program.name == "後"


def test_programs_between() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    names = [s.program.name for s in programs_between(schedule, at(12, 45), at(13, 30))]
    assert names == ["天気", "ドキュメント"]
    assert programs_between(schedule, at(14), at(15)) == []


def test_next_transition() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    assert next_transition(schedule, at(12)) == at(12, 30)
    assert next_transition(schedule, at(12, 30)) == at(13)
    assert next_transition(schedule, at(14)) is None
    assert next_transition((), at(12)) is None


def test_genre_key() -> None:
    assert genre_key(0) == "news"
    assert genre_key(7) == "anime"
    assert genre_key(15) == "other"
    assert genre_key(12) is None
    assert genre_key(None) is None
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_programs.py -v`
Expected: FAIL（`No module named 'custom_components.mirakurun.programs'`）

- [ ] **Step 3: 実装する**

`custom_components/mirakurun/programs.py`:

```python
"""Schedule helpers built on top of Mirakurun programs."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Program

FALLBACK_DURATION = timedelta(hours=1)

# ARIB STD-B10 content_nibble_level_1
GENRE_KEYS: dict[int, str] = {
    0: "news",
    1: "sports",
    2: "information",
    3: "drama",
    4: "music",
    5: "variety",
    6: "movie",
    7: "anime",
    8: "documentary",
    9: "theater",
    10: "hobby",
    11: "welfare",
    14: "extension",
    15: "other",
}


@dataclass(frozen=True, slots=True)
class ScheduledProgram:
    """A program with a resolved end time."""

    program: Program
    start: datetime
    end: datetime


type Schedule = tuple[ScheduledProgram, ...]


def build_schedule(programs: Iterable[Program]) -> Schedule:
    """Sort programs and resolve end times, including unknown durations."""
    ordered = sorted(programs, key=lambda program: program.start)
    result: list[ScheduledProgram] = []
    for index, program in enumerate(ordered):
        if program.has_known_duration:
            end = program.start + timedelta(milliseconds=program.duration_ms)
        else:
            following = next(
                (p.start for p in ordered[index + 1 :] if p.start > program.start),
                None,
            )
            end = following if following is not None else program.start + FALLBACK_DURATION
        result.append(ScheduledProgram(program, program.start, end))
    return tuple(result)


def current_program(
    schedule: Sequence[ScheduledProgram], now: datetime
) -> ScheduledProgram | None:
    """Return the program on air at ``now``."""
    return next((item for item in schedule if item.start <= now < item.end), None)


def next_program(
    schedule: Sequence[ScheduledProgram], now: datetime
) -> ScheduledProgram | None:
    """Return the first program starting after ``now``."""
    return next((item for item in schedule if item.start > now), None)


def programs_between(
    schedule: Sequence[ScheduledProgram], start: datetime, end: datetime
) -> list[ScheduledProgram]:
    """Return programs overlapping the given window."""
    return [item for item in schedule if item.end > start and item.start < end]


def next_transition(
    schedule: Sequence[ScheduledProgram], now: datetime
) -> datetime | None:
    """Return the next time a program starts or ends."""
    return min(
        (t for item in schedule for t in (item.start, item.end) if t > now),
        default=None,
    )


def genre_key(lv1: int | None) -> str | None:
    """Return the translation key for an ARIB top level genre."""
    return None if lv1 is None else GENRE_KEYS.get(lv1)
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_programs.py -v`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy`

```bash
git add -A
git commit -m "feat: add program schedule helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 放送の判定

**Files:**
- Create: `custom_components/mirakurun/broadcast.py`
- Test: `tests/test_broadcast.py`

**Interfaces:**
- Consumes: `api.MirakurunClient`、`api.MirakurunError`、`models.Program`、`models.Service`、`programs.Schedule`、`programs.ScheduledProgram`、`programs.build_schedule`、`programs.current_program`
- Produces:
  - `broadcast.Broadcast(main: Service, subs: tuple[Service, ...] = ())`
  - `broadcast.SubchannelSplit(service: Service, program: ScheduledProgram)`
  - `broadcast.group_by_channel(services: Sequence[Service]) -> list[list[Service]]`
  - `broadcast.classify_channel(services: Sequence[Service], main_programs: Sequence[Program] | None, now: datetime) -> list[Broadcast]`
  - `broadcast.discover_broadcasts(client: MirakurunClient, now: datetime) -> list[Broadcast]`（async。`get_services` の失敗は `MirakurunError` のまま送出）
  - `broadcast.to_option_map(broadcasts: Sequence[Broadcast]) -> dict[str, list[int]]`
  - `broadcast.default_selection(broadcasts: Sequence[Broadcast]) -> list[str]`
  - `broadcast.resolve_broadcasts(option_map: Mapping[str, Sequence[int]], selected: Sequence[str], services: Sequence[Service]) -> list[Broadcast]`
  - `broadcast.distinct_sub_programs(main: Service, main_schedule: Schedule, sub_schedule: Schedule) -> list[ScheduledProgram]`
  - `broadcast.detect_splits(main: Service, main_schedule: Schedule, subs: Sequence[tuple[Service, Schedule]], now: datetime) -> list[SubchannelSplit]`
  - 定数 `TV_SERVICE_TYPE = 1`、`SHARED_RATIO_THRESHOLD = 0.5`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_broadcast.py`:

```python
"""Tests for broadcast grouping."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.api import MirakurunClient
from custom_components.mirakurun.broadcast import (
    Broadcast,
    classify_channel,
    default_selection,
    detect_splits,
    discover_broadcasts,
    distinct_sub_programs,
    group_by_channel,
    resolve_broadcasts,
    to_option_map,
)
from custom_components.mirakurun.models import Program, Service
from custom_components.mirakurun.programs import build_schedule

from .common import (
    BASE_URL,
    MX1,
    NHK,
    NHK2,
    NOW,
    PROGRAMS,
    at,
    load_fixture,
    make_program,
    mock_mirakurun,
)

SERVICES = [Service.from_dict(s) for s in load_fixture("services.json")]
BY_SID = {s.service_id: s for s in SERVICES}
NHK_SVC, NHK2_SVC = BY_SID[1024], BY_SID[1025]
MX1_SVC, MX2_SVC = BY_SID[23608], BY_SID[23610]
SHOP_SVC, TOEI_SVC = BY_SID[55], BY_SID[218]


def _programs(key: tuple[int, int]) -> list[Program]:
    return [Program.from_dict(p) for p in PROGRAMS[key]]


def test_group_by_channel() -> None:
    groups = group_by_channel(SERVICES)
    assert [[s.service_id for s in g] for g in groups] == [
        [1024, 1025],
        [23608, 23610],
        [55, 218],
    ]


def test_classify_dependent_subchannel() -> None:
    result = classify_channel([NHK_SVC, NHK2_SVC], _programs(NHK), NOW)
    assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]


def test_classify_independent_subchannel() -> None:
    result = classify_channel([MX1_SVC, MX2_SVC], _programs(MX1), NOW)
    assert result == [Broadcast(MX1_SVC), Broadcast(MX2_SVC)]


def test_classify_cohabiting_channels() -> None:
    result = classify_channel([SHOP_SVC, TOEI_SVC], [], NOW)
    assert result == [Broadcast(SHOP_SVC), Broadcast(TOEI_SVC)]


def test_classify_failure_makes_everything_independent() -> None:
    result = classify_channel([NHK_SVC, NHK2_SVC], None, NOW)
    assert result == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]


def test_classify_ignores_past_programs() -> None:
    past_shared = [
        Program.from_dict(make_program(NHK, 1, at(9), 60, "過去", shared=(1025,))),
        Program.from_dict(make_program(NHK, 2, at(12), 60, "現在")),
    ]
    result = classify_channel([NHK_SVC, NHK2_SVC], past_shared, NOW)
    assert result == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]


def test_classify_threshold_is_inclusive() -> None:
    half = [
        Program.from_dict(make_program(NHK, 1, at(12), 60, "共有", shared=(1025,))),
        Program.from_dict(make_program(NHK, 2, at(13), 60, "単独")),
    ]
    result = classify_channel([NHK_SVC, NHK2_SVC], half, NOW)
    assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]


async def test_discover_broadcasts(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover_broadcasts(client, NOW)
    assert result == [
        Broadcast(NHK_SVC, (NHK2_SVC,)),
        Broadcast(MX1_SVC),
        Broadcast(MX2_SVC),
        Broadcast(SHOP_SVC),
        Broadcast(TOEI_SVC),
    ]


async def test_discover_broadcasts_with_failed_channel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_mirakurun(aioclient_mock, fail_programs={NHK})
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover_broadcasts(client, NOW)
    assert result[:2] == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]
    assert len(result) == 6


def test_option_round_trip() -> None:
    broadcasts = [Broadcast(NHK_SVC, (NHK2_SVC,)), Broadcast(MX2_SVC), Broadcast(SHOP_SVC)]
    option_map = to_option_map(broadcasts)
    assert option_map == {"3273601024": [3273601025], "3239123610": [], "700055": []}
    assert default_selection(broadcasts) == ["3273601024", "3239123610"]
    assert resolve_broadcasts(option_map, ["3273601024", "700055"], SERVICES) == [
        Broadcast(NHK_SVC, (NHK2_SVC,)),
        Broadcast(SHOP_SVC),
    ]


def test_resolve_broadcasts_skips_missing_services() -> None:
    option_map = {"3273601024": [3273601025, 9999], "1234": []}
    remaining = [s for s in SERVICES if s.service_id != 1025]
    assert resolve_broadcasts(option_map, ["3273601024", "1234"], remaining) == [
        Broadcast(NHK_SVC)
    ]


def test_distinct_sub_programs() -> None:
    main = build_schedule(_programs(NHK))
    sub = build_schedule(_programs(NHK2))
    assert [s.program.name for s in distinct_sub_programs(NHK_SVC, main, sub)] == [
        "国会中継"
    ]


def test_detect_splits() -> None:
    main = build_schedule(_programs(NHK))
    subs = [(NHK2_SVC, build_schedule(_programs(NHK2)))]
    assert detect_splits(NHK_SVC, main, subs, at(12)) == []
    (split,) = detect_splits(NHK_SVC, main, subs, at(12, 30))
    assert split.service == NHK2_SVC
    assert split.program.program.name == "国会中継"
    assert detect_splits(NHK_SVC, main, subs, at(13)) == []
    assert detect_splits(NHK_SVC, main, [(NHK2_SVC, ())], at(12, 30)) == []
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_broadcast.py -v`
Expected: FAIL（`No module named 'custom_components.mirakurun.broadcast'`）

- [ ] **Step 3: 実装する**

`custom_components/mirakurun/broadcast.py`:

```python
"""Group Mirakurun services into broadcasts (main service plus subchannels)."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from .api import MirakurunClient, MirakurunError
from .models import Program, Service
from .programs import Schedule, ScheduledProgram, build_schedule, current_program

TV_SERVICE_TYPE = 1
SHARED_RATIO_THRESHOLD = 0.5
DISCOVERY_CONCURRENCY = 4


@dataclass(frozen=True, slots=True)
class Broadcast:
    """A main service and the subchannels that usually simulcast it."""

    main: Service
    subs: tuple[Service, ...] = ()


@dataclass(frozen=True, slots=True)
class SubchannelSplit:
    """A subchannel currently airing something other than the main service."""

    service: Service
    program: ScheduledProgram


def group_by_channel(services: Sequence[Service]) -> list[list[Service]]:
    """Group TV services by physical channel, each sorted by service ID."""
    groups: dict[tuple[str, str], list[Service]] = defaultdict(list)
    for service in services:
        if service.type == TV_SERVICE_TYPE:
            groups[(service.channel.type, service.channel.channel)].append(service)
    return [sorted(group, key=lambda s: s.service_id) for group in groups.values()]


def classify_channel(
    services: Sequence[Service],
    main_programs: Sequence[Program] | None,
    now: datetime,
) -> list[Broadcast]:
    """Split one physical channel into broadcasts by how often programs are shared."""
    main, *others = services
    upcoming = [
        item.program
        for item in build_schedule(main_programs or ())
        if item.end > now
    ]
    if not upcoming:
        return [Broadcast(service) for service in services]
    subs: list[Service] = []
    independents: list[Service] = []
    for service in others:
        shared = sum(1 for p in upcoming if service.service_id in p.shared_service_ids)
        if shared / len(upcoming) >= SHARED_RATIO_THRESHOLD:
            subs.append(service)
        else:
            independents.append(service)
    return [Broadcast(main, tuple(subs)), *(Broadcast(s) for s in independents)]


async def discover_broadcasts(
    client: MirakurunClient, now: datetime
) -> list[Broadcast]:
    """Fetch services and classify every physical channel."""
    services = await client.get_services()
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def classify(group: list[Service]) -> list[Broadcast]:
        main = group[0]
        programs: list[Program] | None
        async with semaphore:
            try:
                programs = await client.get_programs(main.network_id, main.service_id)
            except MirakurunError:
                programs = None
        return classify_channel(group, programs, now)

    results = await asyncio.gather(
        *(classify(group) for group in group_by_channel(services))
    )
    return [broadcast for result in results for broadcast in result]


def to_option_map(broadcasts: Sequence[Broadcast]) -> dict[str, list[int]]:
    """Serialize broadcasts for config entry options."""
    return {str(b.main.id): [s.id for s in b.subs] for b in broadcasts}


def default_selection(broadcasts: Sequence[Broadcast]) -> list[str]:
    """Return the broadcasts selected by default: every terrestrial broadcast."""
    return [str(b.main.id) for b in broadcasts if b.main.channel.type == "GR"]


def resolve_broadcasts(
    option_map: Mapping[str, Sequence[int]],
    selected: Sequence[str],
    services: Sequence[Service],
) -> list[Broadcast]:
    """Rebuild selected broadcasts, skipping services that no longer exist."""
    by_id = {service.id: service for service in services}
    result: list[Broadcast] = []
    for key in selected:
        main = by_id.get(int(key))
        if main is None:
            continue
        subs = tuple(by_id[sid] for sid in option_map.get(key, ()) if sid in by_id)
        result.append(Broadcast(main, subs))
    return result


def _main_keys(main_schedule: Schedule) -> set[tuple[int, datetime]]:
    return {(item.program.event_id, item.start) for item in main_schedule}


def _is_distinct(
    main: Service, main_keys: set[tuple[int, datetime]], item: ScheduledProgram
) -> bool:
    return (
        main.service_id not in item.program.shared_service_ids
        and (item.program.event_id, item.start) not in main_keys
    )


def distinct_sub_programs(
    main: Service, main_schedule: Schedule, sub_schedule: Schedule
) -> list[ScheduledProgram]:
    """Return subchannel programs that are not simulcasts of the main service."""
    keys = _main_keys(main_schedule)
    return [item for item in sub_schedule if _is_distinct(main, keys, item)]


def detect_splits(
    main: Service,
    main_schedule: Schedule,
    subs: Sequence[tuple[Service, Schedule]],
    now: datetime,
) -> list[SubchannelSplit]:
    """Return subchannels airing their own program at ``now``."""
    keys = _main_keys(main_schedule)
    splits: list[SubchannelSplit] = []
    for service, schedule in subs:
        current = current_program(schedule, now)
        if current is not None and _is_distinct(main, keys, current):
            splits.append(SubchannelSplit(service, current))
    return splits
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_broadcast.py -v`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy`

```bash
git add -A
git commit -m "feat: classify services into broadcasts and detect subchannel splits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: コーディネーターとセットアップ

**Files:**
- Create: `custom_components/mirakurun/coordinator.py`, `custom_components/mirakurun/__init__.py`
- Create: `custom_components/mirakurun/translations/en.json`, `custom_components/mirakurun/translations/ja.json`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: Task 1〜3 のすべて
- Produces:
  - `coordinator.StatusData(status: Status, tuners: tuple[Tuner, ...])`
  - `coordinator.BroadcastSchedule(broadcast: Broadcast, main: Schedule, subs: tuple[tuple[Service, Schedule], ...])`
  - `coordinator.StatusCoordinator(hass, entry, client)`（`DataUpdateCoordinator[StatusData]`、属性 `client`）
  - `coordinator.ProgramCoordinator(hass, entry, client, broadcasts: tuple[Broadcast, ...])`（`DataUpdateCoordinator[dict[int, BroadcastSchedule]]`、キーはメインサービスの `id`、属性 `broadcasts`）
  - `coordinator.VersionCoordinator(hass, entry, client)`（`DataUpdateCoordinator[Version]`）
  - `coordinator.MirakurunRuntimeData(client, broadcasts, status, programs, version)`
  - `coordinator.MirakurunConfigEntry = ConfigEntry[MirakurunRuntimeData]`
  - `__init__.PLATFORMS: list[Platform]`（このタスクでは空。Task 6〜8 で追加）
  - 翻訳ファイルは以降のタスクで使う全キーをこのタスクで用意する

- [ ] **Step 1: 翻訳ファイルを作る**

`custom_components/mirakurun/translations/en.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to Mirakurun",
        "description": "Enter the URL of your Mirakurun server.",
        "data": {"url": "URL"},
        "data_description": {"url": "For example http://192.168.1.10:40772"}
      },
      "reconfigure": {
        "title": "Change the Mirakurun URL",
        "data": {"url": "URL"},
        "data_description": {"url": "For example http://192.168.1.10:40772"}
      }
    },
    "error": {
      "invalid_url": "Enter a URL starting with http:// or https://.",
      "cannot_connect": "Could not connect to Mirakurun.",
      "unknown": "Unexpected error."
    },
    "abort": {
      "already_configured": "This Mirakurun server is already configured.",
      "reconfigure_successful": "The Mirakurun URL was updated."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Mirakurun options",
        "data": {
          "broadcasts": "Broadcasts",
          "status_interval": "Tuner and status polling interval",
          "program_interval": "Program guide polling interval"
        },
        "data_description": {
          "broadcasts": "Broadcasts to create program guide entities for. Subchannels that usually simulcast the main service are grouped with it.",
          "status_interval": "How often to poll tuner usage and server status.",
          "program_interval": "How often to refresh the program guide."
        }
      }
    },
    "abort": {"cannot_connect": "Could not connect to Mirakurun."}
  },
  "entity": {
    "sensor": {
      "tuners_in_use": {"name": "Tuners in use"},
      "tuners_free": {"name": "Free tuners"},
      "streams": {"name": "Tuner streams"},
      "stored_events": {"name": "Stored programs"},
      "tuner_respawns": {"name": "Tuner respawns"},
      "uncaught_exceptions": {"name": "Uncaught exceptions"},
      "unhandled_rejections": {"name": "Unhandled rejections"},
      "buffer_overflows": {"name": "Buffer overflows"},
      "decoder_respawns": {"name": "Decoder respawns"},
      "tuner_state": {
        "name": "State",
        "state": {
          "fault": "Fault",
          "disabled": "Disabled",
          "in_use": "In use",
          "free": "Free"
        }
      },
      "tuner_channel": {"name": "Channel"},
      "tuner_user": {
        "name": "User",
        "state_attributes": {"users": {"name": "Users"}}
      },
      "current_program": {
        "name": "Current program",
        "state_attributes": {
          "start": {"name": "Start"},
          "end": {"name": "End"},
          "description": {"name": "Description"},
          "genre": {
            "name": "Genre",
            "state": {
              "news": "News",
              "sports": "Sports",
              "information": "Information",
              "drama": "Drama",
              "music": "Music",
              "variety": "Variety",
              "movie": "Movie",
              "anime": "Anime",
              "documentary": "Documentary",
              "theater": "Theater",
              "hobby": "Hobby and education",
              "welfare": "Welfare",
              "extension": "Extension",
              "other": "Other"
            }
          }
        }
      },
      "next_program": {
        "name": "Next program",
        "state_attributes": {
          "start": {"name": "Start"},
          "genre": {
            "name": "Genre",
            "state": {
              "news": "News",
              "sports": "Sports",
              "information": "Information",
              "drama": "Drama",
              "music": "Music",
              "variety": "Variety",
              "movie": "Movie",
              "anime": "Anime",
              "documentary": "Documentary",
              "theater": "Theater",
              "hobby": "Hobby and education",
              "welfare": "Welfare",
              "extension": "Extension",
              "other": "Other"
            }
          }
        }
      }
    },
    "binary_sensor": {
      "epg_gathering": {"name": "Gathering program guide"},
      "tuner_fault": {"name": "Fault"},
      "subchannel_split": {
        "name": "Subchannel airing a different program",
        "state_attributes": {"subchannels": {"name": "Subchannels"}}
      }
    },
    "calendar": {
      "schedule": {"name": "Schedule"}
    }
  },
  "exceptions": {
    "cannot_connect": {"message": "Could not connect to Mirakurun: {error}"},
    "update_failed": {"message": "Error communicating with Mirakurun: {error}"}
  }
}
```

`custom_components/mirakurun/translations/ja.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Mirakurun に接続",
        "description": "Mirakurun サーバーの URL を入力してください。",
        "data": {"url": "URL"},
        "data_description": {"url": "例: http://192.168.1.10:40772"}
      },
      "reconfigure": {
        "title": "Mirakurun の URL を変更",
        "data": {"url": "URL"},
        "data_description": {"url": "例: http://192.168.1.10:40772"}
      }
    },
    "error": {
      "invalid_url": "http:// または https:// で始まる URL を入力してください。",
      "cannot_connect": "Mirakurun に接続できませんでした。",
      "unknown": "予期しないエラーが発生しました。"
    },
    "abort": {
      "already_configured": "この Mirakurun サーバーは設定済みです。",
      "reconfigure_successful": "Mirakurun の URL を更新しました。"
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Mirakurun のオプション",
        "data": {
          "broadcasts": "放送",
          "status_interval": "チューナーと状態の取得間隔",
          "program_interval": "番組表の取得間隔"
        },
        "data_description": {
          "broadcasts": "番組情報のエンティティを作る放送を選びます。ふだんメインと同じ番組を流すサブチャンネルは、メインにまとめられます。",
          "status_interval": "チューナーの使用状況とサーバーの状態を取得する間隔です。",
          "program_interval": "番組表を取得し直す間隔です。"
        }
      }
    },
    "abort": {"cannot_connect": "Mirakurun に接続できませんでした。"}
  },
  "entity": {
    "sensor": {
      "tuners_in_use": {"name": "使用中のチューナー"},
      "tuners_free": {"name": "空きチューナー"},
      "streams": {"name": "チューナーのストリーム数"},
      "stored_events": {"name": "保持番組数"},
      "tuner_respawns": {"name": "チューナーの再起動回数"},
      "uncaught_exceptions": {"name": "未捕捉の例外"},
      "unhandled_rejections": {"name": "未処理の Promise 拒否"},
      "buffer_overflows": {"name": "バッファーあふれ"},
      "decoder_respawns": {"name": "デコーダーの再起動回数"},
      "tuner_state": {
        "name": "状態",
        "state": {
          "fault": "故障",
          "disabled": "無効",
          "in_use": "使用中",
          "free": "空き"
        }
      },
      "tuner_channel": {"name": "チャンネル"},
      "tuner_user": {
        "name": "利用者",
        "state_attributes": {"users": {"name": "利用者一覧"}}
      },
      "current_program": {
        "name": "現在の番組",
        "state_attributes": {
          "start": {"name": "開始"},
          "end": {"name": "終了"},
          "description": {"name": "説明"},
          "genre": {
            "name": "ジャンル",
            "state": {
              "news": "ニュース／報道",
              "sports": "スポーツ",
              "information": "情報／ワイドショー",
              "drama": "ドラマ",
              "music": "音楽",
              "variety": "バラエティ",
              "movie": "映画",
              "anime": "アニメ／特撮",
              "documentary": "ドキュメンタリー／教養",
              "theater": "劇場／公演",
              "hobby": "趣味／教育",
              "welfare": "福祉",
              "extension": "拡張",
              "other": "その他"
            }
          }
        }
      },
      "next_program": {
        "name": "次の番組",
        "state_attributes": {
          "start": {"name": "開始"},
          "genre": {
            "name": "ジャンル",
            "state": {
              "news": "ニュース／報道",
              "sports": "スポーツ",
              "information": "情報／ワイドショー",
              "drama": "ドラマ",
              "music": "音楽",
              "variety": "バラエティ",
              "movie": "映画",
              "anime": "アニメ／特撮",
              "documentary": "ドキュメンタリー／教養",
              "theater": "劇場／公演",
              "hobby": "趣味／教育",
              "welfare": "福祉",
              "extension": "拡張",
              "other": "その他"
            }
          }
        }
      }
    },
    "binary_sensor": {
      "epg_gathering": {"name": "番組表取得中"},
      "tuner_fault": {"name": "故障"},
      "subchannel_split": {
        "name": "サブチャンネル別番組中",
        "state_attributes": {"subchannels": {"name": "サブチャンネル"}}
      }
    },
    "calendar": {
      "schedule": {"name": "番組表"}
    }
  },
  "exceptions": {
    "cannot_connect": {"message": "Mirakurun に接続できませんでした: {error}"},
    "update_failed": {"message": "Mirakurun との通信でエラーが発生しました: {error}"}
  }
}
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_init.py`:

```python
"""Tests for setting up the Mirakurun integration."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import NHK, NHK2, PROGRAMS, mock_mirakurun, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    data = config_entry.runtime_data
    assert [b.main.service_id for b in data.broadcasts] == [1024, 23608, 23610]
    assert [s.service_id for s in data.broadcasts[0].subs] == [1025]
    assert len(data.status.data.tuners) == 3
    assert data.version.data.latest == "4.1.5"
    nhk = data.programs.data[3273601024]
    assert [s.program.name for s in nhk.main] == ["ニュース", "天気", "ドキュメント"]
    assert [s.program.name for s in nhk.subs[0][1]][1] == "国会中継"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_services_fail(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, fail_services=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_status_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, fail_status=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_succeeds_without_version(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, fail_version=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert not config_entry.runtime_data.version.last_update_success


async def test_program_refresh_keeps_previous_data_on_partial_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    programs = config_entry.runtime_data.programs
    before = programs.data[3273601024].subs[0][1]

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_programs={NHK2})
    await programs.async_refresh()

    assert programs.last_update_success
    assert programs.data[3273601024].subs[0][1] == before


async def test_program_refresh_fails_when_everything_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    programs = config_entry.runtime_data.programs

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_programs=set(PROGRAMS))
    await programs.async_refresh()

    assert not programs.last_update_success


async def test_setup_with_service_without_programs(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, programs={**PROGRAMS, NHK: []})
    await setup_integration(hass, config_entry)
    assert config_entry.runtime_data.programs.data[3273601024].main == ()
```

- [ ] **Step 3: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_init.py -v`
Expected: FAIL（`Integration 'mirakurun' not found` などでセットアップできない）

- [ ] **Step 4: coordinator.py を実装する**

`custom_components/mirakurun/coordinator.py`:

```python
"""Data update coordinators for Mirakurun."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MirakurunClient, MirakurunError
from .broadcast import Broadcast
from .const import (
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    VERSION_INTERVAL,
)
from .models import Service, Status, Tuner, Version
from .programs import Schedule, build_schedule

_LOGGER = logging.getLogger(__package__)

type MirakurunConfigEntry = ConfigEntry[MirakurunRuntimeData]


@dataclass(frozen=True, slots=True)
class StatusData:
    """Server status and tuners fetched together."""

    status: Status
    tuners: tuple[Tuner, ...]


@dataclass(frozen=True, slots=True)
class BroadcastSchedule:
    """Schedules for a broadcast's main service and its subchannels."""

    broadcast: Broadcast
    main: Schedule
    subs: tuple[tuple[Service, Schedule], ...]


def _update_failed(err: MirakurunError) -> UpdateFailed:
    return UpdateFailed(
        translation_domain=DOMAIN,
        translation_key="update_failed",
        translation_placeholders={"error": str(err)},
    )


class StatusCoordinator(DataUpdateCoordinator[StatusData]):
    """Polls server status and tuners."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MirakurunConfigEntry, client: MirakurunClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_status",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
            ),
        )
        self.client = client

    async def _async_update_data(self) -> StatusData:
        try:
            status, tuners = await asyncio.gather(
                self.client.get_status(), self.client.get_tuners()
            )
        except MirakurunError as err:
            raise _update_failed(err) from err
        return StatusData(status, tuple(tuners))


class ProgramCoordinator(DataUpdateCoordinator[dict[int, BroadcastSchedule]]):
    """Polls programs for the selected broadcasts."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MirakurunConfigEntry,
        client: MirakurunClient,
        broadcasts: tuple[Broadcast, ...],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_programs",
            update_interval=timedelta(
                minutes=entry.options.get(
                    CONF_PROGRAM_INTERVAL, DEFAULT_PROGRAM_INTERVAL
                )
            ),
        )
        self.client = client
        self.broadcasts = broadcasts
        self._schedules: dict[int, Schedule] = {}

    async def _async_update_data(self) -> dict[int, BroadcastSchedule]:
        services = [s for b in self.broadcasts for s in (b.main, *b.subs)]
        results = await asyncio.gather(
            *(self.client.get_programs(s.network_id, s.service_id) for s in services),
            return_exceptions=True,
        )
        schedules: dict[int, Schedule] = {}
        errors: list[MirakurunError] = []
        for service, result in zip(services, results, strict=True):
            if isinstance(result, MirakurunError):
                errors.append(result)
                if service.id in self._schedules:
                    schedules[service.id] = self._schedules[service.id]
            elif isinstance(result, BaseException):
                raise result
            else:
                schedules[service.id] = build_schedule(result)
        if services and len(errors) == len(services):
            raise _update_failed(errors[0]) from errors[0]
        if errors:
            _LOGGER.debug(
                "Failed to fetch programs for %d of %d services",
                len(errors),
                len(services),
            )
        self._schedules = schedules
        return {
            b.main.id: BroadcastSchedule(
                b,
                schedules.get(b.main.id, ()),
                tuple((s, schedules.get(s.id, ())) for s in b.subs),
            )
            for b in self.broadcasts
        }


class VersionCoordinator(DataUpdateCoordinator[Version]):
    """Polls the installed and latest Mirakurun versions."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MirakurunConfigEntry, client: MirakurunClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_version",
            update_interval=VERSION_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> Version:
        try:
            return await self.client.get_version()
        except MirakurunError as err:
            raise _update_failed(err) from err


@dataclass(slots=True)
class MirakurunRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: MirakurunClient
    broadcasts: tuple[Broadcast, ...]
    status: StatusCoordinator
    programs: ProgramCoordinator
    version: VersionCoordinator
```

- [ ] **Step 5: __init__.py を実装する**

`custom_components/mirakurun/__init__.py`:

```python
"""The Mirakurun integration."""

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MirakurunClient, MirakurunError
from .broadcast import resolve_broadcasts
from .const import CONF_BROADCAST_MAP, CONF_BROADCASTS, DOMAIN
from .coordinator import (
    MirakurunConfigEntry,
    MirakurunRuntimeData,
    ProgramCoordinator,
    StatusCoordinator,
    VersionCoordinator,
)

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Set up Mirakurun from a config entry."""
    client = MirakurunClient(async_get_clientsession(hass), entry.data[CONF_URL])
    try:
        services = await client.get_services()
    except MirakurunError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    broadcasts = tuple(
        resolve_broadcasts(
            entry.options.get(CONF_BROADCAST_MAP, {}),
            entry.options.get(CONF_BROADCASTS, []),
            services,
        )
    )
    status = StatusCoordinator(hass, entry, client)
    programs = ProgramCoordinator(hass, entry, client, broadcasts)
    version = VersionCoordinator(hass, entry, client)

    await status.async_config_entry_first_refresh()
    await programs.async_config_entry_first_refresh()
    # The latest version comes from npm via Mirakurun and may be unreachable;
    # it must not block setup.
    await version.async_refresh()

    entry.runtime_data = MirakurunRuntimeData(
        client, broadcasts, status, programs, version
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 6: テストが通ることを確かめる**

Run: `uv run pytest tests/test_init.py -v`
Expected: すべて PASS

- [ ] **Step 7: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy && uv run pytest`

```bash
git add -A
git commit -m "feat: add coordinators and config entry setup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 設定フロー

**Files:**
- Create: `custom_components/mirakurun/config_flow.py`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `api.MirakurunClient`、`api.MirakurunError`、`api.normalize_url`、`broadcast.Broadcast`、`broadcast.default_selection`、`broadcast.discover_broadcasts`、`broadcast.to_option_map`、`coordinator.MirakurunConfigEntry`、`const` の定数
- Produces:
  - `config_flow.build_options(broadcasts: Sequence[Broadcast], selected: list[str] | None = None, status_interval: int = DEFAULT_STATUS_INTERVAL, program_interval: int = DEFAULT_PROGRAM_INTERVAL) -> dict[str, Any]`
  - `config_flow.MirakurunConfigFlow`（`user`、`reconfigure`）
  - `config_flow.MirakurunOptionsFlow`（`init`、`OptionsFlowWithReload`）
  - エントリのタイトルは `Mirakurun ({host})`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config_flow.py`:

```python
"""Tests for the Mirakurun config flow."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import (
    CONF_BROADCAST_MAP,
    CONF_BROADCASTS,
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
)

from .common import BASE_URL, DEFAULT_OPTIONS, mock_mirakurun, setup_integration

OTHER_URL = "http://other.local:40772"


@pytest.fixture
def mock_setup_entry() -> Iterator[AsyncMock]:
    with patch(
        "custom_components.mirakurun.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def test_user_flow(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f"{BASE_URL}/api/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Mirakurun (mirakurun.local)"
    assert result["data"] == {CONF_URL: BASE_URL}
    assert result["options"] == DEFAULT_OPTIONS
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_flow_invalid_url_then_recovers(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "mirakurun.local:40772"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect_then_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    mock_mirakurun(aioclient_mock, fail_version=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_services_fail(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    mock_mirakurun(aioclient_mock, fail_services=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.mirakurun.config_flow.MirakurunClient.get_version",
        side_effect=RuntimeError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: BASE_URL}
        )
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured_with_different_spelling(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f" {BASE_URL}/api "}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_mirakurun(aioclient_mock, base_url=OTHER_URL)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f"{OTHER_URL}/"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_URL: OTHER_URL}
    assert config_entry.title == "Mirakurun (other.local)"


async def test_reconfigure_same_url(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_to_other_configured_server(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    MockConfigEntry(domain=DOMAIN, data={CONF_URL: OTHER_URL}).add_to_hass(hass)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: OTHER_URL}
    )
    assert result["reason"] == "already_configured"


async def test_reconfigure_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_mirakurun(aioclient_mock, base_url=OTHER_URL, fail_version=True)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "nonsense"}
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: OTHER_URL}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_BROADCASTS: ["700055"],
            CONF_STATUS_INTERVAL: 60,
            CONF_PROGRAM_INTERVAL: 10,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_BROADCAST_MAP: DEFAULT_OPTIONS[CONF_BROADCAST_MAP],
        CONF_BROADCASTS: ["700055"],
        CONF_STATUS_INTERVAL: 60,
        CONF_PROGRAM_INTERVAL: 10,
    }
    assert [b.main.service_id for b in config_entry.runtime_data.broadcasts] == [55]


async def test_options_flow_drops_vanished_selection(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options={**DEFAULT_OPTIONS, CONF_BROADCASTS: ["3273601024", "1"]},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    default = next(k for k in schema if k == CONF_BROADCASTS).default()
    assert default == ["3273601024"]


async def test_options_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, fail_services=True)
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_config_flow.py -v`
Expected: FAIL（`Invalid handler specified` など。設定フローがまだない）

- [ ] **Step 3: 実装する**

`custom_components/mirakurun/config_flow.py`:

```python
"""Config flow for Mirakurun."""

from collections.abc import Sequence
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol
from yarl import URL

from .api import MirakurunClient, MirakurunError, normalize_url
from .broadcast import Broadcast, default_selection, discover_broadcasts, to_option_map
from .const import (
    CONF_BROADCAST_MAP,
    CONF_BROADCASTS,
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MAX_PROGRAM_INTERVAL,
    MAX_STATUS_INTERVAL,
    MIN_PROGRAM_INTERVAL,
    MIN_STATUS_INTERVAL,
)
from .coordinator import MirakurunConfigEntry

_LOGGER = logging.getLogger(__name__)

URL_SCHEMA = vol.Schema(
    {vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL))}
)


def build_options(
    broadcasts: Sequence[Broadcast],
    selected: list[str] | None = None,
    status_interval: int = DEFAULT_STATUS_INTERVAL,
    program_interval: int = DEFAULT_PROGRAM_INTERVAL,
) -> dict[str, Any]:
    """Build config entry options from classified broadcasts."""
    return {
        CONF_BROADCAST_MAP: to_option_map(broadcasts),
        CONF_BROADCASTS: default_selection(broadcasts) if selected is None else selected,
        CONF_STATUS_INTERVAL: status_interval,
        CONF_PROGRAM_INTERVAL: program_interval,
    }


def _title(url: str) -> str:
    return f"Mirakurun ({URL(url).host})"


class MirakurunConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mirakurun."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: MirakurunConfigEntry,
    ) -> MirakurunOptionsFlow:
        """Return the options flow."""
        return MirakurunOptionsFlow()

    async def _async_check(self, url: str) -> dict[str, str]:
        client = MirakurunClient(async_get_clientsession(self.hass), url)
        try:
            await client.get_version()
        except MirakurunError:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to Mirakurun")
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the server URL."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                self._async_abort_entries_match({CONF_URL: url})
                errors = await self._async_check(url)
                if not errors:
                    client = MirakurunClient(async_get_clientsession(self.hass), url)
                    try:
                        broadcasts = await discover_broadcasts(
                            client, dt_util.utcnow()
                        )
                    except MirakurunError:
                        errors["base"] = "cannot_connect"
                    else:
                        return self.async_create_entry(
                            title=_title(url),
                            data={CONF_URL: url},
                            options=build_options(broadcasts),
                        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(URL_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the server URL."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                if url != entry.data[CONF_URL]:
                    self._async_abort_entries_match({CONF_URL: url})
                errors = await self._async_check(url)
                if not errors:
                    return self.async_update_reload_and_abort(
                        entry, title=_title(url), data_updates={CONF_URL: url}
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                URL_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )


class MirakurunOptionsFlow(OptionsFlowWithReload):
    """Select broadcasts and polling intervals."""

    def __init__(self) -> None:
        self._broadcasts: list[Broadcast] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form, re-classifying broadcasts on open."""
        if user_input is not None:
            return self.async_create_entry(
                data=build_options(
                    self._broadcasts,
                    selected=list(user_input[CONF_BROADCASTS]),
                    status_interval=int(user_input[CONF_STATUS_INTERVAL]),
                    program_interval=int(user_input[CONF_PROGRAM_INTERVAL]),
                )
            )

        client = MirakurunClient(
            async_get_clientsession(self.hass), self.config_entry.data[CONF_URL]
        )
        try:
            self._broadcasts = await discover_broadcasts(client, dt_util.utcnow())
        except MirakurunError:
            return self.async_abort(reason="cannot_connect")

        options = self.config_entry.options
        available = {str(b.main.id) for b in self._broadcasts}
        selected = [
            key
            for key in options.get(CONF_BROADCASTS, default_selection(self._broadcasts))
            if key in available
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_BROADCASTS, default=selected): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=str(b.main.id),
                                label=f"{b.main.channel.type}: {b.main.name}",
                            )
                            for b in self._broadcasts
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STATUS_INTERVAL,
                        max=MAX_STATUS_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PROGRAM_INTERVAL,
                    default=options.get(
                        CONF_PROGRAM_INTERVAL, DEFAULT_PROGRAM_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_PROGRAM_INTERVAL,
                        max=MAX_PROGRAM_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_config_flow.py -v --cov=custom_components.mirakurun.config_flow --cov-report=term-missing`
Expected: すべて PASS。`config_flow.py` のカバレッジが 100%。100% に届かない行があれば、その分岐を通るテストを追加する（Quality Scale の config-flow-test-coverage）。

- [ ] **Step 5: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy && uv run pytest`

```bash
git add -A
git commit -m "feat: add config, reconfigure and options flows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: サーバーとチューナーのエンティティ

**Files:**
- Create: `custom_components/mirakurun/entity.py`, `custom_components/mirakurun/sensor.py`, `custom_components/mirakurun/binary_sensor.py`, `custom_components/mirakurun/icons.json`
- Modify: `custom_components/mirakurun/__init__.py`（`PLATFORMS`）
- Test: `tests/test_sensor.py`, `tests/test_binary_sensor.py`

**Interfaces:**
- Consumes: `coordinator.MirakurunConfigEntry`、`coordinator.StatusCoordinator`、`coordinator.StatusData`、`models.Tuner`
- Produces（`entity.py`）:
  - `server_identifier(entry) -> str`（= `entry.entry_id`）
  - `tuner_identifier(entry, index: int) -> str`（= `f"{entry_id}_tuner_{index}"`）
  - `broadcast_identifier(entry, main_id: int) -> str`（= `f"{entry_id}_broadcast_{main_id}"`）
  - `server_device_info(entry) -> DeviceInfo`、`tuner_device_info(entry, tuner) -> DeviceInfo`、`broadcast_device_info(entry, broadcast) -> DeviceInfo`
  - `MirakurunEntity[C]`（`CoordinatorEntity[C]`、`_attr_has_entity_name = True`）
  - `MirakurunServerEntity(coordinator: StatusCoordinator, entry, key: str)`。`unique_id` は `f"{entry_id}_server_{key}"`
  - `MirakurunTunerEntity(coordinator: StatusCoordinator, entry, tuner: Tuner, key: str)`。プロパティ `tuner: Tuner | None`。`unique_id` は `f"{entry_id}_tuner_{index}_{key}"`
  - `async_add_tuner_entities(entry, coordinator, factory: Callable[[Tuner], Iterable[Entity]], async_add_entities) -> None`
- Produces（`sensor.py`）: `tuner_state(tuner: Tuner) -> str`、`TUNER_STATES = ["fault", "disabled", "in_use", "free"]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sensor.py`:

```python
"""Tests for Mirakurun sensors."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import ENTRY_ID, entity_id, load_fixture, mock_mirakurun, setup_integration


def _state(hass: HomeAssistant, unique_id: str) -> str:
    state = hass.states.get(entity_id(hass, "sensor", unique_id))
    assert state is not None
    return state.state


async def _refresh_status(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_server_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_server_tuners_in_use") == "1"
    assert _state(hass, f"{ENTRY_ID}_server_tuners_free") == "1"
    assert _state(hass, f"{ENTRY_ID}_server_streams") == "2"
    assert _state(hass, f"{ENTRY_ID}_server_tuner_respawns") == "1747"


async def test_diagnostic_sensors_disabled_by_default(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    for key in (
        "stored_events",
        "uncaught_exceptions",
        "unhandled_rejections",
        "buffer_overflows",
        "decoder_respawns",
    ):
        entry = entity_registry.async_get(
            entity_id(hass, "sensor", f"{ENTRY_ID}_server_{key}")
        )
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_tuner_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_tuner_12_state") == "in_use"
    assert _state(hass, f"{ENTRY_ID}_tuner_12_channel") == "ＢＳ朝日"
    assert _state(hass, f"{ENTRY_ID}_tuner_12_user") == "EPGStation-recorder"
    user = hass.states.get(entity_id(hass, "sensor", f"{ENTRY_ID}_tuner_12_user"))
    assert user.attributes["users"] == [
        {"id": "Mirakurun:getEPG()", "priority": -1},
        {"id": "EPGStation-recorder", "priority": 2},
    ]
    assert _state(hass, f"{ENTRY_ID}_tuner_14_state") == "free"
    assert _state(hass, f"{ENTRY_ID}_tuner_14_channel") == STATE_UNKNOWN
    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == "fault"


async def test_disabled_tuner_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    tuners = load_fixture("tuners.json")
    tuners[1]["isAvailable"] = False
    mock_mirakurun(aioclient_mock, tuners=tuners)
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_tuner_14_state") == "disabled"


async def test_new_tuner_added_dynamically(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    tuners = load_fixture("tuners.json")
    tuners.append({**tuners[1], "index": 16, "name": "PX-T3"})
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=tuners)
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_tuner_16_state") == "free"


async def test_removed_tuner_becomes_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=load_fixture("tuners.json")[:2])
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == STATE_UNAVAILABLE
    assert _state(hass, f"{ENTRY_ID}_tuner_14_state") == "free"


async def test_status_failure_makes_entities_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_status=True)
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_server_tuners_in_use") == STATE_UNAVAILABLE
    assert _state(hass, f"{ENTRY_ID}_tuner_12_state") == STATE_UNAVAILABLE
```

`tests/test_binary_sensor.py`:

```python
"""Tests for Mirakurun binary sensors."""

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import ENTRY_ID, entity_id, setup_integration


def _state(hass: HomeAssistant, unique_id: str) -> str:
    state = hass.states.get(entity_id(hass, "binary_sensor", unique_id))
    assert state is not None
    return state.state


async def test_server_and_tuner_binary_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_server_epg_gathering") == STATE_ON
    assert _state(hass, f"{ENTRY_ID}_tuner_12_fault") == STATE_OFF
    assert _state(hass, f"{ENTRY_ID}_tuner_15_fault") == STATE_ON
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_sensor.py tests/test_binary_sensor.py -v`
Expected: FAIL（`AssertionError: ..._server_tuners_in_use`。エンティティがない）

- [ ] **Step 3: entity.py を実装する**

`custom_components/mirakurun/entity.py`:

```python
"""Base entities and device info for Mirakurun."""

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .broadcast import Broadcast
from .const import DOMAIN, MANUFACTURER
from .coordinator import MirakurunConfigEntry, StatusCoordinator
from .models import Tuner


def server_identifier(entry: MirakurunConfigEntry) -> str:
    """Return the device identifier of the server."""
    return entry.entry_id


def tuner_identifier(entry: MirakurunConfigEntry, index: int) -> str:
    """Return the device identifier of a tuner."""
    return f"{entry.entry_id}_tuner_{index}"


def broadcast_identifier(entry: MirakurunConfigEntry, main_id: int) -> str:
    """Return the device identifier of a broadcast."""
    return f"{entry.entry_id}_broadcast_{main_id}"


def server_device_info(entry: MirakurunConfigEntry) -> DeviceInfo:
    """Return device info for the server."""
    return DeviceInfo(
        identifiers={(DOMAIN, server_identifier(entry))},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model="Mirakurun",
        sw_version=entry.runtime_data.status.data.status.version,
        configuration_url=entry.data[CONF_URL],
    )


def tuner_device_info(entry: MirakurunConfigEntry, tuner: Tuner) -> DeviceInfo:
    """Return device info for a tuner."""
    return DeviceInfo(
        identifiers={(DOMAIN, tuner_identifier(entry, tuner.index))},
        name=tuner.name,
        manufacturer=MANUFACTURER,
        model=f"Tuner ({'/'.join(tuner.types)})",
        via_device=(DOMAIN, server_identifier(entry)),
    )


def broadcast_device_info(entry: MirakurunConfigEntry, broadcast: Broadcast) -> DeviceInfo:
    """Return device info for a broadcast."""
    main = broadcast.main
    return DeviceInfo(
        identifiers={(DOMAIN, broadcast_identifier(entry, main.id))},
        name=main.name,
        manufacturer=MANUFACTURER,
        model=f"{main.channel.type} {main.channel.channel}",
        via_device=(DOMAIN, server_identifier(entry)),
    )


class MirakurunEntity[CoordinatorT: DataUpdateCoordinator[Any]](
    CoordinatorEntity[CoordinatorT]
):
    """Base class for Mirakurun entities."""

    _attr_has_entity_name = True


class MirakurunServerEntity(MirakurunEntity[StatusCoordinator]):
    """An entity of the server device."""

    def __init__(
        self, coordinator: StatusCoordinator, entry: MirakurunConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_server_{key}"
        self._attr_device_info = server_device_info(entry)


class MirakurunTunerEntity(MirakurunEntity[StatusCoordinator]):
    """An entity of a tuner device."""

    def __init__(
        self,
        coordinator: StatusCoordinator,
        entry: MirakurunConfigEntry,
        tuner: Tuner,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._index = tuner.index
        self._attr_unique_id = f"{tuner_identifier(entry, tuner.index)}_{key}"
        self._attr_device_info = tuner_device_info(entry, tuner)

    @property
    def tuner(self) -> Tuner | None:
        """Return the latest data for this tuner."""
        return next(
            (t for t in self.coordinator.data.tuners if t.index == self._index), None
        )

    @property
    def available(self) -> bool:
        """Return whether the tuner still exists."""
        return super().available and self.tuner is not None


def async_add_tuner_entities(
    entry: MirakurunConfigEntry,
    coordinator: StatusCoordinator,
    factory: Callable[[Tuner], Iterable[Entity]],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add entities for current tuners and for tuners that appear later."""
    known: set[int] = set()

    @callback
    def add_new_tuners() -> None:
        new = [t for t in coordinator.data.tuners if t.index not in known]
        if not new:
            return
        known.update(t.index for t in new)
        async_add_entities(entity for tuner in new for entity in factory(tuner))

    add_new_tuners()
    entry.async_on_unload(coordinator.async_add_listener(add_new_tuners))
```

- [ ] **Step 4: sensor.py を実装する**

`custom_components/mirakurun/sensor.py`:

```python
"""Sensors for Mirakurun."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MirakurunConfigEntry, StatusCoordinator, StatusData
from .entity import MirakurunServerEntity, MirakurunTunerEntity, async_add_tuner_entities
from .models import Tuner

PARALLEL_UPDATES = 0

TUNER_STATES = ["fault", "disabled", "in_use", "free"]


def tuner_state(tuner: Tuner) -> str:
    """Return the enum state of a tuner."""
    if tuner.is_fault:
        return "fault"
    if not tuner.is_available:
        return "disabled"
    if tuner.is_using:
        return "in_use"
    return "free"


@dataclass(frozen=True, kw_only=True)
class MirakurunServerSensorDescription(SensorEntityDescription):
    """Describes a server sensor."""

    value_fn: Callable[[StatusData], int | None]


def _error_count(key: str) -> Callable[[StatusData], int | None]:
    return lambda data: data.status.error_counts.get(key)


SERVER_SENSORS: tuple[MirakurunServerSensorDescription, ...] = (
    MirakurunServerSensorDescription(
        key="tuners_in_use",
        translation_key="tuners_in_use",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: sum(t.is_using for t in data.tuners),
    ),
    MirakurunServerSensorDescription(
        key="tuners_free",
        translation_key="tuners_free",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: sum(t.is_free for t in data.tuners),
    ),
    MirakurunServerSensorDescription(
        key="streams",
        translation_key="streams",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.tuner_device_streams,
    ),
    MirakurunServerSensorDescription(
        key="stored_events",
        translation_key="stored_events",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.stored_events,
    ),
    MirakurunServerSensorDescription(
        key="tuner_respawns",
        translation_key="tuner_respawns",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_error_count("tunerDeviceRespawn"),
    ),
    MirakurunServerSensorDescription(
        key="uncaught_exceptions",
        translation_key="uncaught_exceptions",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_error_count("uncaughtException"),
    ),
    MirakurunServerSensorDescription(
        key="unhandled_rejections",
        translation_key="unhandled_rejections",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_error_count("unhandledRejection"),
    ),
    MirakurunServerSensorDescription(
        key="buffer_overflows",
        translation_key="buffer_overflows",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_error_count("bufferOverflow"),
    ),
    MirakurunServerSensorDescription(
        key="decoder_respawns",
        translation_key="decoder_respawns",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_error_count("decoderRespawn"),
    ),
)


@dataclass(frozen=True, kw_only=True)
class MirakurunTunerSensorDescription(SensorEntityDescription):
    """Describes a tuner sensor."""

    value_fn: Callable[[Tuner], str | None]
    attributes_fn: Callable[[Tuner], dict[str, Any]] | None = None


TUNER_SENSORS: tuple[MirakurunTunerSensorDescription, ...] = (
    MirakurunTunerSensorDescription(
        key="state",
        translation_key="tuner_state",
        device_class=SensorDeviceClass.ENUM,
        options=TUNER_STATES,
        value_fn=tuner_state,
    ),
    MirakurunTunerSensorDescription(
        key="channel",
        translation_key="tuner_channel",
        value_fn=lambda t: t.top_user.channel_name if t.top_user else None,
    ),
    MirakurunTunerSensorDescription(
        key="user",
        translation_key="tuner_user",
        value_fn=lambda t: t.top_user.id if t.top_user else None,
        attributes_fn=lambda t: {
            "users": [{"id": u.id, "priority": u.priority} for u in t.users]
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Mirakurun sensors."""
    status = entry.runtime_data.status
    async_add_entities(
        MirakurunServerSensor(status, entry, description)
        for description in SERVER_SENSORS
    )
    async_add_tuner_entities(
        entry,
        status,
        lambda tuner: [
            MirakurunTunerSensor(status, entry, tuner, description)
            for description in TUNER_SENSORS
        ],
        async_add_entities,
    )


class MirakurunServerSensor(MirakurunServerEntity, SensorEntity):
    """A server level sensor."""

    entity_description: MirakurunServerSensorDescription

    def __init__(
        self,
        coordinator: StatusCoordinator,
        entry: MirakurunConfigEntry,
        description: MirakurunServerSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data)


class MirakurunTunerSensor(MirakurunTunerEntity, SensorEntity):
    """A tuner level sensor."""

    entity_description: MirakurunTunerSensorDescription

    def __init__(
        self,
        coordinator: StatusCoordinator,
        entry: MirakurunConfigEntry,
        tuner: Tuner,
        description: MirakurunTunerSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, tuner, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | None:
        tuner = self.tuner
        return self.entity_description.value_fn(tuner) if tuner else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        tuner = self.tuner
        if tuner is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(tuner)
```

- [ ] **Step 5: binary_sensor.py を実装する**

`custom_components/mirakurun/binary_sensor.py`:

```python
"""Binary sensors for Mirakurun."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MirakurunConfigEntry, StatusCoordinator
from .entity import MirakurunServerEntity, MirakurunTunerEntity, async_add_tuner_entities
from .models import Tuner

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Mirakurun binary sensors."""
    status = entry.runtime_data.status
    async_add_entities([MirakurunGatheringBinarySensor(status, entry)])
    async_add_tuner_entities(
        entry,
        status,
        lambda tuner: [MirakurunTunerFaultBinarySensor(status, entry, tuner)],
        async_add_entities,
    )


class MirakurunGatheringBinarySensor(MirakurunServerEntity, BinarySensorEntity):
    """On while Mirakurun is gathering the program guide."""

    _attr_translation_key = "epg_gathering"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: StatusCoordinator, entry: MirakurunConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "epg_gathering")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.status.gathering_networks)


class MirakurunTunerFaultBinarySensor(MirakurunTunerEntity, BinarySensorEntity):
    """On when a tuner reports a fault."""

    _attr_translation_key = "tuner_fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: StatusCoordinator,
        entry: MirakurunConfigEntry,
        tuner: Tuner,
    ) -> None:
        super().__init__(coordinator, entry, tuner, "fault")

    @property
    def is_on(self) -> bool | None:
        tuner = self.tuner
        return tuner.is_fault if tuner else None
```

- [ ] **Step 6: icons.json を作り、プラットフォームを登録する**

`custom_components/mirakurun/icons.json`:

```json
{
  "entity": {
    "sensor": {
      "tuners_in_use": {"default": "mdi:television-classic"},
      "tuners_free": {"default": "mdi:television-classic-off"},
      "streams": {"default": "mdi:transit-connection-variant"},
      "stored_events": {"default": "mdi:database"},
      "tuner_respawns": {"default": "mdi:restart"},
      "uncaught_exceptions": {"default": "mdi:alert-circle-outline"},
      "unhandled_rejections": {"default": "mdi:alert-circle-outline"},
      "buffer_overflows": {"default": "mdi:tray-full"},
      "decoder_respawns": {"default": "mdi:restart"},
      "tuner_state": {
        "default": "mdi:tune-vertical",
        "state": {
          "fault": "mdi:alert",
          "disabled": "mdi:cancel",
          "in_use": "mdi:record-rec",
          "free": "mdi:sleep"
        }
      },
      "tuner_channel": {"default": "mdi:television-guide"},
      "tuner_user": {"default": "mdi:account"},
      "current_program": {"default": "mdi:television-play"},
      "next_program": {"default": "mdi:television-guide"}
    },
    "binary_sensor": {
      "epg_gathering": {"default": "mdi:download"},
      "subchannel_split": {"default": "mdi:call-split"}
    },
    "calendar": {
      "schedule": {"default": "mdi:calendar-clock"}
    }
  }
}
```

`custom_components/mirakurun/__init__.py` の `PLATFORMS` を次に置き換える:

```python
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]
```

- [ ] **Step 7: テストが通ることを確かめる**

Run: `uv run pytest -v`
Expected: すべて PASS

- [ ] **Step 8: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy`

```bash
git add -A
git commit -m "feat: add server and tuner sensors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 放送のエンティティ（番組センサー、別番組センサー、カレンダー）

**Files:**
- Create: `custom_components/mirakurun/calendar.py`
- Modify: `custom_components/mirakurun/entity.py`（`MirakurunBroadcastEntity` を追加）
- Modify: `custom_components/mirakurun/sensor.py`（放送のセンサーを追加）
- Modify: `custom_components/mirakurun/binary_sensor.py`（別番組センサーを追加）
- Modify: `custom_components/mirakurun/__init__.py`（`PLATFORMS`）
- Test: `tests/test_broadcast_entities.py`

**Interfaces:**
- Consumes: `coordinator.ProgramCoordinator`、`coordinator.BroadcastSchedule`、`broadcast.Broadcast`、`broadcast.detect_splits`、`broadcast.distinct_sub_programs`、`programs.*`、`entity.broadcast_identifier`、`entity.broadcast_device_info`
- Produces:
  - `entity.MirakurunBroadcastEntity(coordinator: ProgramCoordinator, entry, broadcast: Broadcast, key: str)`。属性 `broadcast`、プロパティ `schedule: BroadcastSchedule | None`。`unique_id` は `f"{entry_id}_broadcast_{main_id}_{key}"`。番組の切り替わり時刻に状態を書き直す
  - キー: `current_program`、`next_program`（sensor）、`subchannel_split`（binary_sensor）、`schedule`（calendar）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_broadcast_entities.py`:

```python
"""Tests for broadcast entities."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import DOMAIN

from .common import (
    ENTRY_ID,
    NHK,
    PROGRAMS,
    at,
    entity_id,
    mock_mirakurun,
    setup_integration,
)

NHK_KEY = f"{ENTRY_ID}_broadcast_3273601024"
MX1_KEY = f"{ENTRY_ID}_broadcast_3239123608"


async def _move_to(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_program_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)

    current = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_current_program"))
    assert current.state == "ニュース"
    assert current.attributes["start"] == at(11).isoformat()
    assert current.attributes["end"] == at(12, 30).isoformat()
    assert current.attributes["description"] == "ニュース description"
    assert current.attributes["genre"] == "news"

    upcoming = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_next_program"))
    assert upcoming.state == "天気"
    assert upcoming.attributes["start"] == at(12, 30).isoformat()


async def test_program_sensors_follow_transitions(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    await setup_integration(hass, config_entry)
    await _move_to(hass, frozen_now, at(12, 30))

    current = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_current_program"))
    assert current.state == "天気"
    upcoming = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_next_program"))
    assert upcoming.state == "ドキュメント"


async def test_subchannel_split(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    split_id = entity_id(hass, "binary_sensor", f"{NHK_KEY}_subchannel_split")
    assert hass.states.get(split_id).state == STATE_OFF
    assert hass.states.get(split_id).attributes["subchannels"] == []

    await _move_to(hass, frozen_now, at(12, 30))
    state = hass.states.get(split_id)
    assert state.state == STATE_ON
    assert state.attributes["subchannels"] == [
        {
            "service": "ＮＨＫ総合２・東京",
            "program": "国会中継",
            "end": at(13).isoformat(),
        }
    ]

    await _move_to(hass, frozen_now, at(13))
    assert hass.states.get(split_id).state == STATE_OFF

    assert (
        entity_registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{MX1_KEY}_subchannel_split"
        )
        is None
    )


async def test_calendar(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    calendar_id = entity_id(hass, "calendar", f"{NHK_KEY}_schedule")

    state = hass.states.get(calendar_id)
    assert state.state == STATE_ON
    assert state.attributes["message"] == "ニュース"

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar_id,
            "start_date_time": at(10),
            "end_date_time": at(15),
        },
        blocking=True,
        return_response=True,
    )
    summaries = [event["summary"] for event in response[calendar_id]["events"]]
    assert summaries == [
        "ニュース",
        "天気",
        "[ＮＨＫ総合２・東京] 国会中継",
        "ドキュメント",
    ]

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar_id,
            "start_date_time": at(13, 30),
            "end_date_time": at(15),
        },
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in response[calendar_id]["events"]] == ["ドキュメント"]


async def test_broadcast_without_programs(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, programs={**PROGRAMS, NHK: []})
    await setup_integration(hass, config_entry)

    current = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_current_program"))
    assert current.state == STATE_UNKNOWN
    calendar = hass.states.get(entity_id(hass, "calendar", f"{NHK_KEY}_schedule"))
    # NHK2 still airs its own program at 12:30, but nothing is on air now
    assert calendar.state == STATE_OFF
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_broadcast_entities.py -v`
Expected: FAIL（`AssertionError: ..._current_program`）

- [ ] **Step 3: entity.py に放送の基底クラスを追加する**

`custom_components/mirakurun/entity.py` の import に次を加える:

```python
from datetime import datetime

from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .coordinator import BroadcastSchedule, ProgramCoordinator
from .programs import next_transition
```

（`from .coordinator import MirakurunConfigEntry, StatusCoordinator` は `from .coordinator import BroadcastSchedule, MirakurunConfigEntry, ProgramCoordinator, StatusCoordinator` にまとめる。`from homeassistant.core import callback` は `from homeassistant.core import CALLBACK_TYPE, callback` にまとめる。）

ファイル末尾に次を追加する:

```python
class MirakurunBroadcastEntity(MirakurunEntity[ProgramCoordinator]):
    """An entity of a broadcast device that refreshes at program boundaries."""

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self.broadcast = broadcast
        self._attr_unique_id = f"{broadcast_identifier(entry, broadcast.main.id)}_{key}"
        self._attr_device_info = broadcast_device_info(entry, broadcast)
        self._unsub_transition: CALLBACK_TYPE | None = None

    @property
    def schedule(self) -> BroadcastSchedule | None:
        """Return the latest schedules for this broadcast."""
        return self.coordinator.data.get(self.broadcast.main.id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_transition()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_transition()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_transition()
        super()._handle_coordinator_update()

    @callback
    def _cancel_transition(self) -> None:
        if self._unsub_transition is not None:
            self._unsub_transition()
            self._unsub_transition = None

    @callback
    def _schedule_transition(self) -> None:
        self._cancel_transition()
        schedule = self.schedule
        if schedule is None:
            return
        now = dt_util.utcnow()
        candidates = [
            t
            for t in (
                next_transition(schedule.main, now),
                *(next_transition(sub, now) for _, sub in schedule.subs),
            )
            if t is not None
        ]
        if candidates:
            self._unsub_transition = async_track_point_in_utc_time(
                self.hass, self._handle_transition, min(candidates)
            )

    @callback
    def _handle_transition(self, _now: datetime) -> None:
        self._unsub_transition = None
        self._schedule_transition()
        self.async_write_ha_state()
```

- [ ] **Step 4: sensor.py に番組センサーを追加する**

`custom_components/mirakurun/sensor.py` の import に次を加える:

```python
from homeassistant.util import dt as dt_util

from .broadcast import Broadcast
from .coordinator import ProgramCoordinator
from .entity import MirakurunBroadcastEntity
from .programs import ScheduledProgram, current_program, genre_key, next_program
```

（既存の `from .coordinator import ...` と `from .entity import ...` に統合する。）

`async_setup_entry` の末尾に次を追加する:

```python
    programs = entry.runtime_data.programs
    async_add_entities(
        entity
        for broadcast in entry.runtime_data.broadcasts
        for entity in (
            MirakurunCurrentProgramSensor(programs, entry, broadcast),
            MirakurunNextProgramSensor(programs, entry, broadcast),
        )
    )
```

ファイル末尾に次を追加する:

```python
class MirakurunCurrentProgramSensor(MirakurunBroadcastEntity, SensorEntity):
    """The program currently on air on the main service."""

    _attr_translation_key = "current_program"

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
    ) -> None:
        super().__init__(coordinator, entry, broadcast, "current_program")

    def _item(self) -> ScheduledProgram | None:
        schedule = self.schedule
        if schedule is None:
            return None
        return current_program(schedule.main, dt_util.utcnow())

    @property
    def native_value(self) -> str | None:
        item = self._item()
        return item.program.name if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        item = self._item()
        if item is None:
            return None
        return {
            "start": item.start.isoformat(),
            "end": item.end.isoformat(),
            "description": item.program.description,
            "genre": genre_key(item.program.genre_lv1),
        }


class MirakurunNextProgramSensor(MirakurunBroadcastEntity, SensorEntity):
    """The next program on the main service."""

    _attr_translation_key = "next_program"

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
    ) -> None:
        super().__init__(coordinator, entry, broadcast, "next_program")

    def _item(self) -> ScheduledProgram | None:
        schedule = self.schedule
        if schedule is None:
            return None
        return next_program(schedule.main, dt_util.utcnow())

    @property
    def native_value(self) -> str | None:
        item = self._item()
        return item.program.name if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        item = self._item()
        if item is None:
            return None
        return {
            "start": item.start.isoformat(),
            "genre": genre_key(item.program.genre_lv1),
        }
```

- [ ] **Step 5: binary_sensor.py に別番組センサーを追加する**

`custom_components/mirakurun/binary_sensor.py` の import に次を加える:

```python
from typing import Any

from homeassistant.util import dt as dt_util

from .broadcast import Broadcast, SubchannelSplit, detect_splits
from .coordinator import ProgramCoordinator
from .entity import MirakurunBroadcastEntity
```

（既存の `from .coordinator import ...` と `from .entity import ...` に統合する。）

`async_setup_entry` の末尾に次を追加する:

```python
    programs = entry.runtime_data.programs
    async_add_entities(
        MirakurunSubchannelSplitBinarySensor(programs, entry, broadcast)
        for broadcast in entry.runtime_data.broadcasts
        if broadcast.subs
    )
```

ファイル末尾に次を追加する:

```python
class MirakurunSubchannelSplitBinarySensor(MirakurunBroadcastEntity, BinarySensorEntity):
    """On while a subchannel airs something other than the main service."""

    _attr_translation_key = "subchannel_split"

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
    ) -> None:
        super().__init__(coordinator, entry, broadcast, "subchannel_split")

    def _splits(self) -> list[SubchannelSplit]:
        schedule = self.schedule
        if schedule is None:
            return []
        return detect_splits(
            self.broadcast.main, schedule.main, schedule.subs, dt_util.utcnow()
        )

    @property
    def is_on(self) -> bool:
        return bool(self._splits())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "subchannels": [
                {
                    "service": split.service.name,
                    "program": split.program.program.name,
                    "end": split.program.end.isoformat(),
                }
                for split in self._splits()
            ]
        }
```

- [ ] **Step 6: calendar.py を実装し、プラットフォームを登録する**

`custom_components/mirakurun/calendar.py`:

```python
"""Program guide calendars for Mirakurun."""

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .broadcast import Broadcast, distinct_sub_programs
from .coordinator import MirakurunConfigEntry, ProgramCoordinator
from .entity import MirakurunBroadcastEntity
from .programs import ScheduledProgram

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up program guide calendars."""
    programs = entry.runtime_data.programs
    async_add_entities(
        MirakurunCalendar(programs, entry, broadcast)
        for broadcast in entry.runtime_data.broadcasts
    )


def _to_event(item: ScheduledProgram, prefix: str | None) -> CalendarEvent:
    summary = item.program.name or ""
    if prefix:
        summary = f"[{prefix}] {summary}"
    return CalendarEvent(
        start=item.start,
        end=item.end,
        summary=summary,
        description=item.program.description,
        uid=str(item.program.id),
    )


class MirakurunCalendar(MirakurunBroadcastEntity, CalendarEntity):
    """Programs of the main service plus distinct subchannel programs."""

    _attr_translation_key = "schedule"

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
    ) -> None:
        super().__init__(coordinator, entry, broadcast, "schedule")

    def _items(self) -> list[tuple[ScheduledProgram, str | None]]:
        schedule = self.schedule
        if schedule is None:
            return []
        items: list[tuple[ScheduledProgram, str | None]] = [
            (item, None) for item in schedule.main
        ]
        for service, sub_schedule in schedule.subs:
            items.extend(
                (item, service.name)
                for item in distinct_sub_programs(
                    self.broadcast.main, schedule.main, sub_schedule
                )
            )
        return sorted(items, key=lambda pair: pair[0].start)

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        return next(
            (_to_event(item, prefix) for item, prefix in self._items() if item.end > now),
            None,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            _to_event(item, prefix)
            for item, prefix in self._items()
            if item.end > start_date and item.start < end_date
        ]
```

`custom_components/mirakurun/__init__.py` の `PLATFORMS` を次に置き換える:

```python
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]
```

- [ ] **Step 7: テストが通ることを確かめる**

Run: `uv run pytest -v`
Expected: すべて PASS

`test_broadcast_without_programs` の補足: NHK のメインが空でも NHK2 の「国会中継」（12:30〜）は別番組としてカレンダーに入る。12:00 時点では何も放送中でないため `off` になる。`event` は「次の予定」を返すので属性 `message` は「[ＮＨＫ総合２・東京] 国会中継」になる（テストでは状態のみ確認）。

- [ ] **Step 8: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy`

```bash
git add -A
git commit -m "feat: add program sensors, subchannel split sensor and calendar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 更新エンティティ、診断、不要デバイスの削除

**Files:**
- Create: `custom_components/mirakurun/update.py`, `custom_components/mirakurun/diagnostics.py`
- Modify: `custom_components/mirakurun/__init__.py`（`PLATFORMS`、不要デバイスの削除、`async_remove_config_entry_device`）
- Test: `tests/test_update.py`, `tests/test_diagnostics.py`, `tests/test_init.py`（追記）

**Interfaces:**
- Consumes: `coordinator.VersionCoordinator`、`coordinator.MirakurunRuntimeData`、`entity.server_identifier`、`entity.tuner_identifier`、`entity.broadcast_identifier`、`entity.server_device_info`、`entity.MirakurunEntity`、`const.RELEASE_URL`
- Produces:
  - `update.MirakurunUpdate`（`unique_id` は `f"{entry_id}_server_update"`）
  - `diagnostics.async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]`
  - `__init__.async_remove_config_entry_device(hass, entry, device_entry) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_update.py`:

```python
"""Tests for the Mirakurun update entity."""

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import RELEASE_URL

from .common import ENTRY_ID, entity_id, mock_mirakurun, setup_integration


async def test_update_entity(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    state = hass.states.get(entity_id(hass, "update", f"{ENTRY_ID}_server_update"))
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "4.0.0-beta.18"
    assert state.attributes["latest_version"] == "4.1.5"
    assert state.attributes["release_url"] == RELEASE_URL


async def test_update_entity_unavailable_without_version(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock, fail_version=True)
    await setup_integration(hass, config_entry)
    state = hass.states.get(entity_id(hass, "update", f"{ENTRY_ID}_server_update"))
    assert state.state == STATE_UNAVAILABLE
```

`tests/test_diagnostics.py`:

```python
"""Tests for Mirakurun diagnostics."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import setup_integration


async def test_diagnostics(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["entry"]["data"] == {"url": "**REDACTED**"}
    assert result["entry"]["options"]["broadcasts"] == [
        "3273601024",
        "3239123608",
        "3239123610",
    ]
    assert result["status"]["version"] == "4.0.0-beta.18"
    assert len(result["tuners"]) == 3
    assert result["version"] == {"current": "4.0.0-beta.18", "latest": "4.1.5"}
    assert result["programs"]["3273601024"] == {"main": 3, "subs": {"3273601025": 3}}
```

`tests/test_init.py` の末尾に追記する（import に `from homeassistant.helpers import device_registry as dr` と `from custom_components.mirakurun.const import DOMAIN` と `from .common import ENTRY_ID` を加える）:

```python
async def test_stale_broadcast_device_removed(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    stale = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_broadcast_999")},
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(stale.id) is None
    assert device_registry.async_get_device(
        identifiers={(DOMAIN, f"{ENTRY_ID}_broadcast_3273601024")}
    )


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    from custom_components.mirakurun import async_remove_config_entry_device

    await setup_integration(hass, config_entry)
    tuner = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{ENTRY_ID}_tuner_14")}
    )
    assert not await async_remove_config_entry_device(hass, config_entry, tuner)

    gone = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_tuner_99")},
    )
    assert await async_remove_config_entry_device(hass, config_entry, gone)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_update.py tests/test_diagnostics.py tests/test_init.py -v`
Expected: FAIL（`No module named 'custom_components.mirakurun.diagnostics'` など）

- [ ] **Step 3: update.py を実装する**

`custom_components/mirakurun/update.py`:

```python
"""Update entity reporting new Mirakurun releases."""

from homeassistant.components.update import UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import RELEASE_URL
from .coordinator import MirakurunConfigEntry, VersionCoordinator
from .entity import MirakurunEntity, server_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the update entity."""
    async_add_entities([MirakurunUpdate(entry.runtime_data.version, entry)])


class MirakurunUpdate(MirakurunEntity[VersionCoordinator], UpdateEntity):
    """Shows whether a newer Mirakurun is available. Installing is not supported."""

    _attr_name = None
    _attr_title = "Mirakurun"
    _attr_release_url = RELEASE_URL

    def __init__(
        self, coordinator: VersionCoordinator, entry: MirakurunConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_server_update"
        self._attr_device_info = server_device_info(entry)

    @property
    def installed_version(self) -> str | None:
        data = self.coordinator.data
        return data.current if data is not None else None

    @property
    def latest_version(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.latest or data.current
```

- [ ] **Step 4: diagnostics.py を実装する**

`custom_components/mirakurun/diagnostics.py`:

```python
"""Diagnostics for Mirakurun."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from .const import CONF_BROADCASTS, CONF_PROGRAM_INTERVAL, CONF_STATUS_INTERVAL
from .coordinator import MirakurunConfigEntry

TO_REDACT = {CONF_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MirakurunConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    status = data.status.data
    version = data.version.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": {
                key: entry.options.get(key)
                for key in (CONF_BROADCASTS, CONF_STATUS_INTERVAL, CONF_PROGRAM_INTERVAL)
            },
        },
        "status": asdict(status.status),
        "tuners": [asdict(tuner) for tuner in status.tuners],
        "version": asdict(version) if version is not None else None,
        "programs": {
            str(main_id): {
                "main": len(schedule.main),
                "subs": {str(service.id): len(sub) for service, sub in schedule.subs},
            }
            for main_id, schedule in data.programs.data.items()
        },
    }
```

- [ ] **Step 5: __init__.py に不要デバイスの削除を加え、プラットフォームを登録する**

`custom_components/mirakurun/__init__.py` を次の内容に置き換える:

```python
"""The Mirakurun integration."""

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MirakurunClient, MirakurunError
from .broadcast import resolve_broadcasts
from .const import CONF_BROADCAST_MAP, CONF_BROADCASTS, DOMAIN
from .coordinator import (
    MirakurunConfigEntry,
    MirakurunRuntimeData,
    ProgramCoordinator,
    StatusCoordinator,
    VersionCoordinator,
)
from .entity import broadcast_identifier, server_identifier, tuner_identifier

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Set up Mirakurun from a config entry."""
    client = MirakurunClient(async_get_clientsession(hass), entry.data[CONF_URL])
    try:
        services = await client.get_services()
    except MirakurunError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    broadcasts = tuple(
        resolve_broadcasts(
            entry.options.get(CONF_BROADCAST_MAP, {}),
            entry.options.get(CONF_BROADCASTS, []),
            services,
        )
    )
    status = StatusCoordinator(hass, entry, client)
    programs = ProgramCoordinator(hass, entry, client, broadcasts)
    version = VersionCoordinator(hass, entry, client)

    await status.async_config_entry_first_refresh()
    await programs.async_config_entry_first_refresh()
    # The latest version comes from npm via Mirakurun and may be unreachable;
    # it must not block setup.
    await version.async_refresh()

    entry.runtime_data = MirakurunRuntimeData(
        client, broadcasts, status, programs, version
    )
    _async_remove_stale_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MirakurunConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices that no longer exist on the server."""
    return not device_entry.identifiers & _current_identifiers(entry)


def _current_identifiers(entry: MirakurunConfigEntry) -> set[tuple[str, str]]:
    data = entry.runtime_data
    identifiers = {(DOMAIN, server_identifier(entry))}
    identifiers.update(
        (DOMAIN, tuner_identifier(entry, tuner.index))
        for tuner in data.status.data.tuners
    )
    identifiers.update(
        (DOMAIN, broadcast_identifier(entry, broadcast.main.id))
        for broadcast in data.broadcasts
    )
    return identifiers


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: MirakurunConfigEntry
) -> None:
    current = _current_identifiers(entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & current:
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
```

- [ ] **Step 6: テストが通ることを確かめる**

Run: `uv run pytest -v`
Expected: すべて PASS

- [ ] **Step 7: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy`

```bash
git add -A
git commit -m "feat: add update entity, diagnostics and stale device cleanup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 品質の記録、README、CI

**Files:**
- Create: `custom_components/mirakurun/quality_scale.yaml`, `README.md`, `.github/workflows/validate.yml`
- Test: 全体（カバレッジ 95% 以上）

**Interfaces:**
- Consumes: これまでのすべて
- Produces: 配布可能なリポジトリ

- [ ] **Step 1: カバレッジを測る**

Run: `uv run pytest --cov=custom_components.mirakurun --cov-report=term-missing`
Expected: 合計 95% 以上。下回る場合は、未到達の行を通るテストを該当タスクのテストファイルに追加してから進む。

- [ ] **Step 2: quality_scale.yaml を作る**

`custom_components/mirakurun/quality_scale.yaml`:

```yaml
rules:
  # Bronze
  action-setup:
    status: exempt
    comment: The integration does not register actions.
  appropriate-polling: done
  brands:
    status: todo
    comment: Submit icons to home-assistant/brands before requesting HACS default inclusion.
  common-modules: done
  config-flow-test-coverage: done
  config-flow: done
  dependency-transparency: done
  docs-actions:
    status: exempt
    comment: The integration does not register actions.
  docs-high-level-description: done
  docs-installation-instructions: done
  docs-removal-instructions: done
  entity-event-setup: done
  entity-unique-id: done
  has-entity-name: done
  runtime-data: done
  test-before-configure: done
  test-before-setup: done
  unique-config-entry: done

  # Silver
  action-exceptions:
    status: exempt
    comment: The integration does not register actions.
  config-entry-unloading: done
  docs-configuration-parameters: done
  docs-installation-parameters: done
  entity-unavailable: done
  integration-owner: done
  log-when-unavailable: done
  parallel-updates: done
  reauthentication-flow:
    status: exempt
    comment: Mirakurun has no authentication.
  test-coverage: done

  # Gold
  devices: done
  diagnostics: done
  discovery-update-info:
    status: exempt
    comment: Mirakurun does not announce itself on the network.
  discovery:
    status: exempt
    comment: Mirakurun does not announce itself on the network.
  docs-data-update: done
  docs-examples: done
  docs-known-limitations: done
  docs-supported-devices: done
  docs-supported-functions: done
  docs-troubleshooting: done
  docs-use-cases: done
  dynamic-devices: done
  entity-category: done
  entity-device-class: done
  entity-disabled-by-default: done
  entity-translations: done
  exception-translations: done
  icon-translations: done
  reconfiguration-flow: done
  repair-issues:
    status: exempt
    comment: There are no user-repairable issues.
  stale-devices: done

  # Platinum
  async-dependency: done
  inject-websession: done
  strict-typing: done
```

- [ ] **Step 3: README.md を作る**

`README.md`:

````markdown
# Mirakurun for Home Assistant

A Home Assistant custom integration for [Mirakurun](https://github.com/Chinachu/Mirakurun), the DVR tuner server for Japanese TV.
It shows tuner usage, server health and the program guide, and tells you when a new Mirakurun release is available.
It does not record or schedule recordings; use it alongside EPGStation for that.

## Features

- **Server**: tuners in use, free tuners, tuner streams, tuner respawns, error counters, whether the program guide is being gathered, and a Mirakurun update entity.
- **Tuners**: one device per tuner with its state (`free`, `in_use`, `disabled`, `fault`), the channel being received, the highest priority user, and a fault sensor. Tuners added later appear without restarting.
- **Broadcasts**: one device per selected broadcast with the current and next program, a calendar of the program guide, and a sensor that turns on while a subchannel airs a different program.

### Multichannel broadcasts

Services on the same physical channel are grouped into broadcasts.
A subchannel that shares at least half of the main service's upcoming programs (for example NHK General 2) belongs to the main broadcast; its own programs show up in the calendar as `[service name] program` and turn on the "Subchannel airing a different program" sensor.
A subchannel that usually airs its own programs (for example TOKYO MX2) becomes a broadcast of its own.
The grouping is decided when the integration is set up and each time the options are opened.

## Installation

1. In HACS, open the menu, choose **Custom repositories**, and add `https://github.com/hinaloe/ha-mirakurun` with the type **Integration**.
2. Install **Mirakurun** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and choose **Mirakurun**.

## Configuration

| Field | Description |
|---|---|
| URL | The Mirakurun server, for example `http://192.168.1.10:40772`. A trailing `/api` is accepted and removed. |

### Options

| Option | Default | Description |
|---|---|---|
| Broadcasts | All terrestrial broadcasts | Broadcasts that get program guide entities. |
| Tuner and status polling interval | 30 s (10–300 s) | How often tuner usage and server status are polled. |
| Program guide polling interval | 30 min (5–180 min) | How often programs are refreshed. Current and next programs switch exactly at program boundaries regardless of this interval. |

Home Assistant core integrations do not offer polling interval options.
This integration does, because Mirakurun runs on your local network and polling it is cheap.

The URL can be changed later with **Reconfigure**.

## Data updates

The integration polls Mirakurun's REST API: `/api/status` and `/api/tuners` at the status interval, `/api/programs` for the selected broadcasts at the program interval, and `/api/version` every 12 hours.
It never opens a stream, so it does not occupy tuners or interfere with recordings.

## Examples

Entity IDs are generated from service names and differ between installations; replace them with the ones shown on your device pages.

Notify when a subchannel starts airing something different:

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.nhk_general_1_tokyo_subchannel_airing_a_different_program
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            {{ state_attr(trigger.entity_id, 'subchannels')[0].service }}:
            {{ state_attr(trigger.entity_id, 'subchannels')[0].program }}
```

Do something when a program starts:

```yaml
automation:
  - triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.tokyo_mx1_schedule
    conditions:
      - condition: template
        value_template: "{{ 'アニメ' in trigger.calendar_event.summary }}"
    actions:
      - action: light.turn_off
        target:
          area_id: living_room
```

## Supported versions

Tested with Mirakurun 4.x. Mirakurun 3.x is not tested.

## Known limitations

- Live streaming is not supported yet.
- Recording and reservations are out of scope; use EPGStation.
- Mirakurun has no authentication. Connecting through an authenticating reverse proxy is not supported.
- The update entity only reports new releases; it cannot install them.
- If Mirakurun cannot reach npm, the update entity becomes unavailable. Everything else keeps working.

## Troubleshooting

- **Cannot connect**: open `http://<host>:40772/api/version` from the Home Assistant host. If it does not respond, check the address, port and firewall.
- **A broadcast is missing**: open the options; the list is rebuilt from Mirakurun's current services each time.
- **A subchannel is grouped the wrong way**: open and save the options to re-run the grouping.
- Download diagnostics from the integration page when reporting an issue.

## Removal

Go to **Settings → Devices & services → Mirakurun**, open the menu and choose **Delete**. Then remove the repository from HACS if you no longer need it.
````

- [ ] **Step 4: CI を作る**

`.github/workflows/validate.yml`:

```yaml
name: Validate

on:
  push:
    branches: [main]
  pull_request:

jobs:
  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: home-assistant/actions/hassfest@master

  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: hacs/action@main
        with:
          category: integration
          ignore: brands

  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: jdx/mise-action@v2
      - run: uv sync --locked
      - run: mise run lint
      - run: mise run test -- --cov-fail-under=95
```

- [ ] **Step 5: 全体を検証する**

Run: `mise run lint && mise run test -- --cov-fail-under=95`
Expected: すべて成功

- [ ] **Step 6: コミットする**

```bash
git add -A
git commit -m "docs: add README, quality scale tracking and CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 仕様との対応

| 仕様の節 | タスク |
|---|---|
| 3.1 API クライアント | 1 |
| 3.2 コーディネーター、取得間隔 | 4、5（オプション） |
| 3.3 設定フロー | 5 |
| 3.4 サーバー・チューナー | 6、8（更新） |
| 3.4 放送 | 7 |
| 3.5 マルチチャンネル | 3、5、7 |
| 3.6 番組データ | 2 |
| 3.7 エラー処理 | 4（`ConfigEntryNotReady`、`UpdateFailed`、部分失敗）、6（利用不可） |
| 3.8 診断 | 8 |
| 6 品質の目標 | 9 |
| 7 テスト、CI | 1〜9 |

仕様からの意図的な差分は次のとおり。仕様書も合わせて更新済み。

- 翻訳は `strings.json` ではなく `translations/{en,ja}.json`（カスタムインテグレーションの仕組みによる）。
- エンティティの検証はスナップショットではなく明示的な assert（計画の中で期待値を読めるようにするため）。
- サービス一覧の取得はセットアップ時とオプション画面だけ（放送の判定を固定する方針と揃えるため）。
- チューナーの状態の `unavailable` は `disabled` とする（HA の予約状態 `unavailable` と衝突するため）。
- バージョンの初回取得失敗はセットアップを止めない（`latest` は Mirakurun が npm に問い合わせるため）。
