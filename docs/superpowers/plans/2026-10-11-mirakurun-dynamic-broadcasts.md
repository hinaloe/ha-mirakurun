# Mirakurun 放送の自動追従 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 放送を個別に選ぶ方式をやめ、選んだ種別の放送を Mirakurun に追従して自動で追加・削除する。

**Architecture:** `broadcast.py` に判定のヒステリシスと種別での絞り込みを加える。新しい `ServiceCoordinator` が放送一覧を定期的に取り直し、判定結果を `Store` に保存する。`ProgramCoordinator` と各プラットフォームはその一覧に追従し、増えた放送のエンティティを追加し、消えた放送のデバイスを削除する。旧形式のオプションは `async_migrate_entry` で移行する。

**Tech Stack:** Python 3.14、Home Assistant 2026.10（`probatio`、`homeassistant.helpers.storage.Store`）、pytest-homeassistant-custom-component 0.13.371、mise、uv、ruff、mypy（strict）。

**Spec:** `docs/superpowers/specs/2026-10-11-mirakurun-integration-design.md`（3.2〜3.5 節、7 節。コミット `ab0dd24`）

## Global Constraints

- ブランチは `feat/dynamic-broadcasts`（`feat/phase1` の上）。
- ファイルの変更には Edit ツール（新規ファイルや全体の書き換えには Write ツール）を使う。`python3 - <<EOF`、`sed -i`、`cat > file` での書き換えはしない。`ruff format` など、ツール本来の書き換えは可。
- `api.py`、`models.py`、`programs.py`、`broadcast.py` は `homeassistant` を import しない。
- スキーマは `probatio` を使う（HA 2026.10 本体と同じ）。デバイスの親子は `via_device_id`。デバイスの検索は `async_get_device_by_identifier(identifier, config_entry_id)`。
- オプションのキー: `channel_types`（list[str]、既定 `["GR"]`）、`status_interval`（秒、10〜300、既定 30）、`program_interval`（分、5〜180、既定 30）、`service_interval`（時間、1〜168、既定 24）。
- 判定のしきい値: 初めて見るサービスは共有率 0.5 以上で従属。前回従属なら 0.4 以上で従属のまま。前回独立なら 0.6 以上で従属に変わる。
- 判定結果は `Store`（キー `mirakurun.{entry_id}.classification`、`{サービスの id 文字列: 従属なら true}`）に保存する。
- エントリは `VERSION = 1`、`MINOR_VERSION = 2`。minor version 1 のエントリは移行する。
- 各コミットの前に `uv run ruff format . && uv run ruff check --fix . && uv run mypy` と `uv run pytest` を実行する。
- コミットの Co-Authored-By はハーネスが示す自分のモデル名を使う。署名に失敗したら回避せず報告する。
- テストで時刻を進めたあとは `await hass.async_block_till_done(wait_background_tasks=True)` で待つ。

## Review Focus

1. **Mirakurun が一時的に空のサービス一覧を返す（チャンネルスキャン中など）**: 放送のデバイスをすべて消してはならない。更新の失敗として扱い、前回の一覧を保つ。→ Task 2 `test_empty_service_list_keeps_broadcasts`。
2. **一度消えた放送が、のちの更新で戻ってくる**: エンティティが再び作られること。→ Task 3 `test_broadcast_returns_after_removal`。
3. **利用者が無効化した放送のデバイス**: 一覧の更新で消されず、無効のまま残ること。→ Task 3 `test_disabled_broadcast_survives_refresh`。
4. **ある物理チャンネルの判定だけ失敗する**: 前回の判定を使い、従属サブチャンネルが独立の放送に化けないこと。→ Task 1 `test_discover_uses_previous_on_failure`、Task 2 `test_saved_classification_used_when_channel_fails`。
5. **取得間隔のキーを持たない古いエントリの移行**: 既定値で補われること。→ Task 2 `test_migrates_legacy_options_without_intervals`。

---

## ファイル構成

| パス | このプランでの変更 |
|---|---|
| `custom_components/mirakurun/broadcast.py` | ヒステリシス、`Discovery`、`discover()`、`classification_from_option_map()` を追加（Task 1）。旧オプション用の関数を削除（Task 2） |
| `custom_components/mirakurun/const.py` | 新しいオプションのキーと既定値、`default_options()`（Task 2） |
| `custom_components/mirakurun/identifiers.py` | 新規。デバイス識別子の関数を `entity.py` から移す（Task 2） |
| `custom_components/mirakurun/store.py` | 新規。判定結果の保存（Task 2） |
| `custom_components/mirakurun/coordinator.py` | `ServiceCoordinator` を追加し、`ProgramCoordinator` を追従させる（Task 2、Task 3） |
| `custom_components/mirakurun/__init__.py` | セットアップの組み替え、移行、保存領域の削除（Task 2）。一覧の更新への追従（Task 3） |
| `custom_components/mirakurun/config_flow.py` | 種別の選択と一覧の更新間隔（Task 2） |
| `custom_components/mirakurun/entity.py` | 識別子の import 元の変更（Task 2）。放送エンティティの動的追加（Task 3） |
| `custom_components/mirakurun/sensor.py`、`binary_sensor.py`、`calendar.py` | 放送一覧の参照先の変更（Task 2）。動的追加（Task 3） |
| `custom_components/mirakurun/diagnostics.py` | オプションのキーの変更（Task 2） |
| `custom_components/mirakurun/translations/{en,ja}.json` | オプションと種別の文言（Task 2） |
| `README.md` | 利用者向けの説明（Task 4） |

---

### Task 1: 判定のヒステリシスと種別の絞り込み

**Files:**
- Modify: `custom_components/mirakurun/broadcast.py`
- Test: `tests/test_broadcast.py`

