"""Tests for the day-type picker options."""

from datetime import date

import flet as ft

from app.api_client import WorkLocation
from app.components.day_type_picker import PICKER_LABELS, build_day_type_picker


def test_picker_offers_work_travel() -> None:
    picker = build_day_type_picker(
        work_date=date(2025, 6, 10),
        current=None,
        on_select=lambda _location: None,
        on_clear=lambda: None,
        on_dismiss=lambda: None,
    )

    choices = picker.content.controls
    travel_choice = next(
        choice
        for choice in choices
        if isinstance(choice, ft.Button) and choice.data is WorkLocation.TRAVEL
    )
    assert PICKER_LABELS[WorkLocation.TRAVEL] == "Work Travel"
    assert isinstance(travel_choice.content, ft.Text)
    assert travel_choice.content.value == "Work Travel"
