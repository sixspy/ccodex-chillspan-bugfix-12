"""仓间配额 vs 在批差额对账 + 互证只读。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from db import connect
from locks import ACTIVE_BATCH_PARAMS, ACTIVE_BATCH_WHERE, probe_lock_key

router = APIRouter(tags=["reconcile"])


def _probe_track_summary(conn) -> dict:
    """全探头单轨/争用汇总，供对账视图与探头/争用痕视图同源核对。"""
    probes = conn.execute("SELECT id, probe_code, chamber_id FROM probes ORDER BY id").fetchall()
    items = []
    violation_probes = 0
    contention_hits = 0
    for p in probes:
        n = conn.execute(
            f"""SELECT COUNT(*) c FROM temp_batches
                WHERE probe_id=? AND {ACTIVE_BATCH_WHERE}""",
            (p["id"], *ACTIVE_BATCH_PARAMS),
        ).fetchone()["c"]
        traces = conn.execute(
            "SELECT COUNT(*) c FROM contention_log WHERE lock_key=?",
            (probe_lock_key(p["id"]),),
        ).fetchone()["c"]
        violation = max(0, n - 1)
        if violation:
            violation_probes += 1
        contention_hits += traces
        items.append(
            {
                "probe_id": p["id"],
                "probe_code": p["probe_code"],
                "chamber_id": p["chamber_id"],
                "active_batches": n,
                "single_track_violations": violation,
                "contention_count": traces,
                "single_track_ok": n <= 1,
            }
        )
    return {
        "items": items,
        "summary": {
            "probes": len(items),
            "violation_probes": violation_probes,
            "contention_total": contention_hits,
            "all_single_track": violation_probes == 0,
        },
    }


def _chamber_recon(conn, chamber) -> dict:
    cid = chamber["id"]
    quota = int(chamber["quota_batches"])
    active = conn.execute(
        f"""SELECT COUNT(*) c FROM temp_batches
           WHERE chamber_id=? AND {ACTIVE_BATCH_WHERE}""",
        (cid, *ACTIVE_BATCH_PARAMS),
    ).fetchone()["c"]
    sealed = conn.execute(
        """SELECT COUNT(*) c FROM temp_batches
           WHERE chamber_id=? AND status='已封批'""",
        (cid,),
    ).fetchone()["c"]
    gap = quota - active
    ok = active <= quota
    return {
        "chamber_id": cid,
        "chamber_code": chamber["chamber_code"],
        "region": chamber["region"],
        "quota_batches": quota,
        "active_batches": active,
        "sealed_batches": sealed,
        "quota_left": gap,
        "balanced": ok,
        "proof": {
            "formula": "active_batches <= quota_batches",
            "left": active,
            "right": quota,
        },
    }


@router.get("/api/reconcile")
def reconcile_all(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        chambers = conn.execute("SELECT * FROM cold_chambers ORDER BY id").fetchall()
        items = [_chamber_recon(conn, c) for c in chambers]
        bad = [i for i in items if not i["balanced"]]
        probe_track = _probe_track_summary(conn)
        return {
            "items": items,
            "summary": {
                "total": len(items),
                "balanced": len(items) - len(bad),
                "unbalanced": len(bad),
                "probe_single_track": probe_track["summary"],
            },
            "probe_tracks": probe_track["items"],
        }


@router.get("/api/reconcile/{chamber_code}")
def reconcile_one(chamber_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        ch = conn.execute(
            "SELECT * FROM cold_chambers WHERE chamber_code=?", (chamber_code,)
        ).fetchone()
        if not ch:
            raise HTTPException(404, "仓间不存在")
        return _chamber_recon(conn, ch)


@router.get("/api/proof/batch/{batch_code}")
def batch_proof(batch_code: str, authorization: AuthHeader = None):
    """批次互证：封批代 + 温谱导出 + 开放游标。"""
    require_user(authorization)
    with connect() as conn:
        batch = conn.execute(
            "SELECT * FROM temp_batches WHERE batch_code=?", (batch_code,)
        ).fetchone()
        if not batch:
            raise HTTPException(404, "批次不存在")
        open_exc = conn.execute(
            """SELECT COUNT(*) c FROM excursion_cursors
               WHERE batch_id=? AND status='开放'""",
            (batch["id"],),
        ).fetchone()["c"]
        exports = conn.execute(
            """SELECT COUNT(*) c FROM spectrum_exports
               WHERE batch_id=? AND status='已导出'""",
            (batch["id"],),
        ).fetchone()["c"]
        sealed = batch["status"] == "已封批"
        spectrum_ok = (exports >= 1) if sealed else True
        return {
            "batch_code": batch_code,
            "status": batch["status"],
            "generation": batch["generation"],
            "open_excursions": open_exc,
            "spectrum_exports": exports,
            "sealed": sealed,
            "excursion_closed": open_exc == 0,
            "spectrum_matches_seal": spectrum_ok,
            "proof": {
                "formula": "sealed => spectrum>=1 and open_excursions==0",
                "sealed": sealed,
                "open_excursions": open_exc,
                "exports": exports,
            },
        }