**Interfaces:**
- Consumes: `models.Service`、`models.Program`、`programs.build_schedule`、`api.MirakurunClient`、`api.MirakurunError`
- Produces:
  - 定数 `SPLIT_THRESHOLD = 0.4`、`JOIN_THRESHOLD = 0.6`（`SHARED_RATIO_THRESHOLD = 0.5` は既存）
  - 型 `Classification = dict[int, bool]`（サービスの Mirakurun `id` → 従属なら True）
  - `Discovery(broadcasts: tuple[Broadcast, ...], classification: Classification, channel_types: frozenset[str])`（frozen dataclass）
  - `classify_channel(services, main_programs, now, previous: Mapping[int, bool] | None = None) -> list[Broadcast]`（既存の呼び出しはそのまま動く）
  - `async discover(client, now, channel_types: Collection[str], previous: Mapping[int, bool]) -> Discovery`
  - `classification_from_option_map(option_map: Mapping[str, Sequence[int]]) -> Classification`
  - 既存の `discover_broadcasts`、`to_option_map`、`default_selection`、`resolve_broadcasts` はこのタスクでは残す（Task 2 で削除）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_broadcast.py` の import を次のように変える（`timedelta`、`pytest`、新しい名前を追加）:

```python
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.api import MirakurunClient
from custom_components.mirakurun.broadcast import (
    Broadcast,
    classification_from_option_map,
    classify_channel,
    default_selection,
    detect_splits,
    discover,
    discover_broadcasts,
    distinct_sub_programs,
    group_by_channel,
    resolve_broadcasts,
    to_option_map,
)
```

（`.common` からの import は既存のまま。）

ファイル末尾に次を追加する:

```python
def _ratio_programs(total: int, shared: int) -> list[Program]:
    """Main programs of which the first ``shared`` list NHK2 as shared."""
    return [
        Program.from_dict(
            make_program(
                NHK,
                i + 1,
                NOW + timedelta(minutes=10 * i),
                10,
                f"番組{i}",
                shared=(1025,) if i < shared else (),
            )
        )
        for i in range(total)
    ]


@pytest.mark.parametrize(
    ("shared", "previous", "dependent"),
    [
        (10, None, True),  # 0.50, first classification
        (9, None, False),  # 0.45, first classification
        (8, True, True),  # 0.40, stays dependent
        (7, True, False),  # 0.35, splits off
        (11, False, False),  # 0.55, stays independent
        (12, False, True),  # 0.60, joins
    ],
)
def test_classify_hysteresis(shared: int, previous: bool | None, dependent: bool) -> None:
    prior = {} if previous is None else {NHK2_SVC.id: previous}
    result = classify_channel(
        [NHK_SVC, NHK2_SVC], _ratio_programs(20, shared), NOW, prior
    )
    if dependent:
        assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]
    else:
        assert result == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]


def test_classify_failure_keeps_previous() -> None:
    result = classify_channel([NHK_SVC, NHK2_SVC], None, NOW, {NHK2_SVC.id: True})
    assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]


async def test_discover_filters_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {})
    assert result.broadcasts == (
        Broadcast(NHK_SVC, (NHK2_SVC,)),
        Broadcast(MX1_SVC),
        Broadcast(MX2_SVC),
    )
    assert result.classification == {NHK2_SVC.id: True, MX2_SVC.id: False}
    assert result.channel_types == frozenset({"GR", "CS"})


async def test_discover_without_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, [], {})
    assert result.broadcasts == ()
    assert result.classification == {}
    assert result.channel_types == frozenset({"GR", "CS"})


async def test_discover_uses_previous_on_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_mirakurun(aioclient_mock, fail_programs={NHK})
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {NHK2_SVC.id: True})
    assert result.broadcasts[0] == Broadcast(NHK_SVC, (NHK2_SVC,))
    assert result.classification[NHK2_SVC.id] is True


def test_classification_from_option_map() -> None:
    assert classification_from_option_map(
        {"3273601024": [3273601025], "3239123608": []}
    ) == {3273601025: True}
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_broadcast.py -q`
Expected: FAIL（`ImportError: cannot import name 'classification_from_option_map'`）

- [ ] **Step 3: 実装する**

`custom_components/mirakurun/broadcast.py` を次のように変更する。

import を次に置き換える:

```python
import asyncio
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
```

`SHARED_RATIO_THRESHOLD = 0.5` の直後に追加する:

```python
# Hysteresis for services classified before: a dependent subchannel splits off
# below SPLIT_THRESHOLD, an independent service joins at JOIN_THRESHOLD.
SPLIT_THRESHOLD = 0.4
JOIN_THRESHOLD = 0.6

type Classification = dict[int, bool]
```

`SubchannelSplit` クラスの直後に追加する:

```python
@dataclass(frozen=True, slots=True)
class Discovery:
    """Broadcasts of the selected channel types and how services were grouped."""

    broadcasts: tuple[Broadcast, ...]
    classification: Classification
    channel_types: frozenset[str]
```

既存の `classify_channel` を次に置き換える:

```python
def _is_dependent(ratio: float, previous: bool | None) -> bool:
    if previous is None:
        return ratio >= SHARED_RATIO_THRESHOLD
    if previous:
        return ratio >= SPLIT_THRESHOLD
    return ratio >= JOIN_THRESHOLD


def classify_channel(
    services: Sequence[Service],
    main_programs: Sequence[Program] | None,
    now: datetime,
    previous: Mapping[int, bool] | None = None,
) -> list[Broadcast]:
    """Split one physical channel into broadcasts by how often programs are shared.

    ``previous`` maps service IDs to their last classification; it adds
    hysteresis and is used as-is when the main service has no upcoming programs.
    """
    prior = previous or {}
    main, *others = services
    upcoming = [
        item.program for item in build_schedule(main_programs or ()) if item.end > now
    ]
    subs: list[Service] = []
    independents: list[Service] = []
    for service in others:
        if upcoming:
            shared = sum(
                1 for p in upcoming if service.service_id in p.shared_service_ids
            )
            dependent = _is_dependent(shared / len(upcoming), prior.get(service.id))
        else:
            dependent = prior.get(service.id, False)
        if dependent:
            subs.append(service)
        else:
            independents.append(service)
    return [Broadcast(main, tuple(subs)), *(Broadcast(s) for s in independents)]
```

既存の `discover_broadcasts` の直後に追加する:

```python
async def discover(
    client: MirakurunClient,
    now: datetime,
    channel_types: Collection[str],
    previous: Mapping[int, bool],
) -> Discovery:
    """Fetch services and classify the physical channels of the given types."""
    services = await client.get_services()
    groups = group_by_channel(services)
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def classify(group: list[Service]) -> list[Broadcast]:
        main = group[0]
        programs: list[Program] | None
        async with semaphore:
            try:
                programs = await client.get_programs(main.network_id, main.service_id)
            except MirakurunError:
                programs = None
        return classify_channel(group, programs, now, previous)

    selected = [g for g in groups if g[0].channel.type in channel_types]
    results = await asyncio.gather(*(classify(group) for group in selected))
    classification: Classification = {}
    for group, broadcasts in zip(selected, results, strict=True):
        dependent = {s.id for b in broadcasts for s in b.subs}
        classification.update({s.id: s.id in dependent for s in group[1:]})
    return Discovery(
        broadcasts=tuple(b for result in results for b in result),
        classification=classification,
        channel_types=frozenset(g[0].channel.type for g in groups),
    )


