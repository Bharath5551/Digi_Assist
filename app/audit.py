from typing import Any

from app.db.base import session
from app.db.models import AuditLog


async def record(skill: str, tool: str, args: dict[str, Any], *, ok: bool, result: str, approval_id: int | None = None) -> None:
    async with session() as s:
        s.add(
            AuditLog(
                skill=skill,
                tool=tool,
                args=args,
                ok=ok,
                result_preview=(result or "")[:1000],
                approval_id=approval_id,
            )
        )
        await s.commit()
