"""同探头建批争用：单轨互斥 + 争用痕（甲路径定稿）。

三红夹具：
  甲：同探头两笔正式批次串行提交，第二笔零增拒建且必须写争用痕；
  乙：同探头两笔正式批次并发提交，只允许一笔成功，拒绝侧不得留正式批次；
  争用：双人同探头各打一次，恰好一胜一负且争用痕视图可见。

五处同源口径（争用痕视图 / 建批视图 / 仓间视图 / 封批视图 / 对账视图）：
同一在线探头任一时点最多一笔正式在批（状态不在 已封批/作废）。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db
from locks import ACTIVE_BATCH_PARAMS, ACTIVE_BATCH_WHERE

# 与生产口径同源：夹具不得自造在批定义
ACTIVE_CLAUSE = ACTIVE_BATCH_WHERE
ACTIVE_PARAMS = ACTIVE_BATCH_PARAMS


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user: str = "admin") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _fresh_probe(c: TestClient, h: dict, sealable: bool = False) -> dict:
    """挑一枚当前没有任何在批的在线探头（避免种子批次干扰）。

    sealable=True 时再要求校准未到期，便于后续封批收口核验。
    """
    probes = c.get("/api/probes", headers=h).json()["items"]
    chambers = {x["id"]: x for x in c.get("/api/chambers", headers=h).json()["items"]}
    today = "2026-11-23"
    with connect() as conn:
        for p in probes:
            n = conn.execute(
                f"SELECT COUNT(*) c FROM temp_batches WHERE probe_id=? AND {ACTIVE_CLAUSE}",
                (p["id"], *ACTIVE_PARAMS),
            ).fetchone()["c"]
            if n != 0 or p["online_status"] != "在线":
                continue
            if sealable and p["calibration_due"] < today:
                continue
            ch = chambers[p["chamber_id"]]
            p["_band"] = (float(ch["target_min"]), float(ch["target_max"]))
            return p
    pytest.fail("种子中无空闲在线探头，夹具前提不成立")


def _payload(probe: dict, code: str) -> dict:
    lo, hi = probe["_band"]
    mid = round((lo + hi) / 2.0, 2)
    return {
        "chamber_id": probe["chamber_id"],
        "probe_id": probe["id"],
        "cargo_ref": f"争用货载-{code}",
        "batch_code": code,
        "temp_points": [
            {"t": "08:00", "c": mid},
            {"t": "09:00", "c": round(mid + 0.4, 2)},
        ],
    }


def _active_batches_for_probe(probe_id: int) -> int:
    with connect() as conn:
        return conn.execute(
            f"SELECT COUNT(*) c FROM temp_batches WHERE probe_id=? AND {ACTIVE_CLAUSE}",
            (probe_id, *ACTIVE_PARAMS),
        ).fetchone()["c"]


def _probe_contention_rows(c: TestClient, h: dict, probe_id: int) -> list:
    rows = c.get("/api/contention", headers=h).json()["items"]
    key = f"probe:{probe_id}"
    return [r for r in rows if r["lock_key"] == key]


def test_path_a_second_formal_batch_rejected_with_contention_trace():
    """甲：已有在批则第二笔正式批次零增拒建，且须写争用痕。"""
    c = TestClient(app)
    h = _auth(c)
    probe = _fresh_probe(c, h)

    first = c.post("/api/batches", headers=h, json=_payload(probe, "TB-CONT-A1"))
    assert first.status_code == 200, first.text

    second = c.post(
        "/api/batches", headers=h, json=_payload(probe, "TB-CONT-A2")
    )
    assert second.status_code == 409, second.text

    # 零增：同探头仍只有一笔正式在批，第二笔编码根本未落库
    assert _active_batches_for_probe(probe["id"]) == 1
    with connect() as conn:
        assert conn.execute(
            "SELECT id FROM temp_batches WHERE batch_code=?", ("TB-CONT-A2",)
        ).fetchone() is None

    # 争用痕：争用痕视图必须能按探头锁键查到
    traces = _probe_contention_rows(c, h, probe["id"])
    assert len(traces) == 1
    assert traces[0]["action"] == "争用"


def test_path_b_no_dual_formal_batch_queued_intent_must_not_promote_silently():
    """乙：并发两笔落同一探头，禁止双正式批并存；被拒侧不得静默排队/晋升。"""
    c0 = TestClient(app)
    h0 = _auth(c0)
    probe = _fresh_probe(c0, h0)

    results: list = []
    barrier = threading.Barrier(2)

    def worker(user: str, code: str) -> None:
        c = TestClient(app)
        h = _auth(c, user)
        barrier.wait()
        r = c.post("/api/batches", headers=h, json=_payload(probe, code))
        results.append((user, r.status_code))

    attempts = {"admin": "TB-CONT-B1", "ops": "TB-CONT-B2"}
    t1 = threading.Thread(target=worker, args=("admin", attempts["admin"]))
    t2 = threading.Thread(target=worker, args=("ops", attempts["ops"]))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    statuses = sorted(s for _, s in results)
    assert statuses == [200, 409], results

    # 不允许双正式批：同探头只有一笔在批
    assert _active_batches_for_probe(probe["id"]) == 1

    # 拒绝侧零增：败者批次编码不存在任何形态的正式批次
    loser_codes = [attempts[user] for user, status in results if status != 200]
    with connect() as conn:
        for code in loser_codes:
            assert conn.execute(
                "SELECT id FROM temp_batches WHERE batch_code=?", (code,)
            ).fetchone() is None
        # 不允许影子/排队形态的批次冒充在批：状态集合只能是既有业务状态
        rows = conn.execute(
            "SELECT DISTINCT status FROM temp_batches WHERE probe_id=?",
            (probe["id"],),
        ).fetchall()
        assert all(
            r["status"] in ("草稿", "已入库", "超温处理中", "已封批", "作废")
            for r in rows
        )

    # 争用痕同样要留下（并发拒绝也得有痕）
    c = TestClient(app)
    h = _auth(c)
    assert len(_probe_contention_rows(c, h, probe["id"])) >= 1


def test_contention_two_users_same_probe_each_attempt_one_winner():
    """争用：双人同探头各打一次，恰好一胜一负，争用痕视图可查。"""
    c = TestClient(app)
    h_admin = _auth(c, "admin")
    h_ops = _auth(c, "ops")
    probe = _fresh_probe(c, h_admin)

    r1 = c.post("/api/batches", headers=h_admin, json=_payload(probe, "TB-CONT-U1"))
    r2 = c.post("/api/batches", headers=h_ops, json=_payload(probe, "TB-CONT-U2"))
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 409, r2.text

    assert _active_batches_for_probe(probe["id"]) == 1
    traces = _probe_contention_rows(c, h_admin, probe["id"])
    assert len(traces) == 1
    assert traces[0]["actor"] == "ops"


def test_closure_five_views_single_source_after_seal_releases_probe():
    """收口：封批后探头释放；五处视图同源，且永不出现同探头双正式批。"""
    c = TestClient(app)
    h = _auth(c)
    probe = _fresh_probe(c, h, sealable=True)

    created = c.post("/api/batches", headers=h, json=_payload(probe, "TB-CLOSE-1"))
    assert created.status_code == 200, created.text
    bid = created.json()["id"]
    assert _active_batches_for_probe(probe["id"]) == 1

    # 封批前：建批视图/探头视图/仓间视图/对账视图 均显示一笔正式在批
    listed = [b for b in c.get("/api/batches", headers=h).json()["items"]
              if b["probe_id"] == probe["id"] and b["status"] in ACTIVE_PARAMS]
    assert len(listed) == 1

    probe_view = c.get(f"/api/probes/{probe['id']}", headers=h).json()
    assert len(probe_view["active_batches"]) == 1
    assert probe_view["single_track_violations"] == 0

    chamber_view = c.get(f"/api/chambers/{probe['chamber_id']}", headers=h).json()
    slot = next(p for p in chamber_view["probes"] if p["id"] == probe["id"])
    assert slot["active_batches"] == 1
    assert slot["single_track_violations"] == 0

    recon = c.get("/api/reconcile", headers=h).json()
    track = next(t for t in recon["probe_tracks"] if t["probe_id"] == probe["id"])
    assert track["active_batches"] == 1
    assert track["single_track_ok"] is True
    assert recon["summary"]["probe_single_track"]["all_single_track"] is True
    assert recon["summary"]["probe_single_track"]["violation_probes"] == 0

    # 封批视图收口
    seal = c.post("/api/seals", headers=h, json={"batch_id": bid})
    assert seal.status_code == 200, seal.text
    assert seal.json()["status"] == "已封批"

    # 收口后：正式在批归零，探头单轨释放
    assert _active_batches_for_probe(probe["id"]) == 0
    probe_view2 = c.get(f"/api/probes/{probe['id']}", headers=h).json()
    assert probe_view2["active_batches"] == []
    slot2 = next(
        p for p in c.get(f"/api/chambers/{probe['chamber_id']}", headers=h).json()["probes"]
        if p["id"] == probe["id"]
    )
    assert slot2["active_batches"] == 0

    # 同探头再建一笔正式批应被允许（前批已收口，不是双正式批）
    again = c.post("/api/batches", headers=h, json=_payload(probe, "TB-CLOSE-2"))
    assert again.status_code == 200, again.text
    assert _active_batches_for_probe(probe["id"]) == 1

    # 争用痕视图：封批前那次双人争用仍可按探头过滤
    filtered = c.get(f"/api/contention?probe_id={probe['id']}", headers=h).json()["items"]
    assert all(r["lock_key"] == f"probe:{probe['id']}" for r in filtered)


def test_draft_does_not_occupy_probe_single_track():
    """草稿不是正式批次：同探头草稿之上仍可建一笔正式在批。"""
    c = TestClient(app)
    h = _auth(c)
    probe = _fresh_probe(c, h)
    draft = c.post(
        "/api/batches",
        headers=h,
        json={
            "chamber_id": probe["chamber_id"],
            "probe_id": probe["id"],
            "cargo_ref": "草稿意图",
            "batch_code": "TB-DRAFT-1",
            "temp_points": [],
        },
    )
    assert draft.status_code == 200 and draft.json()["status"] == "草稿"
    formal = c.post("/api/batches", headers=h, json=_payload(probe, "TB-FORMAL-1"))
    assert formal.status_code == 200, formal.text
    assert _active_batches_for_probe(probe["id"]) == 1
    # 第二笔正式批仍被单轨拒绝且有痕
    second = c.post("/api/batches", headers=h, json=_payload(probe, "TB-FORMAL-2"))
    assert second.status_code == 409
    assert len(_probe_contention_rows(c, h, probe["id"])) == 1
