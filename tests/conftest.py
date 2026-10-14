"""Wspólne ustawienia testów: każdy test zaczyna się z językiem polskim (domyślnym)."""

from collections.abc import Iterator

import pytest

from taktykai.i18n import DEFAULT_LANGUAGE, set_language


@pytest.fixture(autouse=True)
def default_language() -> Iterator[None]:
    set_language(DEFAULT_LANGUAGE)
    yield
    set_language(DEFAULT_LANGUAGE)
