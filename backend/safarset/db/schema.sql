-- SafarSet schema (SQLite). The database, not application code, enforces the capacity invariants:
--   * segment_capacity: CHECK (used >= 0), CHECK (used <= cap)
--   * used is maintained ONLY by triggers on allocations, in the same statement as the allocation write,
--     so a multi-segment allocation either updates every segment or none (statement atomicity).
-- Event log is append-only (triggers). State tables are projections written by reducers in the same transaction.

-- ---------------------------------------------------------------- event log
CREATE TABLE events (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_sim        INTEGER,                         -- scenario clock, minutes of day (NULL if not applicable)
    ts_wall       TEXT NOT NULL,
    type          TEXT NOT NULL,
    actor         TEXT NOT NULL CHECK (actor IN ('system','operator','field','sim')),
    payload       TEXT NOT NULL CHECK (json_valid(payload)),
    causation_seq INTEGER
);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

-- Which event is being applied right now (read by triggers that record capacity touches).
CREATE TABLE ctx (id INTEGER PRIMARY KEY CHECK (id = 1), current_seq INTEGER NOT NULL);
INSERT INTO ctx VALUES (1, 0);

-- ---------------------------------------------------------------- reference + scenario
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL CHECK (json_valid(value)),
    version    INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);

CREATE TABLE places (
    place_id TEXT PRIMARY KEY, name TEXT NOT NULL, rail TEXT NOT NULL CHECK (json_valid(rail)),
    transfer_only INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE vehicles (
    vehicle_id  TEXT PRIMARY KEY,
    mode        TEXT NOT NULL CHECK (mode IN ('TRAIN','BUS')),
    role        TEXT NOT NULL CHECK (role IN ('ALLOCATION','TRANSFER_LEG','TO_BE_CANCELLED')),
    label       TEXT NOT NULL,                     -- REAL / REAL_DRAFT_UNVERIFIED / SIMULATED / ...
    status      TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN ('SCHEDULED','CANCELLED')),
    delay_min   INTEGER NOT NULL DEFAULT 0,
    depart_min  INTEGER NOT NULL,
    route_id    TEXT, train_no TEXT, name TEXT,
    boarding    TEXT NOT NULL CHECK (json_valid(boarding)),
    attrs       TEXT NOT NULL CHECK (json_valid(attrs))
);

CREATE TABLE vehicle_stops (
    vehicle_id TEXT NOT NULL REFERENCES vehicles(vehicle_id),
    seq INTEGER NOT NULL, stop_id TEXT NOT NULL, stop_name TEXT,
    serves_places TEXT NOT NULL CHECK (json_valid(serves_places)),
    arr_min INTEGER, dep_min INTEGER NOT NULL,
    PRIMARY KEY (vehicle_id, seq)
) WITHOUT ROWID;

CREATE TABLE pools (
    pool_id   TEXT PRIMARY KEY,
    vehicle_id TEXT NOT NULL REFERENCES vehicles(vehicle_id),
    kind      TEXT NOT NULL CHECK (kind IN ('RESERVED','UNRESERVED')),
    class     TEXT NOT NULL,
    coaches   INTEGER NOT NULL, nominal INTEGER NOT NULL CHECK (nominal >= 0),
    capacity_label TEXT NOT NULL,
    buffer_mode TEXT,                              -- NULL for reserved (exact vacancy, no buffer)
    buffer_pct  REAL CHECK (buffer_pct IS NULL OR (buffer_pct >= 0 AND buffer_pct <= 1)),
    walkon_expected INTEGER NOT NULL DEFAULT 0,
    CHECK ((kind = 'RESERVED' AND buffer_mode IS NULL AND buffer_pct IS NULL)
        OR (kind = 'UNRESERVED' AND buffer_mode IS NOT NULL AND buffer_pct IS NOT NULL))
);

-- Capacity per (pool, segment). cap = allocatable seats (exact vacancy for reserved; floor(nominal*buffer)-committed
-- for unreserved). used = seats held by TENTATIVE/CONFIRMED/BOARDED allocations, maintained by triggers.
CREATE TABLE segment_capacity (
    pool_id TEXT NOT NULL REFERENCES pools(pool_id),
    seg_idx INTEGER NOT NULL CHECK (seg_idx >= 0),
    cap     INTEGER NOT NULL CHECK (cap >= 0),
    used    INTEGER NOT NULL DEFAULT 0 CHECK (used >= 0),
    committed_other INTEGER NOT NULL DEFAULT 0 CHECK (committed_other >= 0),
    PRIMARY KEY (pool_id, seg_idx),
    CHECK (used <= cap)
) WITHOUT ROWID;

CREATE TABLE capacity_touches (
    seq INTEGER NOT NULL, pool_id TEXT NOT NULL, seg_idx INTEGER NOT NULL,
    PRIMARY KEY (seq, pool_id, seg_idx)
) WITHOUT ROWID;

