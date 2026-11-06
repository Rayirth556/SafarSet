"""Constraint 2: two field sources can disagree about one segment's vacancy. The observation time decides which claim stands,
never arrival order, and disagreements are recorded for the operator instead of being resolved silently."""
import pytest

from safarset.db.conn import new_db
from safarset.db.invariants import check_invariants, state_dump
from safarset.events.apply import apply_event, replay
from safarset.events.reducers import Rejected
from safarset.sim.generator import generate


@pytest.fixture(scope="module")
def scenario():
    return generate(42)


@pytest.fixture()
def db(scenario):
    c = new_db()
    apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
    return c


@pytest.fixture()
def pool(db):
    return db.execute("SELECT pool_id FROM pools WHERE kind = 'RESERVED' ORDER BY pool_id LIMIT 1").fetchone()["pool_id"]


def claim(c, pool, vacancy, observed_at=None, by="chart"):
    apply_event(c, "VACANCY_UPDATE", "field", {"pool_id": pool, "from_seg": 0, "to_seg": 1, "vacancy": vacancy,
                                              "observed_at": observed_at, "reported_by": by})


def cap(c, pool):
    return c.execute("SELECT cap FROM segment_capacity WHERE pool_id = ? AND seg_idx = 0", (pool,)).fetchone()["cap"]


def conflicts(c):
    return [dict(r) for r in c.execute("SELECT * FROM field_conflicts ORDER BY id").fetchall()]


def test_older_observation_arriving_last_is_refused(db, pool):
    claim(db, pool, 4, observed_at=850, by="chart")
    claim(db, pool, 2, observed_at=855, by="TTE")             # newer observation, applied
    claim(db, pool, 9, observed_at=845, by="chart")           # stale: observed before the 855 reading, arrives last
    assert cap(db, pool) == 2
    [c] = conflicts(db)
    assert c["outcome"] == "STALE_IGNORED"
    assert (c["kept_value"], c["kept_observed_at"]) == (2, 855)
    assert (c["other_value"], c["other_observed_at"]) == (9, 845)
    assert check_invariants(db) == []


def test_same_observation_time_keeps_the_lower_value_in_either_order(scenario):
    results = []
    for order in ([(6, "chart"), (3, "TTE")], [(3, "TTE"), (6, "chart")]):
        c = new_db()
        apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
        pool = c.execute("SELECT pool_id FROM pools WHERE kind = 'RESERVED' ORDER BY pool_id LIMIT 1").fetchone()["pool_id"]
        for vacancy, by in order:
            claim(c, pool, vacancy, observed_at=860, by=by)
        results.append(cap(c, pool))
        [row] = conflicts(c)
        assert row["outcome"] == "CONFLICT" and row["kept_value"] == 3
        assert check_invariants(c) == []
    assert results == [3, 3]


def test_undated_claim_never_overrides_a_dated_one(db, pool):
    claim(db, pool, 4, observed_at=850)
    claim(db, pool, 9)                                        # no observation time
    assert cap(db, pool) == 4
    [c] = conflicts(db)
    assert c["outcome"] == "UNDATED_IGNORED"


def test_undated_claims_keep_the_old_arrival_order_behaviour(db, pool):
    claim(db, pool, 5)
    claim(db, pool, 7)
    assert cap(db, pool) == 7
    assert conflicts(db) == []


def test_conflict_history_replays_identically(db, pool):
    claim(db, pool, 4, observed_at=850)
    claim(db, pool, 2, observed_at=855, by="TTE")
    claim(db, pool, 9, observed_at=845)
    claim(db, pool, 1, observed_at=855, by="TTE")
    dst = new_db()
    replay(db, dst)
    assert state_dump(dst) == state_dump(db)
    assert cap(dst, pool) == cap(db, pool) == 1
    assert check_invariants(dst) == []


def test_operator_reviews_a_conflict_once(db, pool):
    claim(db, pool, 4, observed_at=850)
    claim(db, pool, 9)                                        # undated: refused, recorded
    [c] = conflicts(db)
    apply_event(db, "CONFLICT_RESOLVED", "operator", {"conflict_id": c["id"], "note": "chart is wrong, TTE was checked"})
    [after] = conflicts(db)
    assert after["resolved"] == 1 and after["resolved_note"] == "chart is wrong, TTE was checked" and after["resolved_seq"]
    with pytest.raises(Rejected, match="already reviewed"):
        apply_event(db, "CONFLICT_RESOLVED", "operator", {"conflict_id": c["id"], "note": "again, same note"})
    with pytest.raises(Rejected, match="unknown field conflict"):
        apply_event(db, "CONFLICT_RESOLVED", "operator", {"conflict_id": 999, "note": "no such conflict"})


def test_review_needs_a_note(db, pool):
    claim(db, pool, 4, observed_at=850)
    claim(db, pool, 9)
    with pytest.raises(Rejected, match="requires a note"):
        apply_event(db, "CONFLICT_RESOLVED", "operator", {"conflict_id": 1, "note": "ok"})


def test_conflict_review_is_replay_safe(db, pool):
    claim(db, pool, 4, observed_at=850)
    claim(db, pool, 9)
    apply_event(db, "CONFLICT_RESOLVED", "operator", {"conflict_id": 1, "note": "reviewed after the stale report"})
    dst = new_db()
    replay(db, dst)
    assert state_dump(dst) == state_dump(db)
