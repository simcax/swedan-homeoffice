"""Login screen — shared-secret gate for the Flet app (task 10.2).

The app is gated behind a shared secret the user enters once; it is remembered
across sessions in Flet's ``SharedPreferences`` key-value store and attached by
:class:`app.api_client.APIClient` as the ``X-API-Key`` header on every request.

As with the other views, all persistence and decision logic lives in tiny
runtime-free helpers so they can be unit-tested without starting the Flet
runtime:

* :func:`validate_secret` — rejects empty/blank input (Requirement 5.4),
* :func:`load_secret` / :func:`save_secret` / :func:`clear_secret` — read,
  write, and remove the stored secret through the async ``SharedPreferences``
  API (Requirements 5.2, 5.3, 8.1),
* :func:`resolve_initial_screen` — picks the first screen from a stored secret
  (Requirements 5.1, 5.2).

The view builder itself is a thin Flet wrapper: it shows a password field, a
submit button, and a validation message when the secret was rejected
(``auth_rejected``) or on empty submit (Requirements 5.4, 8.3).

Requirements: 5.1, 5.2, 5.3, 5.4, 8.3
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app.state import Screen

# The ``KeyValueStorage`` protocol (the async ``SharedPreferences`` subset we
# rely on, now including ``remove``) is defined once in ``settings_view`` and
# reused here so there is a single source of truth for the storage contract.
from app.views.settings_view import KeyValueStorage

# Storage key the shared secret is persisted under (Requirement 5.3).
APP_SECRET_KEY = "APP_SHARED_SECRET"

# Message shown when the user submits an empty/blank secret (Requirement 5.4).
_EMPTY_SECRET_MESSAGE = "Please enter the shared secret."

# Message shown when returning to login after a backend 401 (Requirement 8.3).
_REJECTED_SECRET_MESSAGE = "Secret rejected. Please re-enter the shared secret."


# ---------------------------------------------------------------------------
# validation (pure of the Flet runtime, so directly testable)
# ---------------------------------------------------------------------------


def validate_secret(value: str) -> str | None:
    """Validate a submitted secret and return an error message, or ``None``.

    A secret is usable only when it contains at least one non-whitespace
    character. The empty string and whitespace-only input are rejected with a
    human-readable message so the login view can stay put and prompt again
    (Requirement 5.4).

    Args:
        value: The raw secret entered by the user.

    Returns:
        An error message string when ``value`` is empty/blank, or ``None`` when
        it carries a usable secret.
    """
    return None if value.strip() else _EMPTY_SECRET_MESSAGE


# ---------------------------------------------------------------------------
# persistence helpers (pure of the Flet runtime, so directly testable)
# ---------------------------------------------------------------------------


async def load_secret(storage: KeyValueStorage) -> str | None:
    """Return the stored shared secret, or ``None`` when none is usable.

    Reads :data:`APP_SECRET_KEY` through the async ``SharedPreferences.get``
    API. A missing key (``None``) or an empty/blank stored value yields
    ``None`` so callers always receive either a usable, trimmed secret or
    nothing at all (Requirement 5.2).

    Args:
        storage: An object exposing the async ``get`` method.

    Returns:
        The persisted trimmed secret, or ``None``.
    """
    stored = await storage.get(APP_SECRET_KEY)
    value = str(stored).strip() if stored is not None else ""
    return value or None


async def save_secret(storage: KeyValueStorage, value: str) -> str:
    """Persist ``value`` as the shared secret and return the trimmed string.

    The value is trimmed before storing so a stray leading/trailing space never
    changes the header sent to the backend. Writing is done through the async
    ``SharedPreferences.set`` API (Requirement 5.3).

    Args:
        storage: An object exposing the async ``set`` method.
        value: The raw secret entered by the user.

    Returns:
        The trimmed secret that was written to storage.
    """
    secret = value.strip()
    await storage.set(APP_SECRET_KEY, secret)
    return secret


async def clear_secret(storage: KeyValueStorage) -> None:
    """Remove the stored shared secret from local storage.

    Invoked after a backend ``401`` so the rejected secret is forgotten and the
    user is forced to re-enter one (Requirement 8.1). Writing is done through
    the async ``SharedPreferences.remove`` API.

    Args:
        storage: An object exposing the async ``remove`` method.
    """
    await storage.remove(APP_SECRET_KEY)


# ---------------------------------------------------------------------------
# initial-screen resolution (pure of the Flet runtime, so directly testable)
# ---------------------------------------------------------------------------


def resolve_initial_screen(stored_secret: str | None) -> Screen:
    """Pick the first screen to show from the stored secret.

    Returns :attr:`Screen.HOME` only when ``stored_secret`` is a non-blank
    string, meaning a usable secret is already remembered; otherwise
    (``None``, empty, or whitespace-only) returns :attr:`Screen.LOGIN` so the
    front page stays withheld (Requirements 5.1, 5.2).

    Args:
        stored_secret: The secret loaded from storage, or ``None``.

    Returns:
        :attr:`Screen.HOME` when a usable secret exists, else
        :attr:`Screen.LOGIN`.
    """
    return Screen.HOME if (stored_secret or "").strip() else Screen.LOGIN


# ---------------------------------------------------------------------------
# view builder
# ---------------------------------------------------------------------------


def build_login_view(
    page: ft.Page,
    on_submit: Callable[[str], None],
    *,
    auth_rejected: bool = False,
) -> ft.Container:
    """Build the login screen gating access to the front page.

    The screen shows a password-style ``ft.TextField`` for the shared secret
    and a submit button. On submit the field is validated with
    :func:`validate_secret`: empty/blank input surfaces the validation message
    inline and keeps the user on the login screen (Requirement 5.4); a usable
    secret is forwarded to ``on_submit`` so the caller can persist it, configure
    the API client, and navigate to the front page (Requirement 5.3).

    When ``auth_rejected`` is set — the user was sent back here by a backend
    ``401`` — the "secret rejected" message is shown immediately so they know
    why they are back on the login screen (Requirement 8.3).

    Args:
        page: The active Flet page; used to repaint after validation.
        on_submit: Callback invoked with the raw secret once it validates.
        auth_rejected: Whether to show the "secret rejected" message on load.

    Returns:
        An :class:`ft.Container` holding the login form.
    """
    secret_field = ft.TextField(
        label="Shared secret",
        password=True,
        can_reveal_password=True,
        error=_REJECTED_SECRET_MESSAGE if auth_rejected else None,
        autofocus=True,
    )

    def _submit(_e: ft.ControlEvent) -> None:
        raw = secret_field.value or ""
        error = validate_secret(raw)
        if error is not None:
            # Empty/blank: surface the validation message and stay on login.
            secret_field.error = error
            page.update()
            return
        secret_field.error = None
        on_submit(raw)

    secret_field.on_submit = _submit

    submit_button = ft.Button(
        content=ft.Text("Unlock"),
        color=ft.Colors.WHITE,
        bgcolor=ft.Colors.BLUE_700,
        on_click=_submit,
    )

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text("Enter shared secret", weight=ft.FontWeight.BOLD, size=18),
                ft.Text(
                    "This app is protected. Enter the shared secret to continue.",
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                secret_field,
                ft.Row(
                    controls=[submit_button],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=16,
        ),
        padding=16,
        expand=True,
    )
