"""Tests for the login view's message surfaces.

These exercise :func:`app.views.login_view.build_login_view` without starting
the Flet runtime: a mock page is passed and the resulting control tree is
flattened and inspected. They cover the three distinct message states on the
login screen — the inline "secret rejected" error, the informational
"could not verify" notice, and neither — so the two are never conflated.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft

from app.views.login_view import (
    VERIFY_FAILED_MESSAGE,
    build_login_view,
)


def _texts(control: object) -> list[str]:
    """Flatten a control tree into the list of ``ft.Text`` values."""
    out: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.Text) and node.value:
            out.append(node.value)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    _walk(control)
    return out


def _secret_field(control: object) -> ft.TextField:
    """Return the first ``ft.TextField`` in the control tree."""
    found: list[ft.TextField] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.TextField):
            found.append(node)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    _walk(control)
    assert found, "expected a secret TextField in the login view"
    return found[0]


def test_notice_is_rendered_above_the_form() -> None:
    page = MagicMock(spec=ft.Page)
    view = build_login_view(page, lambda _s: None, notice=VERIFY_FAILED_MESSAGE)

    assert VERIFY_FAILED_MESSAGE in _texts(view)
    # A verification notice is NOT a rejection: the field error stays clear.
    assert _secret_field(view).error is None


def test_rejected_shows_field_error_not_notice() -> None:
    page = MagicMock(spec=ft.Page)
    view = build_login_view(page, lambda _s: None, auth_rejected=True)

    # Rejection surfaces as the field's inline error, and the verify notice is
    # absent.
    assert _secret_field(view).error is not None
    assert VERIFY_FAILED_MESSAGE not in _texts(view)


def test_no_messages_when_clean() -> None:
    page = MagicMock(spec=ft.Page)
    view = build_login_view(page, lambda _s: None)

    assert _secret_field(view).error is None
    assert VERIFY_FAILED_MESSAGE not in _texts(view)
