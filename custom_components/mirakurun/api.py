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
