"""Property-based tests for ``EntryRepository`` (task 3.3).

Uses ``hypothesis`` to verify universal properties of the repository that
should hold across all valid inputs, complementing the example-based tests in
``test_entry_repository.py``.

Because ``hypothesis`` drives many examples per test function while
pytest-asyncio fixtures are function-scoped (set up once per test), each
example builds its own isolated in-memory SQLite database rather than relying
on the shared ``async_session`` fixture. This keeps every generated example
fully independent.

Requirements: 5.2
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models import Base
from backend.repository import EntryRepository
from backend.schemas import WorkEntryCreate, WorkLocation

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@asynccontextmanager
async def _fresh_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` bound to an isolated in-memory database.

    The schema is created from ``Base.metadata`` up front and the engine is
    disposed on exit, guaranteeing each example starts from an empty database.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()


# Distinct dates within a single month (June 2025 has 30 days), so any subset
# of these days is guaranteed to contain no duplicate ``work_date`` values —
# which respects the unique constraint on ``work_date``.
_days_in_month = st.lists(
    st.integers(min_value=1, max_value=30),
    min_size=1,
    max_size=30,
    unique=True,
)


class TestEntryListOrderingProperty:
    @given(days=_days_in_month, seed=st.integers())
    @settings(max_examples=100, deadline=None)
    def test_get_by_month_always_returns_ascending_order(
        self, days: list[int], seed: int
    ) -> None:
        """**Validates: Requirements 5.2**

        Property 6: Entry List Ordering
        For a shuffled list of distinct dates within a single month, inserting
        them in random order, ``get_by_month`` always returns them sorted
        ascending by ``work_date``.
        """
        # Shuffle the insertion order deterministically from the generated seed
        # so hypothesis explores many distinct orderings without a duplicate
        # strategy for the permutation.
        shuffled = list(days)
        rng_index = seed % max(len(shuffled), 1)
        shuffled = shuffled[rng_index:] + shuffled[:rng_index]
        shuffled.reverse()

        async def scenario() -> list[date]:
            async with _fresh_session() as session:
                repo = EntryRepository(session)
                for day in shuffled:
                    await repo.create(
                        WorkEntryCreate(
                            work_date=date(2025, 6, day),
                            location=WorkLocation.DENMARK,
                        )
                    )
                result = await repo.get_by_month(2025, 6)
                return [entry.work_date for entry in result]

        returned_dates = asyncio.run(scenario())

        # The returned dates must be exactly the inserted dates, sorted ascending.
        expected = sorted(date(2025, 6, day) for day in days)
        assert returned_dates == expected
        assert returned_dates == sorted(returned_dates)