CREATE TRIGGER seg_touch AFTER UPDATE ON segment_capacity
BEGIN
    INSERT OR IGNORE INTO capacity_touches (seq, pool_id, seg_idx)
    SELECT current_seq, NEW.pool_id, NEW.seg_idx FROM ctx;
END;

CREATE TABLE groups (
    group_id TEXT PRIMARY KEY,
    pnr TEXT UNIQUE,
    size INTEGER NOT NULL CHECK (size > 0),
    reserved INTEGER NOT NULL CHECK (reserved IN (0,1)),
    known INTEGER NOT NULL CHECK (known IN (0,1)),
    class TEXT NOT NULL,
    board_place TEXT NOT NULL, dest_place TEXT NOT NULL,
    on_vehicle_id TEXT REFERENCES vehicles(vehicle_id),
    booking_time INTEGER NOT NULL, waiting_since INTEGER NOT NULL,
    requirements TEXT NOT NULL CHECK (json_valid(requirements)),
    attrs TEXT NOT NULL CHECK (json_valid(attrs)),     -- flexible: extra fields need no migration
    affected INTEGER NOT NULL DEFAULT 0 CHECK (affected IN (0,1))
);

-- ---------------------------------------------------------------- plans and allocations
CREATE TABLE plan_batches (
    batch_id    TEXT PRIMARY KEY,
    status      TEXT NOT NULL CHECK (status IN ('PROPOSED','APPROVED','SUPERSEDED')),
    cause       TEXT NOT NULL DEFAULT 'REPLAN',    -- why the batch exists: an event type, WEIGHTS_RERUN, MANUAL_REPLAN, OPERATOR_OVERRIDE
    base_seq    INTEGER NOT NULL,                  -- last event seen by the planner
    proposed_seq INTEGER NOT NULL,
    approved_seq INTEGER,
    summary     TEXT NOT NULL CHECK (json_valid(summary))
);
-- At most one pending batch.
CREATE UNIQUE INDEX one_pending_batch ON plan_batches((1)) WHERE status = 'PROPOSED';

CREATE TABLE batch_footprint (
    batch_id TEXT NOT NULL REFERENCES plan_batches(batch_id),
    pool_id  TEXT NOT NULL, seg_lo INTEGER NOT NULL, seg_hi INTEGER NOT NULL   -- segments [seg_lo, seg_hi)
);

CREATE TABLE batch_items (
    batch_id TEXT NOT NULL REFERENCES plan_batches(batch_id),
    item_idx INTEGER NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('PLACED','NEWLY_PLACED','DISPLACED','RESHUFFLED','UNRESOLVED')),
    group_id TEXT NOT NULL REFERENCES groups(group_id),
    detail   TEXT NOT NULL CHECK (json_valid(detail)),
    PRIMARY KEY (batch_id, item_idx)
);

CREATE TABLE allocations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    TEXT NOT NULL REFERENCES groups(group_id),
    pool_id     TEXT NOT NULL REFERENCES pools(pool_id),
    board_idx   INTEGER NOT NULL CHECK (board_idx >= 0),
    alight_idx  INTEGER NOT NULL,                  -- allocation uses segments [board_idx, alight_idx)
    size        INTEGER NOT NULL CHECK (size > 0),
    status      TEXT NOT NULL CHECK (status IN ('TENTATIVE','CONFIRMED','BOARDED','RELEASED','DISPLACED')),
    batch_id    TEXT REFERENCES plan_batches(batch_id),
    score       REAL NOT NULL DEFAULT 0,
    reason      TEXT NOT NULL CHECK (json_valid(reason)),     -- machine-readable "why"
    created_seq INTEGER NOT NULL,
    status_seq  INTEGER NOT NULL,
    status_reason TEXT CHECK (status_reason IS NULL OR json_valid(status_reason)),
    CHECK (alight_idx > board_idx)
);
CREATE INDEX alloc_group ON allocations(group_id);
CREATE INDEX alloc_pool ON allocations(pool_id, status);
-- A group holds at most one live allocation.
CREATE UNIQUE INDEX one_live_alloc ON allocations(group_id) WHERE status IN ('TENTATIVE','CONFIRMED','BOARDED');

CREATE TRIGGER alloc_before_insert BEFORE INSERT ON allocations
BEGIN
    SELECT RAISE(ABORT, 'allocation: segment range outside pool')
     WHERE (SELECT COUNT(*) FROM segment_capacity
             WHERE pool_id = NEW.pool_id AND seg_idx >= NEW.board_idx AND seg_idx < NEW.alight_idx)
           <> NEW.alight_idx - NEW.board_idx;
    SELECT RAISE(ABORT, 'allocation: size must equal group size')
     WHERE NEW.size <> (SELECT size FROM groups WHERE group_id = NEW.group_id);
    SELECT RAISE(ABORT, 'allocation: must be inserted as TENTATIVE or CONFIRMED')
     WHERE NEW.status NOT IN ('TENTATIVE','CONFIRMED');