def classification_from_option_map(
    option_map: Mapping[str, Sequence[int]],
) -> Classification:
    """Seed a classification from legacy options: listed subchannels were dependent."""
    return {int(sid): True for subs in option_map.values() for sid in subs}
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run pytest tests/test_broadcast.py -q`
Expected: すべて PASS（既存のテストも含む）

- [ ] **Step 5: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy && uv run pytest -q`

```bash
git add custom_components/mirakurun/broadcast.py tests/test_broadcast.py
git commit -m "feat: add classification hysteresis and type-filtered discovery"
```

---

### Task 2: 放送一覧のコーディネーターと種別のオプション

**Files:**
- Create: `custom_components/mirakurun/identifiers.py`, `custom_components/mirakurun/store.py`
- Modify: `custom_components/mirakurun/const.py`, `broadcast.py`, `coordinator.py`, `__init__.py`, `config_flow.py`, `entity.py`, `sensor.py`, `binary_sensor.py`, `calendar.py`, `diagnostics.py`, `translations/en.json`, `translations/ja.json`
- Test: `tests/common.py`, `tests/test_init.py`, `tests/test_config_flow.py`, `tests/test_broadcast.py`, `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: Task 1 の `Discovery`、`discover()`、`classification_from_option_map()`、`Classification`
- Produces:
  - `const`: `CONF_CHANNEL_TYPES = "channel_types"`、`CONF_SERVICE_INTERVAL = "service_interval"`、`DEFAULT_CHANNEL_TYPES = ("GR",)`、`DEFAULT_SERVICE_INTERVAL = 24`、`MIN_SERVICE_INTERVAL = 1`、`MAX_SERVICE_INTERVAL = 168`、`default_options() -> dict[str, Any]`
  - `identifiers.server_identifier(entry) -> str`、`tuner_identifier(entry, index: int) -> str`、`broadcast_identifier(entry, main_id: int) -> str`（`entry` は `ConfigEntry[Any]`）
  - `store.ClassificationStore(hass, entry_id: str)`: `async_load() -> Classification`、`async_save(classification: Mapping[int, bool]) -> None`、`async_remove() -> None`
  - `coordinator.ServiceCoordinator(hass, entry, client, store)`（`DataUpdateCoordinator[Discovery]`、`always_update=False`）
  - `coordinator.ProgramCoordinator(hass, entry, client, services: ServiceCoordinator)`（属性 `services`）
  - `coordinator.MirakurunRuntimeData(client, services, status, programs, version, server_device_id="")`（`broadcasts` フィールドは廃止）
  - `__init__.async_migrate_entry`、`__init__.async_remove_entry`
  - `ConfigFlow.MINOR_VERSION = 2`
  - `tests/common.py`: `DEFAULT_OPTIONS`（新形式）、`LEGACY_OPTIONS`、`create_entry(options=None, minor_version=2)`、`mock_mirakurun(..., services=None)`

- [ ] **Step 1: テストの共通部品を新形式にする**

`tests/common.py` の const の import を次に置き換える:

```python
from custom_components.mirakurun.const import (
    CONF_BROADCAST_MAP,
    CONF_BROADCASTS,
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
)
```

`DEFAULT_OPTIONS` の定義を次に置き換える:

```python
DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_CHANNEL_TYPES: ["GR"],
    CONF_STATUS_INTERVAL: 30,
    CONF_PROGRAM_INTERVAL: 30,
    CONF_SERVICE_INTERVAL: 24,
}

# Options written by phase 1 (config entry minor version 1).
LEGACY_OPTIONS: dict[str, Any] = {
    CONF_BROADCAST_MAP: {
        "3273601024": [3273601025],
        "3239123608": [],
        "3239123610": [],
    },
    CONF_BROADCASTS: ["3273601024", "3239123608", "3239123610"],
    CONF_STATUS_INTERVAL: 45,
    CONF_PROGRAM_INTERVAL: 30,
}
```

`mock_mirakurun` の引数に `services` を加え（`tuners` の直後）、`services` の登録行を置き換える:

```python
    services: Sequence[Mapping[str, Any]] | None = None,
```

```python
    register(
        "services",
        list(services) if services is not None else load_fixture("services.json"),
        fail_services,
    )
