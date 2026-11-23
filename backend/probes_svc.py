"""探头登记与在线态。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import ACTIVE_BATCH_PARAMS, ACTIVE_BATCH_WHERE, probe_lock_key
from models import ProbeIn

router = APIRouter(tags=["probes"])


def _probe_contention_summary(conn, probe_id: int) -> dict:
    """同探头建批争用痕（与 contention_log 同源，不另造口径）。"""
    key = probe_lock_key(probe_id)
    total = conn.execute(
        "SELECT COUNT(*) c FROM contention_log WHERE lock_key=?", (key,)
    ).fetchone()["c"]
    last = conn.execute(
        """SELECT actor,action,detail,created_at FROM contention_log
           WHERE lock_key=? ORDER BY id DESC LIMIT 1""",
        (key,),
    ).fetchone()
    return {
        "lock_key": key,
        "contention_count": total,
        "last_contention": dict(last) if last else None,
    }


def _probe_active_batches(conn, probe_id: int) -> list:
    rows = conn.execute(
        f"""SELECT id,batch_code,status,generation FROM temp_batches
            WHERE probe_id=? AND {ACTIVE_BATCH_WHERE} ORDER BY id DESC""",
        (probe_id, *ACTIVE_BATCH_PARAMS),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/probes")
def list_probes(authorization: AuthHeader = None, chamber_id: int | None = None):
    require_user(authorization)
    with connect() as conn:
        if chamber_id:
            rows = conn.execute(
                """SELECT p.*, c.chamber_code, c.region FROM probes p
                   JOIN cold_chambers c ON c.id=p.chamber_id
                   WHERE p.chamber_id=? ORDER BY p.id""",
                (chamber_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.*, c.chamber_code, c.region FROM probes p
                   JOIN cold_chambers c ON c.id=p.chamber_id ORDER BY p.id"""
            ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            active = _probe_active_batches(conn, d["id"])
            d["active_batches"] = active
            # 单轨不变量：同一探头正式在批至多一笔
            d["single_track_violations"] = max(0, len(active) - 1)
            d.update(_probe_contention_summary(conn, d["id"]))
            items.append(d)
        return {"items": items}


@router.get("/api/probes/{probe_id}")
def get_probe(probe_id: int, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            """SELECT p.*, c.name chamber_name, c.target_min, c.target_max
               FROM probes p JOIN cold_chambers c ON c.id=p.chamber_id
               WHERE p.id=?""",
            (probe_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "探头不存在")
        cals = conn.execute(
            "SELECT * FROM calibration_records WHERE probe_id=? ORDER BY id DESC",
            (probe_id,),
        ).fetchall()
        active = _probe_active_batches(conn, probe_id)
        return {
            "probe": dict(row),
            "calibrations": [dict(x) for x in cals],
            "active_batches": active,
            "single_track_violations": max(0, len(active) - 1),
            "contention": _probe_contention_summary(conn, probe_id),
        }


@router.post("/api/probes")
def register_probe(body: ProbeIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        ch = conn.execute(
            "SELECT id FROM cold_chambers WHERE id=?", (body.chamber_id,)
        ).fetchone()
        if not ch:
            raise HTTPException(404, "仓间不存在")
        if conn.execute(
            "SELECT id FROM probes WHERE probe_code=?", (body.probe_code,)
        ).fetchone():
            raise HTTPException(409, "探头编码已存在")
        cur = conn.execute(
            """INSERT INTO probes(probe_code,chamber_id,model,online_status,
               calibration_due,created_at) VALUES (?,?,?,?,?,?)""",
            (
                body.probe_code,
                body.chamber_id,
                body.model,
                "在线",
                body.calibration_due,
                now_iso(),
            ),
        )
        write_audit(conn, user, "probe_register", body.probe_code, {"id": cur.lastrowid})
        conn.commit()
        return {"id": cur.lastrowid, "probe_code": body.probe_code, "online_status": "在线"}


@router.post("/api/probes/{probe_id}/offline")
def set_offline(probe_id: int, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        row = conn.execute("SELECT * FROM probes WHERE id=?", (probe_id,)).fetchone()
        if not row:
            raise HTTPException(404, "探头不存在")
        conn.execute(
            "UPDATE probes SET online_status='离线' WHERE id=?", (probe_id,)
        )
        write_audit(conn, user, "probe_offline", row["probe_code"], {})
        conn.commit()
        return {"id": probe_id, "online_status": "离线"}