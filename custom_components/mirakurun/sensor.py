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
from .entity import (
    MirakurunServerEntity,
    MirakurunTunerEntity,
    async_add_tuner_entities,
)
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