```

`create_entry` を次に置き換える:

```python
def create_entry(
    options: Mapping[str, Any] | None = None, minor_version: int = 2
) -> MockConfigEntry:
    """Create a config entry for the mocked server."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mirakurun",
        data={CONF_URL: BASE_URL},
        options=dict(options if options is not None else DEFAULT_OPTIONS),
        entry_id=ENTRY_ID,
        minor_version=minor_version,
    )
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_init.py`:
- import に `from custom_components.mirakurun.store import ClassificationStore` と、`.common` から `DEFAULT_OPTIONS`、`LEGACY_OPTIONS`、`MX1`、`create_entry` を加える。`custom_components.mirakurun.const` の import に `CONF_PROGRAM_INTERVAL`、`CONF_STATUS_INTERVAL` を加える。
- `test_setup_and_unload` の 2 行を次に置き換える:

```python
    broadcasts = data.services.data.broadcasts
    assert [b.main.service_id for b in broadcasts] == [1024, 23608, 23610]
    assert [s.service_id for s in broadcasts[0].subs] == [1025]
```

- ファイル末尾に追加する:

```python
async def test_classification_is_saved(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert await ClassificationStore(hass, ENTRY_ID).async_load() == {
        3273601025: True,
        3239123610: False,
    }


async def test_saved_classification_used_when_channel_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await ClassificationStore(hass, ENTRY_ID).async_save({3239123610: True})
    mock_mirakurun(aioclient_mock, fail_programs={MX1})
    await setup_integration(hass, config_entry)
    broadcasts = config_entry.runtime_data.services.data.broadcasts
    mx1 = next(b for b in broadcasts if b.main.service_id == 23608)
    assert [s.service_id for s in mx1.subs] == [23610]


async def test_empty_service_list_keeps_broadcasts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=[])
    await services.async_refresh()

    assert not services.last_update_success
    assert len(services.data.broadcasts) == 3


async def test_migrates_legacy_options(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    entry = create_entry(LEGACY_OPTIONS, minor_version=1)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2
    assert entry.options == {**DEFAULT_OPTIONS, CONF_STATUS_INTERVAL: 45}
    stored = await ClassificationStore(hass, ENTRY_ID).async_load()
    assert stored[3273601025] is True


async def test_migrates_legacy_options_without_intervals(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    legacy = {
        key: value
        for key, value in LEGACY_OPTIONS.items()
        if key not in (CONF_STATUS_INTERVAL, CONF_PROGRAM_INTERVAL)
    }
    entry = create_entry(legacy, minor_version=1)
    await setup_integration(hass, entry)
    assert entry.options == DEFAULT_OPTIONS


async def test_remove_entry_removes_classification(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await ClassificationStore(hass, ENTRY_ID).async_load() == {}
```

`tests/test_config_flow.py`:
- const の import を `CONF_CHANNEL_TYPES`、`CONF_PROGRAM_INTERVAL`、`CONF_SERVICE_INTERVAL`、`CONF_STATUS_INTERVAL`、`DOMAIN` にする（`CONF_BROADCAST_MAP`、`CONF_BROADCASTS` を削除）。
- `test_options_flow` と `test_options_flow_drops_vanished_selection` を次の 2 つに置き換える（`test_options_flow_cannot_connect` はそのまま）:

```python
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
            CONF_CHANNEL_TYPES: ["CS"],
            CONF_STATUS_INTERVAL: 60,
            CONF_PROGRAM_INTERVAL: 10,
            CONF_SERVICE_INTERVAL: 6,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_CHANNEL_TYPES: ["CS"],
        CONF_STATUS_INTERVAL: 60,
        CONF_PROGRAM_INTERVAL: 10,
        CONF_SERVICE_INTERVAL: 6,
    }
    broadcasts = config_entry.runtime_data.services.data.broadcasts
    assert [b.main.service_id for b in broadcasts] == [55, 218]


async def test_options_flow_offers_server_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = create_entry({**DEFAULT_OPTIONS, CONF_CHANNEL_TYPES: ["GR", "SKY"]})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    key = next(k for k in schema if k == CONF_CHANNEL_TYPES)
    assert schema[key].config["options"] == ["CS", "GR"]
    assert key.default() == ["GR"]
```

（`.common` の import に `create_entry` を加える。）

`tests/test_diagnostics.py` の options の assert を次に置き換える:

```python
    assert result["entry"]["options"]["channel_types"] == ["GR"]
    assert result["broadcasts"] == 3
```

`tests/test_broadcast.py` から、`test_discover_broadcasts`、`test_discover_broadcasts_with_failed_channel`、`test_option_round_trip`、`test_resolve_broadcasts_skips_missing_services` の 4 つのテストを削除し、import から `default_selection`、`discover_broadcasts`、`resolve_broadcasts`、`to_option_map` を削除する。

- [ ] **Step 3: テストが失敗することを確かめる**

Run: `uv run pytest -q`
Expected: FAIL（`ImportError: cannot import name 'CONF_CHANNEL_TYPES'` など）

- [ ] **Step 4: const.py、identifiers.py、store.py を作る**

`custom_components/mirakurun/const.py` を次の内容にする:

```python
"""Constants for the Mirakurun integration."""

from datetime import timedelta
from typing import Any, Final

DOMAIN: Final = "mirakurun"
MANUFACTURER: Final = "Chinachu Project"

CONF_CHANNEL_TYPES: Final = "channel_types"
CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_PROGRAM_INTERVAL: Final = "program_interval"
CONF_SERVICE_INTERVAL: Final = "service_interval"

# Legacy options of config entry minor version 1, read only by the migration.
CONF_BROADCASTS: Final = "broadcasts"
CONF_BROADCAST_MAP: Final = "broadcast_map"

DEFAULT_CHANNEL_TYPES: Final = ("GR",)
DEFAULT_STATUS_INTERVAL: Final = 30
MIN_STATUS_INTERVAL: Final = 10
MAX_STATUS_INTERVAL: Final = 300
DEFAULT_PROGRAM_INTERVAL: Final = 30
MIN_PROGRAM_INTERVAL: Final = 5
MAX_PROGRAM_INTERVAL: Final = 180
DEFAULT_SERVICE_INTERVAL: Final = 24
MIN_SERVICE_INTERVAL: Final = 1
MAX_SERVICE_INTERVAL: Final = 168
VERSION_INTERVAL: Final = timedelta(hours=12)
VERSION_RETRY_INTERVAL: Final = timedelta(minutes=30)

RELEASE_URL: Final = "https://github.com/Chinachu/Mirakurun/releases"


def default_options() -> dict[str, Any]:
    """Return the options of a new config entry."""
    return {
        CONF_CHANNEL_TYPES: list(DEFAULT_CHANNEL_TYPES),
        CONF_STATUS_INTERVAL: DEFAULT_STATUS_INTERVAL,
        CONF_PROGRAM_INTERVAL: DEFAULT_PROGRAM_INTERVAL,
        CONF_SERVICE_INTERVAL: DEFAULT_SERVICE_INTERVAL,
    }
```

`custom_components/mirakurun/identifiers.py`:

```python
"""Device identifiers for Mirakurun."""

from typing import Any

from homeassistant.config_entries import ConfigEntry


def server_identifier(entry: ConfigEntry[Any]) -> str:
    """Return the device identifier of the server."""
    return entry.entry_id


def tuner_identifier(entry: ConfigEntry[Any], index: int) -> str:
    """Return the device identifier of a tuner."""
    return f"{entry.entry_id}_tuner_{index}"


def broadcast_identifier(entry: ConfigEntry[Any], main_id: int) -> str:
    """Return the device identifier of a broadcast."""
    return f"{entry.entry_id}_broadcast_{main_id}"
```

`custom_components/mirakurun/store.py`:

```python
"""Persistent storage of how services were grouped into broadcasts."""

from collections.abc import Mapping

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .broadcast import Classification
from .const import DOMAIN

STORAGE_VERSION = 1


class ClassificationStore:
    """Stores, per config entry, whether each subchannel depends on its main."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, bool]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.classification"
        )

    async def async_load(self) -> Classification:
        data = await self._store.async_load()
        return {int(key): bool(value) for key, value in (data or {}).items()}

    async def async_save(self, classification: Mapping[int, bool]) -> None:
        await self._store.async_save(
            {str(key): value for key, value in classification.items()}
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()
```

- [ ] **Step 5: 旧オプション用の関数を broadcast.py から削除する**

`custom_components/mirakurun/broadcast.py` から `discover_broadcasts`、`to_option_map`、`default_selection`、`resolve_broadcasts` の 4 つの関数を削除する。

- [ ] **Step 6: coordinator.py を変更する**

import を次のように変える:

```python
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MirakurunClient, MirakurunError
from .broadcast import Broadcast, Classification, Discovery, discover
from .const import (
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_CHANNEL_TYPES,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_SERVICE_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    VERSION_INTERVAL,
    VERSION_RETRY_INTERVAL,
)
from .models import Service, Status, Tuner, Version
from .programs import Schedule, build_schedule
from .store import ClassificationStore
```

`StatusCoordinator` の直後に追加する:

```python
class ServiceCoordinator(DataUpdateCoordinator[Discovery]):
    """Refreshes the broadcast list and regroups subchannels."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MirakurunConfigEntry,
        client: MirakurunClient,
        store: ClassificationStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_services",
            update_interval=timedelta(
                hours=entry.options.get(CONF_SERVICE_INTERVAL, DEFAULT_SERVICE_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client
        self._store = store
        self._classification: Classification | None = None

    async def _async_update_data(self) -> Discovery:
        if self._classification is None:
            self._classification = await self._store.async_load()
        channel_types = self.config_entry.options.get(
            CONF_CHANNEL_TYPES, list(DEFAULT_CHANNEL_TYPES)
        )
        try:
            discovery = await discover(
                self.client, dt_util.utcnow(), channel_types, self._classification
            )
        except MirakurunError as err:
            raise _update_failed(err) from err
        if not discovery.channel_types:
            # An empty service list (e.g. during a channel scan) must not wipe
            # every broadcast device.
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="no_services"
            )
        merged = {**self._classification, **discovery.classification}
        if merged != self._classification:
            self._classification = merged
            await self._store.async_save(merged)
        return discovery
```

`ProgramCoordinator` を次のように変える:
- コンストラクタの引数 `broadcasts: tuple[Broadcast, ...]` を `services: ServiceCoordinator` に変え、`self.broadcasts = broadcasts` を `self.services = services` に変える。
- `_async_update_data` の先頭行と、その後の `services` という名前のローカル変数をすべて次のように置き換える:

```python
    async def _async_update_data(self) -> dict[int, BroadcastSchedule]:
        broadcasts = self.services.data.broadcasts
        targets = [s for b in broadcasts for s in (b.main, *b.subs)]
        results = await asyncio.gather(
            *(self.client.get_programs(s.network_id, s.service_id) for s in targets),
            return_exceptions=True,
        )
```

  （以降の `services` は `targets` に、`for b in self.broadcasts` は `for b in broadcasts` にする。ロジックは変えない。）

`MirakurunRuntimeData` を次に置き換える:

```python
@dataclass(slots=True)
class MirakurunRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: MirakurunClient
    services: ServiceCoordinator
    status: StatusCoordinator
    programs: ProgramCoordinator
    version: VersionCoordinator
    server_device_id: str = ""
```

`Broadcast` が `BroadcastSchedule` 以外で使われなくなっても import は残す（`BroadcastSchedule` が使う）。

- [ ] **Step 7: __init__.py を書き換える**

`custom_components/mirakurun/__init__.py` を次の内容にする:

```python
"""The Mirakurun integration."""

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MirakurunClient
from .broadcast import classification_from_option_map
from .const import (
    CONF_BROADCAST_MAP,
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
    default_options,
)
from .coordinator import (
    MirakurunConfigEntry,
    MirakurunRuntimeData,
    ProgramCoordinator,
    ServiceCoordinator,
    StatusCoordinator,
    VersionCoordinator,
)
from .entity import server_device_info
from .identifiers import broadcast_identifier, server_identifier, tuner_identifier
from .store import ClassificationStore

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Set up Mirakurun from a config entry."""
    client = MirakurunClient(async_get_clientsession(hass), entry.data[CONF_URL])
    services = ServiceCoordinator(
        hass, entry, client, ClassificationStore(hass, entry.entry_id)
    )
    status = StatusCoordinator(hass, entry, client)
    programs = ProgramCoordinator(hass, entry, client, services)
    version = VersionCoordinator(hass, entry, client)

    await services.async_config_entry_first_refresh()
    await status.async_config_entry_first_refresh()
    await programs.async_config_entry_first_refresh()
    # The latest version comes from npm via Mirakurun and may be unreachable;
    # it must not block setup.
    await version.async_refresh()

    entry.runtime_data = MirakurunRuntimeData(
        client, services, status, programs, version
    )
    server_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(entry)
    )
    entry.runtime_data.server_device_id = server_device.id
    _async_remove_stale_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Migrate per-broadcast options (minor version 1) to broadcast types."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        legacy = dict(entry.options)
        options = default_options()
        for key in (CONF_STATUS_INTERVAL, CONF_PROGRAM_INTERVAL):
            if key in legacy:
                options[key] = legacy[key]
        await ClassificationStore(hass, entry.entry_id).async_save(
            classification_from_option_map(legacy.get(CONF_BROADCAST_MAP, {}))
        )
        hass.config_entries.async_update_entry(
            entry, options=options, minor_version=2
        )
    return True


