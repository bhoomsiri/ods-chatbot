"""ConversationStore contract tests against the in-memory fake.

The same behaviour is required of the Postgres adapter; the critical property is
ownership scoping — one user must never see or mutate another's conversations.
"""

from __future__ import annotations

import pytest

from app.domain.entities import Citation
from app.infrastructure.fakes import InMemoryConversationStore

ALICE = "user_alice"
BOB = "user_bob"


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore()


async def test_create_and_list_scoped_by_user(
    store: InMemoryConversationStore,
) -> None:
    a = await store.create(user_id=ALICE, title="ก่อนผ่าตัด")
    await store.create(user_id=BOB, title="ของบ๊อบ")

    alice_list = await store.list_for_user(user_id=ALICE)
    assert [c.id for c in alice_list] == [a.id]  # Bob's thread is invisible


async def test_empty_title_falls_back(store: InMemoryConversationStore) -> None:
    c = await store.create(user_id=ALICE, title="   ")
    assert c.title == "แชตใหม่"


async def test_add_message_orders_and_bumps_updated_at(
    store: InMemoryConversationStore,
) -> None:
    first = await store.create(user_id=ALICE, title="first")
    second = await store.create(user_id=ALICE, title="second")

    await store.add_message(
        conversation_id=first.id, user_id=ALICE, role="user", content="คำถาม"
    )
    # first was just touched -> it should now sort ahead of second
    ordered = await store.list_for_user(user_id=ALICE)
    assert ordered[0].id == first.id and ordered[1].id == second.id

    msgs = await store.get_messages(conversation_id=first.id, user_id=ALICE)
    assert msgs is not None and [m.content for m in msgs] == ["คำถาม"]


async def test_citations_round_trip(store: InMemoryConversationStore) -> None:
    c = await store.create(user_id=ALICE, title="t")
    cit = Citation(
        id="ch1", source="ODS MIS 2565", page=12, score=0.9, snippet="งดน้ำ"
    )
    await store.add_message(
        conversation_id=c.id, user_id=ALICE, role="assistant",
        content="คำตอบ", citations=[cit],
    )
    msgs = await store.get_messages(conversation_id=c.id, user_id=ALICE)
    assert msgs is not None
    got = msgs[0].citations[0]
    assert (got.source, got.page, got.score) == ("ODS MIS 2565", 12, 0.9)


async def test_foreign_user_cannot_read_or_mutate(
    store: InMemoryConversationStore,
) -> None:
    c = await store.create(user_id=ALICE, title="ของอลิซ")

    assert await store.get_messages(conversation_id=c.id, user_id=BOB) is None
    assert (
        await store.add_message(
            conversation_id=c.id, user_id=BOB, role="user", content="แอบ"
        )
        is None
    )
    assert await store.set_title(conversation_id=c.id, user_id=BOB, title="x") is False
    assert await store.delete(conversation_id=c.id, user_id=BOB) is False

    # Alice's data is untouched.
    msgs = await store.get_messages(conversation_id=c.id, user_id=ALICE)
    assert msgs == []


async def test_owner_can_rename_and_delete(
    store: InMemoryConversationStore,
) -> None:
    c = await store.create(user_id=ALICE, title="เก่า")
    assert await store.set_title(
        conversation_id=c.id, user_id=ALICE, title="ใหม่"
    )
    renamed = (await store.list_for_user(user_id=ALICE))[0]
    assert renamed.title == "ใหม่"

    assert await store.delete(conversation_id=c.id, user_id=ALICE)
    assert await store.list_for_user(user_id=ALICE) == []


async def test_missing_conversation_returns_none(
    store: InMemoryConversationStore,
) -> None:
    assert await store.get_messages(conversation_id="nope", user_id=ALICE) is None
