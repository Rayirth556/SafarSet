"""DB-level invariants, exercised with raw SQL (no application code in the way): the database itself must reject
over-allocation, and a multi-segment allocation must be all-or-nothing."""
import random
import sqlite3

import pytest

from safarset.db.conn import new_db
from safarset.db.invariants import check_capacity_invariants as check_invariants


def mini_db(caps, group_sizes):
    """One vehicle, one reserved pool with len(caps) segments, and groups g0.. of the given sizes (all affected)."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V','TRAIN','ALLOCATION','SIMULATED',0,'{}','{}')")
    c.execute("INSERT INTO pools VALUES ('P','V','RESERVED','SL',1,100,'SIMULATED',NULL,NULL,0)")
    for i, cap in enumerate(caps):
        c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap) VALUES ('P',?,?)", (i, cap))
    for i, size in enumerate(group_sizes):
        c.execute("INSERT INTO groups (group_id, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since,"
                  " requirements, attrs, affected) VALUES (?,?,1,1,'SL','CENTRAL','X',0,0,'{}','{}',1)", (f"g{i}", size))
    c.execute("INSERT INTO events (ts_wall, type, actor, payload) VALUES ('t','TEST','system','{}')")
    return c


def alloc(c, group, lo, hi, status="TENTATIVE", pool="P"):
    c.execute("INSERT INTO allocations (group_id, pool_id, board_idx, alight_idx, size, status, reason, created_seq, status_seq)"
              " VALUES (?,?,?,?,(SELECT size FROM groups WHERE group_id=?),?,'{}',1,1)", (group, pool, lo, hi, group, status))


def used(c):
    return [r["used"] for r in c.execute("SELECT used FROM segment_capacity ORDER BY seg_idx")]


def n_alloc(c):
    return c.execute("SELECT COUNT(*) FROM allocations").fetchone()[0]


def test_check_constraints_reject_negative_and_excess_used():
    c = mini_db([5, 5], [])
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE segment_capacity SET used = 6 WHERE seg_idx = 0")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE segment_capacity SET used = -1 WHERE seg_idx = 0")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used) VALUES ('P', 9, 2, 3)")
    assert used(c) == [0, 0]


def test_database_rejects_overselling():
    c = mini_db([5, 5, 5], [3, 3])
    alloc(c, "g0", 0, 3)
    assert used(c) == [3, 3, 3]
    with pytest.raises(sqlite3.IntegrityError):
        alloc(c, "g1", 0, 3)                      # 3 + 3 > 5
    assert used(c) == [3, 3, 3] and n_alloc(c) == 1
    assert check_invariants(c) == []


def test_multi_segment_allocation_is_all_or_nothing():
    for caps in ([4, 2, 4], [4, 4, 2], [2, 4, 4]):          # the short segment is first, middle or last
        c = mini_db(caps, [3])
        with pytest.raises(sqlite3.IntegrityError):
            alloc(c, "g0", 0, 3)
        assert used(c) == [0, 0, 0] and n_alloc(c) == 0, caps
        assert check_invariants(c) == []


def test_segments_are_reusable_along_the_route():
    c = mini_db([3, 3], [3, 3, 1])
    alloc(c, "g0", 0, 1)                           # A->B
    alloc(c, "g1", 1, 2)                           # B->C reuses the same seats
    assert used(c) == [3, 3]
    with pytest.raises(sqlite3.IntegrityError):
        alloc(c, "g2", 0, 2)                       # whole-route passenger no longer fits
    assert check_invariants(c) == []


def test_release_returns_every_segment():
    c = mini_db([3, 3, 3], [3, 3])
    alloc(c, "g0", 0, 3)
    c.execute("UPDATE allocations SET status = 'RELEASED' WHERE group_id = 'g0'")
    assert used(c) == [0, 0, 0]
    alloc(c, "g1", 0, 3)
    assert used(c) == [3, 3, 3]


def test_range_must_lie_inside_the_pool():
    c = mini_db([3, 3], [1])
    for lo, hi in ((0, 3), (2, 3), (1, 1), (2, 1)):
        with pytest.raises(sqlite3.IntegrityError):
            alloc(c, "g0", lo, hi)
    assert used(c) == [0, 0]


def test_size_must_match_group_and_group_has_one_live_allocation():
    c = mini_db([9, 9], [2])
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO allocations (group_id, pool_id, board_idx, alight_idx, size, status, reason, created_seq, status_seq)"
                  " VALUES ('g0','P',0,1,5,'TENTATIVE','{}',1,1)")
    alloc(c, "g0", 0, 1)
    with pytest.raises(sqlite3.IntegrityError):
        alloc(c, "g0", 1, 2)                       # second live allocation for the same group
    c.execute("UPDATE allocations SET status = 'RELEASED'")
    alloc(c, "g0", 1, 2)                           # fine once the first is released


def test_allocation_fields_are_immutable_and_transitions_are_legal():
    c = mini_db([9, 9], [2, 2])
    alloc(c, "g0", 0, 1)
    for col, val in (("size", 1), ("pool_id", "P"), ("board_idx", 1), ("alight_idx", 2), ("group_id", "g1")):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(f"UPDATE allocations SET {col} = ? WHERE group_id = 'g0'", (val,))
    for bad in ("BOARDED", "DISPLACED"):           # from TENTATIVE
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE allocations SET status = ? WHERE group_id = 'g0'", (bad,))
    c.execute("UPDATE allocations SET status = 'CONFIRMED'")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE allocations SET status = 'TENTATIVE'")
    c.execute("UPDATE allocations SET status = 'RELEASED'")
    for back in ("TENTATIVE", "CONFIRMED", "BOARDED"):    # terminal: no way to re-take seats without a new row
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE allocations SET status = ?", (back,))
    assert used(c) == [0, 0]


def test_event_log_is_append_only():
    c = mini_db([1], [])
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE events SET type = 'X'")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM events")


def test_fuzz_database_decisions_match_an_independent_model():
    """3000 random operations. A pure-Python model predicts whether each insert fits; the DB must agree on every
    one, and after every operation the stored counters must equal what the live allocations actually hold."""
    rng = random.Random(2026)
    nseg, ngroups = 6, 400
    caps = [rng.randint(8, 20) for _ in range(nseg)]
    sizes = [rng.randint(1, 5) for _ in range(ngroups)]
    c = mini_db(caps, sizes)
    live = {}                                      # group -> (lo, hi, status)
    model_used = [0] * nseg
    free_groups = [f"g{i}" for i in range(ngroups)]
    rejected = accepted = 0
    for step in range(3000):
        op = rng.random()
        if op < 0.5 and free_groups:
            g = free_groups[rng.randrange(len(free_groups))]
            lo = rng.randrange(nseg)
            hi = rng.randint(lo + 1, nseg)
            size = sizes[int(g[1:])]
            fits = all(model_used[i] + size <= caps[i] for i in range(lo, hi))
            try:
                alloc(c, g, lo, hi)
                assert fits, f"step {step}: DB accepted an oversell"
                for i in range(lo, hi):
                    model_used[i] += size
                live[g] = (lo, hi, "TENTATIVE")
                free_groups.remove(g)
                accepted += 1
            except sqlite3.IntegrityError:
                assert not fits, f"step {step}: DB rejected an allocation that fits"
                rejected += 1
        elif live:
            g = rng.choice(sorted(live))
            lo, hi, st = live[g]
            if op < 0.62 and st == "TENTATIVE":
                c.execute("UPDATE allocations SET status='CONFIRMED' WHERE group_id=? AND status='TENTATIVE'", (g,))
                live[g] = (lo, hi, "CONFIRMED")
            elif op < 0.64 and st == "CONFIRMED":
                c.execute("UPDATE allocations SET status='BOARDED' WHERE group_id=? AND status='CONFIRMED'", (g,))
                live[g] = (lo, hi, "BOARDED")
            elif op >= 0.64 and st != "BOARDED":
                c.execute("UPDATE allocations SET status=? WHERE group_id=? AND status=?",
                          ("RELEASED" if st == "TENTATIVE" else "DISPLACED", g, st))
                for i in range(lo, hi):
                    model_used[i] -= sizes[int(g[1:])]
                del live[g]
                # a released group may be planned again with a fresh row
                free_groups.append(g)
        assert used(c) == model_used, f"step {step}"
        assert check_invariants(c) == [], f"step {step}"
    assert accepted > 200 and rejected > 100, (accepted, rejected)   # the test exercised both outcomes