END;

-- Taking seats: one UPDATE over all segments of the range. If any segment would break CHECK (used <= cap)
-- the whole statement (including the allocation insert) is rolled back: all segments or none.
CREATE TRIGGER alloc_after_insert AFTER INSERT ON allocations
BEGIN
    UPDATE segment_capacity SET used = used + NEW.size
     WHERE pool_id = NEW.pool_id AND seg_idx >= NEW.board_idx AND seg_idx < NEW.alight_idx;
END;

CREATE TRIGGER alloc_immutable BEFORE UPDATE OF group_id, pool_id, board_idx, alight_idx, size ON allocations
BEGIN SELECT RAISE(ABORT, 'allocation: group, pool, segments and size are immutable'); END;

CREATE TRIGGER alloc_transition BEFORE UPDATE OF status ON allocations
WHEN NEW.status <> OLD.status AND NOT (
       (OLD.status = 'TENTATIVE' AND NEW.status IN ('CONFIRMED','RELEASED'))
    OR (OLD.status = 'CONFIRMED' AND NEW.status IN ('BOARDED','DISPLACED','RELEASED')))
BEGIN SELECT RAISE(ABORT, 'allocation: illegal status transition'); END;

-- Giving seats back (the only way a live allocation stops holding capacity).
CREATE TRIGGER alloc_after_status AFTER UPDATE OF status ON allocations
WHEN OLD.status IN ('TENTATIVE','CONFIRMED','BOARDED') AND NEW.status IN ('RELEASED','DISPLACED')
BEGIN
    UPDATE segment_capacity SET used = used - NEW.size
     WHERE pool_id = NEW.pool_id AND seg_idx >= NEW.board_idx AND seg_idx < NEW.alight_idx;
END;

-- ---------------------------------------------------------------- field, disruptions, notifications
CREATE TABLE field_reports (
    pool_id TEXT PRIMARY KEY REFERENCES pools(pool_id),
    vehicle_id TEXT NOT NULL, level TEXT NOT NULL CHECK (level IN ('NORMAL','FULL','OVERCROWDED')),
    count INTEGER, reported_seq INTEGER NOT NULL
);

CREATE TABLE disruptions (
    seq INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('TRAIN_CANCELLED','TRAIN_DELAYED','ROAD_CLOSED')),
    vehicle_id TEXT, route_id TEXT, detail TEXT NOT NULL CHECK (json_valid(detail))
);

-- Operator removed the group from automatic planning (OPERATOR_OVERRIDE / UNASSIGN) until RESUME_AUTO or ASSIGN.
CREATE TABLE group_holds (
    group_id TEXT PRIMARY KEY REFERENCES groups(group_id), reason TEXT NOT NULL, seq INTEGER NOT NULL
);

CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL REFERENCES groups(group_id),
    channel TEXT NOT NULL, lang TEXT NOT NULL, message TEXT NOT NULL, reason TEXT,
    sent_seq INTEGER NOT NULL
);

-- ---------------------------------------------------------------- read-side views (projections)
CREATE VIEW v_segment_load AS
SELECT s.pool_id, s.seg_idx, s.cap, s.used, s.cap - s.used AS free,
       COALESCE((SELECT SUM(a.size) FROM allocations a WHERE a.pool_id = s.pool_id AND a.status = 'CONFIRMED'
                  AND s.seg_idx >= a.board_idx AND s.seg_idx < a.alight_idx), 0) AS confirmed,
       COALESCE((SELECT SUM(a.size) FROM allocations a WHERE a.pool_id = s.pool_id AND a.status = 'BOARDED'
                  AND s.seg_idx >= a.board_idx AND s.seg_idx < a.alight_idx), 0) AS boarded,
       COALESCE((SELECT SUM(a.size) FROM allocations a WHERE a.pool_id = s.pool_id AND a.status = 'TENTATIVE'
                  AND s.seg_idx >= a.board_idx AND s.seg_idx < a.alight_idx), 0) AS tentative
FROM segment_capacity s;

-- Group lifecycle state: BOARDED / CONFIRMED / TENTATIVE, else UNRESOLVED (affected, no live allocation).
CREATE VIEW v_group_state AS
SELECT g.group_id, g.size, g.affected,
       CASE WHEN g.affected = 0 THEN 'UNAFFECTED'
            ELSE COALESCE((SELECT a.status FROM allocations a WHERE a.group_id = g.group_id
                            AND a.status IN ('TENTATIVE','CONFIRMED','BOARDED')), 'UNRESOLVED') END AS state
FROM groups g;