async def async_remove_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> None:
    """Remove stored data of a deleted config entry."""
    await ClassificationStore(hass, entry.entry_id).async_remove()


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
        for broadcast in data.services.data.broadcasts
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

- [ ] **Step 8: entity.py とプラットフォームの参照先を変える**

`custom_components/mirakurun/entity.py`:
- `server_identifier`、`tuner_identifier`、`broadcast_identifier` の 3 つの関数定義を削除し、代わりに `from .identifiers import broadcast_identifier, server_identifier, tuner_identifier` を import に加える。

`custom_components/mirakurun/sensor.py`、`binary_sensor.py`、`calendar.py`:
- `entry.runtime_data.broadcasts` を `entry.runtime_data.services.data.broadcasts` に置き換える（各ファイル 1 か所）。

`custom_components/mirakurun/diagnostics.py`:
- const の import を `CONF_CHANNEL_TYPES`、`CONF_PROGRAM_INTERVAL`、`CONF_SERVICE_INTERVAL`、`CONF_STATUS_INTERVAL` にする。
- options のキーのタプルを `(CONF_CHANNEL_TYPES, CONF_STATUS_INTERVAL, CONF_PROGRAM_INTERVAL, CONF_SERVICE_INTERVAL)` にする。
- 返す dict の `"version"` の直前に `"broadcasts": len(data.services.data.broadcasts),` を加える。

