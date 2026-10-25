from collections.abc import AsyncIterator

import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario


@pytest.fixture
async def scenario(family: SeededFamily, fake_telegram: FakeTelegram) -> AsyncIterator[Scenario]:
    s = Scenario(family, fake_telegram)
    await s.start()
    yield s
    await s.stop()
