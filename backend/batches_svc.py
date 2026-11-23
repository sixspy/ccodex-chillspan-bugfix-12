"""温控批次入库：温度点序列 JSON。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import (
    ACTIVE_BATCH_PARAMS,
    ACTIVE_BATCH_WHERE,
    probe_lock_key,
    record_contention,
    release,
    try_acquire,
)
from models import BatchIn
from validators import summarize_points, validate_probe_online, validate_temp_point

router = APIRouter(tags=["batches"])


def _next_batch_code(conn, chamber_id: int) -> str:
    ch = conn.execute(
        "SELECT chamber_code FROM cold_chambers WHERE id=?", (chamber_id,)
    ).fetchone()
    prefix = ch["chamber_code"] if ch else f"CH-{chamber_id}"
    n = conn.execute(
        "SELECT COUNT(*) c FROM temp_batches WHERE chamber_id=?",
        (chamber_id,),
    ).fetchone()["c"]
    return f"TB-{prefix}-{n + 1:03d}"


@router.get("/api/batches")
def list_batches(authorization: AuthHeader = None, status: str | None = None):
    require_user(authorization)
    with connect() as conn:
        if status:
            rows = conn.execute(
                """SELECT b.*, c.chamber_code, p.probe_code FROM temp_batches b
                   JOIN cold_chambers c ON c.id=b.chamber_id
                   JOIN probes p ON p.id=b.probe_id
                   WHERE b.status=? ORDER BY b.id DESC""",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT b.*, c.chamber_code, p.probe_code FROM temp_batches b
                   JOIN cold_chambers c ON c.id=b.chamber_id
                   JOIN probes p ON p.id=b.probe_id
                   ORDER BY b.id DESC"""
            ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["temp_points"] = json.loads(d["temp_points"] or "[]")
            items.append(d)
        return {"items": items}


@router.get("/api/batches/{batch_id}")
def get_batch(batch_id: int, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            """SELECT b.*, c.name chamber_name, c.target_min, c.target_max, p.probe_code
               FROM temp_batches b
               JOIN cold_chambers c ON c.id=b.chamber_id
               JOIN probes p ON p.id=b.probe_id WHERE b.id=?""",
            (batch_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "批次不存在")
        data = dict(row)
        data["temp_points"] = json.loads(data["temp_points"] or "[]")
        exc = conn.execute(
            "SELECT * FROM excursion_cursors WHERE batch_id=? ORDER BY id DESC",
            (batch_id,),
        ).fetchall()
        seals = conn.execute(
            "SELECT * FROM seal_snapshots WHERE batch_id=? ORDER BY id DESC",
            (batch_id,),
        ).fetchall()
        return {
            "batch": data,
            "excursions": [dict(e) for e in exc],
            "seals": [dict(s) for s in seals],
        }


@router.post("/api/batches")
def create_batch(body: BatchIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    # 甲路径定稿：同探头建批单轨互斥，锁键只认探头、不掺持有人
    lock_key = probe_lock_key(body.probe_id)
    with connect() as conn:
        if not try_acquire(conn, lock_key, user):
            # 抢锁即争用：争用痕已在锁服务落表，先提交再拒，零业务写入
            conn.commit()
            raise HTTPException(409, "争用：该探头正被其他建批占用")
        try:
            ch = conn.execute(
                "SELECT * FROM cold_chambers WHERE id=?", (body.chamber_id,)
            ).fetchone()
            if not ch:
                raise HTTPException(404, "仓间不存在")
            probe = conn.execute(
                "SELECT * FROM probes WHERE id=?", (body.probe_id,)
            ).fetchone()
            if not probe or probe["chamber_id"] != body.chamber_id:
                raise HTTPException(422, "探头与仓间不匹配")
            validate_probe_online(probe)
            # 锁内硬检查：同探头已有正式在批，第二笔零增拒建并写争用痕
            active_on_probe = conn.execute(
                f"""SELECT batch_code FROM temp_batches
                    WHERE probe_id=? AND {ACTIVE_BATCH_WHERE}
                    ORDER BY id DESC LIMIT 1""",
                (body.probe_id, *ACTIVE_BATCH_PARAMS),
            ).fetchone()
            if active_on_probe is not None:
                record_contention(
                    conn,
                    lock_key,
                    user,
                    f"在批拒建：在批占用={active_on_probe['batch_code']}",
                )
                write_audit(
                    conn,
                    user,
                    "batch_contention_reject",
                    active_on_probe["batch_code"],
                    {"probe_id": body.probe_id},
                )
                conn.commit()
                raise HTTPException(409, "争用：该探头已有正式在批，禁止双批并存")
            active = conn.execute(
                f"""SELECT COUNT(*) c FROM temp_batches
                   WHERE chamber_id=? AND {ACTIVE_BATCH_WHERE}""",
                (body.chamber_id, *ACTIVE_BATCH_PARAMS),
            ).fetchone()["c"]
            if active >= int(ch["quota_batches"]):
                raise HTTPException(409, "仓间在批配额已满")
            points = body.temp_points or []
            for pt in points:
                validate_temp_point(
                    float(pt.get("c", pt.get("temp", 0))),
                    float(ch["target_min"]),
                    float(ch["target_max"]),
                )
            tmin, tmax = summarize_points(points)
            code = body.batch_code or _next_batch_code(conn, body.chamber_id)
            if conn.execute(
                "SELECT id FROM temp_batches WHERE batch_code=?", (code,)
            ).fetchone():
                raise HTTPException(409, "批次编码已存在")
            status = "已入库" if points else "草稿"
            now = now_iso()
            cur = conn.execute(
                """INSERT INTO temp_batches(batch_code,chamber_id,probe_id,cargo_ref,
                   temp_points,generation,status,min_observed,max_observed,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    code,
                    body.chamber_id,
                    body.probe_id,
                    body.cargo_ref,
                    json.dumps(points, ensure_ascii=False),
                    1,
                    status,
                    tmin if points else None,
                    tmax if points else None,
                    now,
                ),
            )
            write_audit(
                conn,
                user,
                "batch_inbound",
                code,
                {"batch_id": cur.lastrowid, "point_count": len(points)},
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "batch_code": code,
                "status": status,
                "point_count": len(points),
            }
        finally:
            release(conn, lock_key, user)
            conn.commit()