- [ ] **Step 9: config_flow.py を書き換える**

`custom_components/mirakurun/config_flow.py` を次の内容にする:

```python
"""Config flow for Mirakurun."""

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
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import probatio
from yarl import URL

from .api import MirakurunClient, MirakurunError, normalize_url
from .broadcast import TV_SERVICE_TYPE
from .const import (
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_CHANNEL_TYPES,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_SERVICE_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MAX_PROGRAM_INTERVAL,
    MAX_SERVICE_INTERVAL,
    MAX_STATUS_INTERVAL,
    MIN_PROGRAM_INTERVAL,
    MIN_SERVICE_INTERVAL,
    MIN_STATUS_INTERVAL,
    default_options,
)
from .coordinator import MirakurunConfigEntry

_LOGGER = logging.getLogger(__name__)

URL_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)


def _title(url: str) -> str:
    return f"Mirakurun ({URL(url).host})"


def _interval_selector(minimum: int, maximum: int, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


class MirakurunConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mirakurun."""

    VERSION = 1
    MINOR_VERSION = 2

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
            # /api/version shells out to npm and can fail where /api/status works
            await client.get_status()
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
                    return self.async_create_entry(
                        title=_title(url),
                        data={CONF_URL: url},
                        options=default_options(),
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
    """Select broadcast types and polling intervals."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form with the channel types the server has."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_CHANNEL_TYPES: list(user_input[CONF_CHANNEL_TYPES]),
                    CONF_STATUS_INTERVAL: int(user_input[CONF_STATUS_INTERVAL]),
                    CONF_PROGRAM_INTERVAL: int(user_input[CONF_PROGRAM_INTERVAL]),
                    CONF_SERVICE_INTERVAL: int(user_input[CONF_SERVICE_INTERVAL]),
                }
            )

        client = MirakurunClient(
            async_get_clientsession(self.hass), self.config_entry.data[CONF_URL]
        )
        try:
            services = await client.get_services()
        except MirakurunError:
            return self.async_abort(reason="cannot_connect")

        available = sorted(
            {s.channel.type for s in services if s.type == TV_SERVICE_TYPE}
        )
        options = self.config_entry.options
        selected = [
            channel_type
            for channel_type in options.get(CONF_CHANNEL_TYPES, DEFAULT_CHANNEL_TYPES)
            if channel_type in available
        ]
        schema = probatio.Schema(
            {
                probatio.Required(CONF_CHANNEL_TYPES, default=selected): SelectSelector(
                    SelectSelectorConfig(
                        options=available,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_CHANNEL_TYPES,
                    )
                ),
                probatio.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): _interval_selector(MIN_STATUS_INTERVAL, MAX_STATUS_INTERVAL, "s"),
                probatio.Required(
                    CONF_PROGRAM_INTERVAL,
                    default=options.get(
                        CONF_PROGRAM_INTERVAL, DEFAULT_PROGRAM_INTERVAL
                    ),
                ): _interval_selector(MIN_PROGRAM_INTERVAL, MAX_PROGRAM_INTERVAL, "min"),
                probatio.Required(
                    CONF_SERVICE_INTERVAL,
                    default=options.get(
                        CONF_SERVICE_INTERVAL, DEFAULT_SERVICE_INTERVAL
                    ),
                ): _interval_selector(MIN_SERVICE_INTERVAL, MAX_SERVICE_INTERVAL, "h"),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
```

- [ ] **Step 10: 翻訳を変える**

`translations/en.json` の `"options"` の `"step"` → `"init"` の `"data"` と `"data_description"` を次に置き換える:

```json
        "data": {
          "channel_types": "Broadcast types",
          "status_interval": "Tuner and status polling interval",
          "program_interval": "Program guide polling interval",
          "service_interval": "Broadcast list refresh interval"
        },
        "data_description": {
          "channel_types": "Broadcasts of these types get program guide entities. Broadcasts added to or removed from Mirakurun are followed automatically; disable a broadcast's device to hide it.",
          "status_interval": "How often to poll tuner usage and server status.",
          "program_interval": "How often to refresh the program guide.",
          "service_interval": "How often to refresh the broadcast list and regroup subchannels."
        }
```

同じファイルの最上位（`"options"` と `"entity"` の間）に追加する:

```json
  "selector": {
    "channel_types": {
      "options": {
        "GR": "Terrestrial (GR)",
        "BS": "BS",
        "CS": "110° CS (CS)",
        "SKY": "SKY PerfecTV! Premium Service (SKY)"
      }
    }
  },
```

`"exceptions"` に追加する:

```json
    "no_services": {"message": "Mirakurun returned no TV services."}
```

`translations/ja.json` も同じ位置に次を入れる:

```json
        "data": {
          "channel_types": "放送の種別",
          "status_interval": "チューナーと状態の取得間隔",
          "program_interval": "番組表の取得間隔",
          "service_interval": "放送一覧の更新間隔"
        },
        "data_description": {
          "channel_types": "この種別の放送に番組情報のエンティティを作ります。Mirakurun で増えた放送や消えた放送には自動で追従します。要らない放送はデバイスを無効化して隠してください。",
          "status_interval": "チューナーの使用状況とサーバーの状態を取得する間隔です。",
          "program_interval": "番組表を取得し直す間隔です。",
          "service_interval": "放送一覧を取り直し、サブチャンネルのまとめ方を判定し直す間隔です。"
        }
```

