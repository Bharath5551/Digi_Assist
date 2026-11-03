from sqlalchemy import or_, select

from app.db.base import session
from app.db.models import Memory


async def remember(key: str, value: str, category: str = "fact", source: str = "user") -> str:
    key = key.strip().lower().replace(" ", "_")[:128]
    async with session() as s:
        row = (await s.execute(select(Memory).where(Memory.key == key))).scalar_one_or_none()
        if row:
            old = row.value
            row.value, row.category, row.source = value, category, source
            await s.commit()
            return f"Updated {key}: '{old}' -> '{value}'"
        s.add(Memory(key=key, value=value, category=category, source=source))
        await s.commit()
        return f"Saved {key} = {value}"


async def forget(key: str) -> str:
    key = key.strip().lower().replace(" ", "_")
    async with session() as s:
        row = (await s.execute(select(Memory).where(Memory.key == key))).scalar_one_or_none()
        if not row:
            return f"Nothing saved under {key}"
        await s.delete(row)
        await s.commit()
        return f"Forgot {key}"


async def search(query: str, limit: int = 20) -> str:
    q = f"%{query.strip().lower()}%"
    async with session() as s:
        rows = (
            await s.execute(
                select(Memory).where(or_(Memory.key.ilike(q), Memory.value.ilike(q))).order_by(Memory.updated_at.desc()).limit(limit)
            )
        ).scalars().all()
    if not rows:
        return "No matching memories."
    return "\n".join(f"{m.key} ({m.category}): {m.value}" for m in rows)


async def snapshot(limit: int = 60) -> str:
    """Compact dump injected into the system prompt."""
    async with session() as s:
        rows = (await s.execute(select(Memory).order_by(Memory.updated_at.desc()).limit(limit))).scalars().all()
    return "\n".join(f"- {m.key}: {m.value}" for m in rows)
