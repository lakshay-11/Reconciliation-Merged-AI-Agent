"""
Notification system (bilingual AR + EN) for reconciliation events.

Creates Notification rows in the DB; actual delivery (email/push) would
plug into a background job queue in production.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Notification

logger = logging.getLogger(__name__)


async def notify(
    db: AsyncSession,
    recipient_id: int,
    notification_type: str,
    title_en: str,
    title_ar: str,
    message_en: str,
    message_ar: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> Notification:
    """Insert a bilingual notification for a user. Caller owns the commit."""
    n = Notification(
        recipient_id=recipient_id,
        notification_type=notification_type,
        title=title_en,
        title_ar=title_ar,
        message=message_en,
        message_ar=message_ar,
        related_entity_type=entity_type,
        related_entity_id=entity_id,
    )
    db.add(n)
    logger.debug(
        "Notification queued: type=%s recipient=%d entity=%s#%s",
        notification_type, recipient_id, entity_type, entity_id,
    )
    return n


async def notify_exception_raised(
    db: AsyncSession,
    recipient_id: int,
    exception_id: int,
    amount: float,
    currency: str,
    priority_level: str,
) -> Notification:
    return await notify(
        db=db,
        recipient_id=recipient_id,
        notification_type="exception_raised",
        title_en=f"New {priority_level.upper()} exception requires review",
        title_ar=f"استثناء {priority_level} جديد يتطلب المراجعة",
        message_en=(
            f"A {priority_level} priority exception has been raised for a "
            f"transaction of {abs(amount):,.2f} {currency}. Please review and resolve."
        ),
        message_ar=(
            f"تم رفع استثناء {priority_level} لمعاملة بقيمة "
            f"{abs(amount):,.2f} {currency}. يرجى المراجعة والحل."
        ),
        entity_type="exception_queue",
        entity_id=exception_id,
    )


async def notify_run_complete(
    db: AsyncSession,
    recipient_id: int,
    run_id: int,
    auto_pct: float,
    exception_count: int,
) -> Notification:
    return await notify(
        db=db,
        recipient_id=recipient_id,
        notification_type="run_complete",
        title_en=f"Reconciliation run #{run_id} completed",
        title_ar=f"اكتمل تشغيل المطابقة #{run_id}",
        message_en=(
            f"Run #{run_id} finished. Auto-reconciled: {auto_pct:.1f}%. "
            f"Exceptions requiring review: {exception_count}."
        ),
        message_ar=(
            f"اكتمل التشغيل #{run_id}. المطابقة التلقائية: {auto_pct:.1f}٪. "
            f"الاستثناءات التي تتطلب المراجعة: {exception_count}."
        ),
        entity_type="reconciliation_runs",
        entity_id=run_id,
    )