```json
  "selector": {
    "channel_types": {
      "options": {
        "GR": "地上波（GR）",
        "BS": "BS",
        "CS": "110度 CS（CS）",
        "SKY": "スカパー！プレミアムサービス（SKY）"
      }
    }
  },
```

```json
    "no_services": {"message": "Mirakurun からテレビのサービスが返されませんでした。"}
```

- [ ] **Step 11: テストが通ることを確かめる**

Run: `uv run pytest -q`
Expected: すべて PASS。`config_flow.py` のカバレッジを `uv run pytest tests/test_config_flow.py --cov=custom_components.mirakurun.config_flow --cov-report=term-missing -q` で確かめ、100% でなければ不足の分岐を通るテストを `tests/test_config_flow.py` に加える。

- [ ] **Step 12: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: select broadcast types and refresh the broadcast list"
```

---

### Task 3: 放送の増減への追従

**Files:**
- Modify: `custom_components/mirakurun/entity.py`, `coordinator.py`, `__init__.py`, `sensor.py`, `binary_sensor.py`, `calendar.py`
- Test: `tests/test_dynamic_broadcasts.py`（新規）

**Interfaces:**
- Consumes: Task 2 の `ServiceCoordinator`、`MirakurunRuntimeData.services`、`identifiers.broadcast_identifier`
- Produces:
  - `entity.async_add_broadcast_entities(entry, factory: Callable[[Broadcast], Iterable[Entity]], async_add_entities) -> None`
  - `MirakurunBroadcastEntity.available`（スケジュールがなければ False）
  - `ProgramCoordinator` は無効化されたデバイスの放送の番組を取得しない
  - 放送一覧が変わると、不要デバイスを削除し、番組を取得し直す

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_dynamic_broadcasts.py`:

```python
"""Tests for following broadcasts added to and removed from Mirakurun."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import DOMAIN

from .common import (
    ENTRY_ID,
    PROGRAMS,
    at,
    entity_id,
    load_fixture,
    make_program,
    mock_mirakurun,
    setup_integration,
)

FUJI = (32741, 1056)
FUJI_SERVICE: dict[str, Any] = {
    "id": 3274101056,
    "serviceId": 1056,
    "networkId": 32741,
    "name": "フジテレビ",
    "type": 1,
    "remoteControlKeyId": 8,
    "channel": {"type": "GR", "channel": "21"},
    "hasLogoData": True,
}
FUJI_PROGRAMS = {**PROGRAMS, FUJI: [make_program(FUJI, 500, at(11), 120, "ドラマ")]}
FUJI_KEY = f"{ENTRY_ID}_broadcast_3274101056"
MX2_KEY = f"{ENTRY_ID}_broadcast_3239123610"
NHK_KEY = f"{ENTRY_ID}_broadcast_3273601024"


def _services(
    *, add: list[dict[str, Any]] | None = None, drop: Collection[int] = ()
) -> list[dict[str, Any]]:
    services = [s for s in load_fixture("services.json") if s["id"] not in drop]
    return services + (add or [])


async def _refresh_services(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.services.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


def _program_fetches(aioclient_mock: AiohttpClientMocker, service_id: int) -> int:
    return sum(
        1
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if url.path == "/api/programs" and url.query.get("serviceId") == str(service_id)
    )


async def test_new_broadcast_added_without_reload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(add=[FUJI_SERVICE]), programs=FUJI_PROGRAMS)
    await _refresh_services(hass, config_entry)

    state = hass.states.get(entity_id(hass, "sensor", f"{FUJI_KEY}_current_program"))
    assert state is not None
    assert state.state == "ドラマ"


async def test_removed_broadcast_device_removed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(drop={3239123610}))
    await _refresh_services(hass, config_entry)

    assert device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID) is None
    assert entity_registry.async_get_entity_id("sensor", DOMAIN, f"{MX2_KEY}_current_program") is None


async def test_broadcast_returns_after_removal(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(drop={3239123610}))
    await _refresh_services(hass, config_entry)
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_services(hass, config_entry)

    state = hass.states.get(entity_id(hass, "sensor", f"{MX2_KEY}_current_program"))
    assert state is not None
    assert state.state == "MX2特番"


async def test_disabled_broadcast_survives_refresh(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
    assert device is not None
    device_registry.async_update_device(device.id, disabled_by=dr.DeviceEntryDisabler.USER)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(add=[FUJI_SERVICE]), programs=FUJI_PROGRAMS)
    await _refresh_services(hass, config_entry)

    device = device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
    assert device is not None
    assert device.disabled_by is dr.DeviceEntryDisabler.USER


async def test_disabled_broadcast_programs_not_fetched(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
    assert device is not None
    device_registry.async_update_device(device.id, disabled_by=dr.DeviceEntryDisabler.USER)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await hass.config_entries.async_reload(ENTRY_ID)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _program_fetches(aioclient_mock, 23610) == 0
    assert 3239123610 not in config_entry.runtime_data.programs.data


async def test_split_sensor_added_when_subchannel_appears(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_mirakurun(aioclient_mock, services=_services(drop={3273601025}))
    await setup_integration(hass, config_entry)
    assert entity_registry.async_get_entity_id("binary_sensor", DOMAIN, f"{NHK_KEY}_subchannel_split") is None

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_services(hass, config_entry)

    assert hass.states.get(entity_id(hass, "binary_sensor", f"{NHK_KEY}_subchannel_split")) is not None
```

（ファイル先頭の import に `from collections.abc import Collection` を加える。）

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest tests/test_dynamic_broadcasts.py -q`
Expected: FAIL（新しい放送のエンティティが見つからない、消えた放送のデバイスが残る、など）

- [ ] **Step 3: entity.py に動的追加を加える**

`custom_components/mirakurun/entity.py` の `MirakurunBroadcastEntity` に、`schedule` プロパティの直後へ追加する:

```python
    @property
    def available(self) -> bool:
        """Return whether programs are known for this broadcast."""
        return super().available and self.schedule is not None
