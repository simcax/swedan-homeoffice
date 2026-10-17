"""Settings screen — API base URL configuration (task 12.5).

``build_settings_view`` assembles a small settings screen holding an
``ft.TextField`` bound to the backend API base URL plus a Save button. The URL
is persisted to the device's key-value store so it survives app restarts
(Requirement 11.1).

Flet 1.0.2 note — the storage API
---------------------------------
In Flet 1.0.2 the old synchronous ``page.client_storage`` property is gone.
Persistent key-value storage is now the :class:`flet.SharedPreferences`
*service*, whose methods are **async**::

    await page.shared_preferences.set(key, value) -> bool
    await page.shared_preferences.get(key)        -> str | int | float | bool | list[str] | None

To keep this module usable with that async service *and* unit-testable without
starting the Flet runtime, the persistence logic lives in two tiny coroutine
helpers — :func:`load_api_base_url` and :func:`save_api_base_url` — that accept
any object exposing the async ``get`` / ``set`` methods (the real
``SharedPreferences`` service in production, a mock in tests). The view builder
itself is a thin Flet wrapper that reads an already-loaded value into the field
and schedules :func:`save_api_base_url` via ``page.run_task`` on Save.

Requirements: 11.1
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlparse

import flet as ft

# Storage key the API base URL is persisted under (Requirement 11.1).
API_BASE_URL_KEY = "API_BASE_URL"

# Fallback used when nothing has been stored yet.
DEFAULT_API_BASE_URL = "http://127.0.0.1:8080"


class KeyValueStorage(Protocol):
    """The async subset of Flet 1.0.2's ``SharedPreferences`` we rely on.

    Declaring a :class:`~typing.Protocol` keeps the persistence helpers
    decoupled from the concrete Flet service so tests can pass a lightweight
    async mock exposing just ``get`` and ``set``.
    """

    async def get(self, key: str) -> object: ...

    async def set(self, key: str, value: object) -> bool: ...


# ---------------------------------------------------------------------------
# persistence helpers (pure of the Flet runtime, so directly testable)
# ---------------------------------------------------------------------------


async def load_api_base_url(
    storage: KeyValueStorage,
    default: str = DEFAULT_API_BASE_URL,
) -> str:
    """Return the stored API base URL, or ``default`` when none is set.

    Reads :data:`API_BASE_URL_KEY` from ``storage`` using the async
    ``SharedPreferences.get`` API. A missing key (``None``) or an empty/blank
    stored value falls back to ``default`` so callers always receive a usable,
    non-empty URL.

    Args:
        storage: An object exposing the async ``get`` method (the Flet
            ``SharedPreferences`` service in production).
        default: The URL to return when nothing usable is stored.

    Returns:
        The persisted URL, or ``default``.
    """
    stored = await storage.get(API_BASE_URL_KEY)
    if stored is None:
        return default
    value = str(stored).strip()
    return value or default


async def save_api_base_url(storage: KeyValueStorage, value: str) -> str:
    """Persist ``value`` as the API base URL and return the normalised string.

    The value is trimmed and any trailing slash removed before storing, so the
    stored URL composes cleanly with the ``/api/v1/...`` paths used by
    :class:`app.api_client.APIClient`. Writing is done through the async
    ``SharedPreferences.set`` API (Requirement 11.1).

    Args:
        storage: An object exposing the async ``set`` method.
        value: The raw URL entered by the user.

    Returns:
        The normalised URL that was written to storage.
    """
    normalised = value.strip().rstrip("/")
    await storage.set(API_BASE_URL_KEY, normalised)
    return normalised


# ---------------------------------------------------------------------------
# validation (pure of the Flet runtime, so directly testable)
# ---------------------------------------------------------------------------


def validate_api_base_url(value: str) -> str | None:
    """Validate an API base URL and return an error message, or ``None``.

    A URL is considered valid only when it uses the ``http`` or ``https``
    scheme and carries a non-empty hostname. Blank/empty input, a missing
    scheme (e.g. ``"example.com"``), a non-HTTP scheme (e.g. ``"ftp://x"``),
    and a missing host (e.g. ``"http://"``) are all rejected.

    Args:
        value: The raw URL entered by the user.

    Returns:
        A human-readable error message string when ``value`` is invalid, or
        ``None`` when it is a usable ``http``/``https`` URL.
    """
    candidate = value.strip()
    if not candidate:
        return "Please enter an API base URL."

    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        return "URL must start with http:// or https://."
    if not parsed.hostname:
        return "URL must include a hostname."
    return None


def _is_loopback_host(hostname: str) -> bool:
    """Return ``True`` when ``hostname`` refers to the local loopback.

    The literal ``localhost`` is treated as loopback, as is any IP address
    inside the IPv4 ``127.0.0.0/8`` block or the IPv6 ``::1`` loopback. Any
    other hostname (a remote host or non-loopback IP) returns ``False``.

    Args:
        hostname: The host portion of a parsed URL.

    Returns:
        ``True`` for loopback hosts, ``False`` otherwise.
    """
    host = hostname.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def warn_insecure_api_base_url(value: str) -> str | None:
    """Return a warning when ``value`` sends traffic over insecure ``http``.

    Work-location records are transmitted to the backend, so using plain
    ``http://`` against a *remote* host exposes them in transit. This helper
    returns a non-blocking warning message in that case. Loopback development
    URLs (``localhost``, the ``127.0.0.0/8`` block, and the IPv6 ``::1``) over
    ``http`` are considered safe and return ``None``, as do all ``https`` URLs.

    This is intentionally *not* a hard validation error — callers should still
    allow the save to proceed while surfacing the warning to the user. Invalid
    URLs (which :func:`validate_api_base_url` rejects) also return ``None``
    here, leaving the blocking error to that validator.

    Args:
        value: The raw URL entered by the user.

    Returns:
        A human-readable warning message when ``value`` uses ``http`` with a
        non-loopback host, or ``None`` when no warning is warranted.
    """
    parsed = urlparse(value.strip())
    if parsed.scheme != "http" or not parsed.hostname:
        return None
    if _is_loopback_host(parsed.hostname):
        return None
    return (
        "Warning: this URL uses insecure http:// to a remote host. "
        "Your work-location data will be sent unencrypted. "
        "Use https:// for remote backends."
    )


# ---------------------------------------------------------------------------
# view builder
# ---------------------------------------------------------------------------


def build_settings_view(
    page: ft.Page,
    storage: KeyValueStorage,
    current_value: str = DEFAULT_API_BASE_URL,
    on_saved: Callable[[str], None] | None = None,
) -> ft.Container:
    """Build the settings screen for configuring the API base URL.

    The screen shows an ``ft.TextField`` pre-filled with ``current_value`` (the
    URL already loaded via :func:`load_api_base_url` on startup) and a Save
    button. Pressing Save normalises and persists the field's value through
    :func:`save_api_base_url`, reflects the normalised value back into the
    field, shows a confirmation snack bar, and — when supplied — notifies
    ``on_saved`` so the caller can rebuild its :class:`app.api_client.APIClient`
    against the new URL.

    Args:
        page: The active Flet page; used to schedule the async save and repaint.
        storage: The async key-value storage service.
        current_value: The URL to pre-fill the field with.
        on_saved: Optional callback invoked with the normalised URL after a
            successful save.

    Returns:
        An :class:`ft.Container` holding the settings form.
    """
    url_field = ft.TextField(
        label="API base URL",
        value=current_value,
        hint_text=DEFAULT_API_BASE_URL,
        autofocus=True,
    )

    def _on_save(_e: ft.ControlEvent) -> None:
        async def _task() -> None:
            raw = url_field.value or ""
            error = validate_api_base_url(raw)
            if error is not None:
                # Reject invalid input: surface the error inline and via a red
                # snack bar, and do NOT persist anything.
                url_field.error_text = error
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(error, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.RED_700,
                    )
                )
                page.update()
                return

            # Valid: clear any prior error, normalise and persist.
            url_field.error_text = None
            normalised = await save_api_base_url(storage, raw)
            url_field.value = normalised

            # Non-blocking security warning for remote plain-http backends: the
            # save still proceeds, but the user is warned (an amber snack bar,
            # visually distinct from the green success toast, plus a helper
            # text under the field).
            warning = warn_insecure_api_base_url(normalised)
            if warning is not None:
                url_field.helper_text = warning
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(warning, color=ft.Colors.BLACK),
                        bgcolor=ft.Colors.AMBER_700,
                    )
                )
            else:
                url_field.helper_text = None
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text("API URL saved.", color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.GREEN_700,
                    )
                )
            if on_saved is not None:
                on_saved(normalised)
            page.update()

        page.run_task(_task)

    save_button = ft.Button(
        content=ft.Text("Save"),
        color=ft.Colors.WHITE,
        bgcolor=ft.Colors.BLUE_700,
        on_click=_on_save,
    )

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text("Settings", weight=ft.FontWeight.BOLD, size=18),
                url_field,
                ft.Row(
                    controls=[save_button],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=16,
        ),
        padding=16,
        expand=True,
    )
