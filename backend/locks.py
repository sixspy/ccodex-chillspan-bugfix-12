"""仓间锁与争用登记（公共并发面）。

探头建批争用口径（甲路径定稿，五处同源）：
  - 同一探头的建批锁键全局唯一（probe:{probe_id}），与持有人无关；
  - 并发抢锁只有一笔能拿到，输家写争用痕并 409；
  - 锁内若发现该探头已有正式在批，第二笔零增拒建，同样写争用痕；
  - 任何争用一律落 contention_log，不存在无痕旁路。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit

router = APIRouter(tags=["locks"])

# 同探头正式在批的唯一口径（五处同源：争用痕/建批/仓间/封批/对账）。
# 只认“已入库/超温处理中”为正式在批；草稿是未提交意图、已封批/作废已收口，
# 均不占探头单轨。禁止各页另造 NOT IN 口径把草稿混入。
FORMAL_STATUSES = ("已入库", "超温处理中")
ACTIVE_BATCH_WHERE = f"status IN ({','.join('?' * len(FORMAL_STATUSES))})"
ACTIVE_BATCH_PARAMS: tuple[str, ...] = FORMAL_STATUSES


class LockIn(BaseModel):
    lock_key: str
    action: str = "acquire"


def probe_lock_key(probe_id: int) -> str:
    """探头建批互斥锁键：同探头单轨，不允许混入持有人维度。"""
    return f"probe:{probe_id}"


def record_contention(
    conn, lock_key: str, actor: str, detail: str, action: str = "争用"
) -> None:
    """争用痕唯一写口：锁争用与在批拒建同源落表。"""
    conn.execute(
        """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
           VALUES (?,?,?,?,?)""",
        (lock_key, actor, action, detail, now_iso()),
    )


def try_acquire(conn, lock_key: str, holder: str) -> bool:
    # INSERT OR IGNORE 靠主键原子判争，避免“先查后插”的并发双插
    cur = conn.execute(
        "INSERT OR IGNORE INTO chamber_locks(lock_key,holder,acquired_at) VALUES (?,?,?)",
        (lock_key, holder, now_iso()),
    )
    if cur.rowcount == 1:
        return True
    row = conn.execute(
        "SELECT holder FROM chamber_locks WHERE lock_key=?", (lock_key,)
    ).fetchone()
    if row is not None and row["holder"] == holder:
        # 同持有人重入，允许
        return True
    record_contention(
        conn, lock_key, holder, f"持有者={row['holder'] if row else '未知'}"
    )
    return False


def release(conn, lock_key: str, holder: str) -> None:
    conn.execute(
        "DELETE FROM chamber_locks WHERE lock_key=? AND holder=?",
        (lock_key, holder),
    )


def require_lock(conn, lock_key: str, holder: str) -> None:
    if not try_acquire(conn, lock_key, holder):
        raise HTTPException(409, "争用：后到只记争用，不写业务")


@router.get("/api/locks")
def list_locks(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chamber_locks ORDER BY acquired_at DESC"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/contention")
def list_contention(
    authorization: AuthHeader = None, probe_id: int | None = None
):
    require_user(authorization)
    with connect() as conn:
        if probe_id is not None:
            rows = conn.execute(
                "SELECT * FROM contention_log WHERE lock_key=? ORDER BY id DESC LIMIT 200",
                (probe_lock_key(probe_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM contention_log ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/locks/acquire")
def acquire_lock(body: LockIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        ok = try_acquire(conn, body.lock_key, user)
        write_audit(conn, user, "lock_acquire", body.lock_key, {"ok": ok})
        conn.commit()
        if not ok:
            raise HTTPException(409, "争用：未能获得锁")
        return {"ok": True, "lock_key": body.lock_key, "holder": user}


@router.post("/api/locks/release")
def release_lock(body: LockIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        release(conn, body.lock_key, user)
        write_audit(conn, user, "lock_release", body.lock_key, {})
        conn.commit()
        return {"ok": True}