```

`async_add_tuner_entities` の直後に追加する:

```python
def async_add_broadcast_entities(
    entry: MirakurunConfigEntry,
    factory: Callable[[Broadcast], Iterable[Entity]],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add entities for current broadcasts and for broadcasts found later.

    A broadcast counts as handled once the factory returns entities for it, so a
    factory that skips a broadcast (one without subchannels, say) is asked again
    on the next refresh. Broadcasts that disappear are forgotten, so they get
    entities again if they come back.
    """
    services = entry.runtime_data.services
    handled: set[int] = set()

    @callback
    def add_new_broadcasts() -> None:
        broadcasts = services.data.broadcasts
        handled.intersection_update(b.main.id for b in broadcasts)
        entities: list[Entity] = []
        for broadcast in broadcasts:
            if broadcast.main.id in handled:
                continue
            created = list(factory(broadcast))
            if created:
                handled.add(broadcast.main.id)
                entities.extend(created)
        if entities:
            async_add_entities(entities)

    add_new_broadcasts()
    entry.async_on_unload(services.async_add_listener(add_new_broadcasts))
```

- [ ] **Step 4: プラットフォームを動的追加に切り替える**

`custom_components/mirakurun/sensor.py` の `async_setup_entry` で、`programs = entry.runtime_data.programs` 以降の `async_add_entities(...)` を次に置き換え、`.entity` の import に `async_add_broadcast_entities` を加える:

```python
    programs = entry.runtime_data.programs
    async_add_broadcast_entities(
        entry,
        lambda broadcast: [
            MirakurunCurrentProgramSensor(programs, entry, broadcast),
            MirakurunNextProgramSensor(programs, entry, broadcast),
        ],
        async_add_entities,
    )
```

`custom_components/mirakurun/binary_sensor.py` も同様に置き換える:

```python
    programs = entry.runtime_data.programs
    async_add_broadcast_entities(
        entry,
        lambda broadcast: (
            [MirakurunSubchannelSplitBinarySensor(programs, entry, broadcast)]
            if broadcast.subs
            else []
        ),
        async_add_entities,
    )
```

`custom_components/mirakurun/calendar.py` も同様に置き換える:

```python
    programs = entry.runtime_data.programs
    async_add_broadcast_entities(
        entry,
        lambda broadcast: [MirakurunCalendar(programs, entry, broadcast)],
        async_add_entities,
    )
```

- [ ] **Step 5: 無効化されたデバイスの放送を番組の取得から外す**

`custom_components/mirakurun/coordinator.py`:
- import に `from homeassistant.helpers import device_registry as dr` と `from .identifiers import broadcast_identifier` を加える。
- `ProgramCoordinator` に次のメソッドを加え、`_async_update_data` の `broadcasts = self.services.data.broadcasts` を `broadcasts = self._target_broadcasts()` に置き換える:

```python
    def _target_broadcasts(self) -> list[Broadcast]:
        """Return broadcasts whose device the user has not disabled."""
        registry = dr.async_get(self.hass)
        targets: list[Broadcast] = []
        for broadcast in self.services.data.broadcasts:
            device = registry.async_get_device_by_identifier(
                (DOMAIN, broadcast_identifier(self.config_entry, broadcast.main.id)),
                self.config_entry.entry_id,
            )
            if device is None or not device.disabled:
                targets.append(broadcast)
        return targets
```

- [ ] **Step 6: 一覧の更新に追従する**

`custom_components/mirakurun/__init__.py` の `async_setup_entry` で、`_async_remove_stale_devices(hass, entry)` の直後に次を加える:

```python
    @callback
    def _async_broadcasts_changed() -> None:
        _async_remove_stale_devices(hass, entry)
        entry.async_create_background_task(
            hass, programs.async_request_refresh(), f"{DOMAIN}_program_refresh"
        )

    entry.async_on_unload(services.async_add_listener(_async_broadcasts_changed))
```

- [ ] **Step 7: テストが通ることを確かめる**

Run: `uv run pytest -q`
Expected: すべて PASS

- [ ] **Step 8: コミットする**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run mypy && uv run pytest -q`

```bash
git add -A
git commit -m "feat: follow broadcasts added to and removed from Mirakurun"
```

---

### Task 4: README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1〜3 の挙動
- Produces: 利用者向けの説明

- [ ] **Step 1: README を直す**

`README.md` の次の箇所を Edit で直す。

`## Features` の **Broadcasts** の行を次に置き換える:

```markdown
- **Broadcasts**: one device per broadcast of the selected types, with the current and next program, a calendar of the program guide, and a sensor that turns on while a subchannel airs a different program. Broadcasts added to or removed from Mirakurun are followed automatically; disable a broadcast's device to hide it.
```

`### Multichannel broadcasts` 節の最後の文（`The grouping is decided when the integration is set up and each time the options are opened.`）を次に置き換える:

```markdown
The grouping is refreshed with the broadcast list (every 24 hours by default) and remembered across restarts. To keep borderline subchannels stable, a dependent subchannel only splits off below 40% shared programs, and an independent one only joins at 60% or more.
```

`### Options` の表を次に置き換える:

```markdown
| Option | Default | Description |
|---|---|---|
| Broadcast types | Terrestrial (GR) | Types of broadcasts that get program guide entities. Only the types your Mirakurun has are offered (GR, BS, CS, SKY). |
| Tuner and status polling interval | 30 s (10–300 s) | How often tuner usage and server status are polled. |
| Program guide polling interval | 30 min (5–180 min) | How often programs are refreshed. Current and next programs switch exactly at program boundaries regardless of this interval. |
| Broadcast list refresh interval | 24 h (1–168 h) | How often the broadcast list is refreshed and subchannels are regrouped. |
```

`## Data updates` 節の最初の段落を次に置き換える:

```markdown
The integration polls Mirakurun's REST API: `/api/status` and `/api/tuners` at the status interval, `/api/programs` for broadcasts whose device is enabled at the program interval, `/api/services` plus the main service's programs of each physical channel of the selected types at the broadcast list interval, and `/api/version` every 12 hours.
```

`## Troubleshooting` の **A broadcast is missing** と **A subchannel is grouped the wrong way** の 2 行を次に置き換える:

```markdown
- **A broadcast is missing**: check that its type is selected in the options and that its device is not disabled. New broadcasts appear at the next broadcast list refresh; reload the integration to refresh now.
- **A subchannel is grouped the wrong way**: the grouping only changes when the share of simulcast programs clearly crosses the thresholds above. Reload the integration after the program guide has been updated.
```

- [ ] **Step 2: 検証してコミットする**

Run: `mise run lint && mise run test -- --cov-fail-under=95`
Expected: すべて成功

```bash
git add README.md
git commit -m "docs: describe broadcast types and automatic following"
```
