"""Search validation shared by the CLI, MCP tools, and query functions."""

from __future__ import annotations

import math


class QueryError(ValueError):
    """Invalid query input, reported as CLI exit code 2."""


def parse_near(value: str) -> tuple[float, float]:
    try:
        lat, lon = value.split(",")
        near = (float(lat.strip()), float(lon.strip()))
    except ValueError as error:
        raise QueryError('expected "lat,lon" with numeric coordinates') from error
    _validate_coordinates(near)
    return near


def _validate_coordinates(near: tuple[float, float]) -> None:
    lat, lon = near
    if not math.isfinite(lat) or not -90 <= lat <= 90:
        raise QueryError("latitude must be finite and between -90 and 90")
    if not math.isfinite(lon) or not -180 <= lon <= 180:
        raise QueryError("longitude must be finite and between -180 and 180")


def validate_search(
    near: tuple[float, float] | None,
    radius_km: float,
    limit: int = 0,
) -> None:
    if near is not None:
        _validate_coordinates(near)
    if not math.isfinite(radius_km) or radius_km <= 0:
        raise QueryError("radius must be finite and greater than zero")
    if limit < 0:
        raise QueryError("limit must not be negative; use 0 for no limit")


def validate_nonnegative(**values: float) -> None:
    for name, value in values.items():
        if not math.isfinite(value) or value < 0:
            raise QueryError(f"{name} must be finite and nonnegative")


def validate_download(timeout: int, max_age: int = 0) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise QueryError("timeout must be finite and greater than zero")
    validate_nonnegative(max_age=max_age)
