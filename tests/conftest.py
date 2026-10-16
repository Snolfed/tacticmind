"""Shared test setup: every test starts in the default language (English)."""

from collections.abc import Iterator

import pytest

from tacticmind.i18n import DEFAULT_LANGUAGE, set_language


@pytest.fixture(autouse=True)
def default_language() -> Iterator[None]:
    set_language(DEFAULT_LANGUAGE)
    yield
    set_language(DEFAULT_LANGUAGE)
