"""Independent invariant checks, written as plain queries so they do not share code with the triggers they audit."""


def check_capacity_invariants(conn):
    """Capacity-only checks (valid on any database, no batches needed). Returns violation strings."""
    bad = []
    q = conn.execute
    for r in q("""SELECT s.pool_id, s.seg_idx, s.used, s.cap,
                  COALESCE((SELECT SUM(a.size) FROM allocations a WHERE a.pool_id = s.pool_id
                            AND a.status IN ('TENTATIVE','CONFIRMED','BOARDED')
                            AND s.seg_idx >= a.board_idx AND s.seg_idx < a.alight_idx), 0) AS held
                  FROM segment_capacity s"""):
        if r["used"] != r["held"]:
            bad.append(f"{r['pool_id']}[{r['seg_idx']}]: used={r['used']} but live allocations hold {r['held']}")
        if r["used"] > r["cap"] or r["used"] < 0:
            bad.append(f"{r['pool_id']}[{r['seg_idx']}]: used={r['used']} outside 0..cap={r['cap']}")
    for r in q("SELECT group_id, COUNT(*) n FROM allocations WHERE status IN ('TENTATIVE','CONFIRMED','BOARDED') GROUP BY group_id HAVING n > 1"):
        bad.append(f"group {r['group_id']} has {r['n']} live allocations")
    for r in q("SELECT a.id FROM allocations a JOIN groups g USING (group_id) WHERE a.size <> g.size"):
        bad.append(f"allocation {r['id']} size differs from its group")
    return bad


def check_invariants(conn):
    """Capacity checks plus lifecycle checks (batches, cancelled vehicles, event log). Empty list = healthy."""
    bad = check_capacity_invariants(conn)
    q = conn.execute
    for r in q("""SELECT a.id FROM allocations a LEFT JOIN plan_batches b USING (batch_id)
                  WHERE a.status = 'TENTATIVE' AND (b.status IS NULL OR b.status <> 'PROPOSED')"""):
        bad.append(f"TENTATIVE allocation {r['id']} is not part of the pending batch")
    for r in q("""SELECT a.id FROM allocations a LEFT JOIN plan_batches b USING (batch_id)
                  WHERE a.status IN ('CONFIRMED','BOARDED') AND b.status IS NOT 'APPROVED'"""):
        bad.append(f"{r['id']}: CONFIRMED/BOARDED allocation whose batch was not approved")
    for r in q("""SELECT a.id FROM allocations a JOIN pools p USING (pool_id) JOIN vehicles v USING (vehicle_id)
                  WHERE v.status = 'CANCELLED' AND a.status IN ('TENTATIVE','CONFIRMED','BOARDED')"""):
        bad.append(f"allocation {r['id']} holds seats on a cancelled vehicle")
    seqs = [r[0] for r in q("SELECT seq FROM events ORDER BY seq")]
    if seqs != list(range(1, len(seqs) + 1)):
        bad.append("event seq is not contiguous")
    return bad


def state_dump(conn):
    """Deterministic snapshot of all projection tables, for replay-equivalence tests."""
    out = {}
    for t, order in (("vehicles", "vehicle_id"), ("pools", "pool_id"), ("segment_capacity", "pool_id, seg_idx"),
                     ("groups", "group_id"), ("allocations", "id"), ("plan_batches", "batch_id"),
                     ("batch_items", "batch_id, item_idx"), ("batch_footprint", "batch_id, pool_id, seg_lo"),
                     ("field_reports", "pool_id"), ("vacancy_claims", "pool_id, seg_idx"), ("field_conflicts", "id"),
                     ("disruptions", "seq"), ("notifications", "id"),
                     ("settings", "key"), ("group_holds", "group_id"), ("capacity_touches", "seq, pool_id, seg_idx")):
        out[t] = [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY {order}")]
    return out
