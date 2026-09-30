from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

import pytest

from community_bot.application.assignments import (
    AssignmentDeadlineSource,
    AssignmentDeadlineWorker,
    AssignmentService,
)


@pytest.mark.asyncio
async def test_worker_processes_each_deadline_kind_with_its_own_batch() -> None:
    """A full task batch must not starve due reviews or rejections."""
    source = create_autospec(AssignmentDeadlineSource, instance=True)
    service = create_autospec(AssignmentService, instance=True)
    task_id, review_id, rejection_id = uuid4(), uuid4(), uuid4()
    source.due_task_ids.return_value = (task_id,)
    source.due_review_ids.return_value = (review_id,)
    source.due_rejection_ids.return_value = (rejection_id,)
    now = datetime.datetime(2026, 9, 30, tzinfo=datetime.UTC)
    worker = AssignmentDeadlineWorker(source, service, batch_size=1)

    assert await worker.tick(now=now) == 3

    for query in (source.due_task_ids, source.due_review_ids, source.due_rejection_ids):
        query.assert_awaited_once_with(now=now, limit=1)
    for finalize, identity, key in (
        (service.finalize_deadline, task_id, "task_id"),
        (service.finalize_review, review_id, "assignment_id"),
        (service.finalize_rejection, rejection_id, "assignment_id"),
    ):
        assert isinstance(finalize, AsyncMock)
        finalize.assert_awaited_once()
        assert finalize.await_args.kwargs[key] == identity
        assert finalize.await_args.kwargs["now"] == now

    source.due_task_ids.return_value = ()
    source.due_review_ids.return_value = ()
    source.due_rejection_ids.return_value = ()
    assert await worker.tick(now=now) == 0
    assert service.finalize_review.await_count == 1
    assert service.finalize_rejection.await_count == 1
