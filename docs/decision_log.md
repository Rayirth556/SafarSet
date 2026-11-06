# SafarSet Architecture Decision Log: Passenger Prioritisation

## 1. Context & Motivation
During major transport disruptions (e.g., train cancellations, major infrastructure closures), demand vastly exceeds short-term recovery capacity. Prioritising passenger groups fairly, transparently, and safely requires an explainable multi-layered model that respects hard operational constraints while preventing starvation.

This document records the architectural and policy decisions implemented for SafarSet's improved passenger prioritisation system.

---

## 2. Implemented Decisions

### Decision 1: 4-Layer Hybrid Prioritisation Architecture
We adopted a four-tier architecture separating constraints from soft preferences:
1. **Layer 1: Hard Eligibility & Feasibility Constraints**
   - Route feasibility, destination reachability, check-in deadlines, wheelchair accessibility, and segment capacity.
   - Hard constraints must NEVER be overridden by a high priority score.
2. **Layer 2: Configurable Priority Tiers**
   - **Tier 0 – Critical**: Verified medical emergencies and explicitly operator-verified critical cases.
   - **Tier 1 – High Priority**: Passengers requiring additional assistance (disability assistance, wheelchair assistance, elderly requiring assistance, unaccompanied minors).
   - **Tier 2 – Standard**: All other eligible passengers.
   - *Crucial Rule:* Healthy elderly passengers without assistance requirements are classified as Tier 2, with age available as a soft scoring factor to prevent age discrimination.
3. **Layer 3: Weighted Scoring Within Tiers**
   - Normalized 0–100 factor scores weighted according to operator policy:
     - Waiting time / delay: 30
     - Age vulnerability: 20
     - Journey urgency: 25
     - Additional assistance: 15
     - Disruption impact: 10
     - Total: 100
   - Linear, uncapped waiting-time ageing: `effective_score = base_score + (waiting_minutes × ageing_rate)`.
4. **Layer 4: Group Integrity & Priority Inheritance**
   - Passenger groups are never split.
   - Group tier = highest-priority tier among its members.
   - Group score = average score of members belonging to that highest-priority tier (`group_score = average(member_scores in highest_priority_tier)`).
   - Anti-abuse companion validation: oversized groups (> 6 members) require operator verification to inherit Tier 0 or Tier 1 priority.

### Decision 2: Starvation Prevention Via Auditable Wait Escalation
- A Tier 2 passenger group waiting beyond a configurable threshold (default: 120 minutes) is promoted to Tier 1.
- Wait escalation NEVER promotes groups to Tier 0 (reserved strictly for verified medical/critical cases).
- Escalation is recorded as an auditable `PASSENGER_ESCALATED` event in the append-only event log.
- Escalation state is deterministic and idempotent; repeated processing never produces duplicate events.

### Decision 3: Separation of Reserved PNR Passengers, UTS Unreserved Passengers, and Walk-on Demand
- **Individually Allocated**: Both reserved PNR holders and ticketed unreserved passengers (UTS) are individually represented in the `groups` table and allocated seats. Reserved passengers are NOT automatically ranked above unreserved passengers unless an explicit authority policy mandates it.
- **Walk-on Demand**: Estimated unregistered walk-on demand contributes strictly to buffer planning and load estimation, NEVER to individual group allocations. Actual walk-on boarding counts reported by conductors via `LOAD_REPORT` directly consume capacity.

### Decision 4: Concurrency & Transactional Capacity Safety
- All state mutations and allocation decisions execute within explicit SQLite `BEGIN IMMEDIATE` transactions.
- Table-level CHECK constraints (`used <= cap`, `used >= 0`) enforced by SQLite triggers guarantee statement-level and journey-level atomicity.
- Multi-segment allocations are all-or-nothing: if any segment cannot be reserved, the entire statement rolls back.

---

## 3. Configurable Policy Choices (`config/priority_policy.json`)

All operational policy settings are centralized and validated on startup via Pydantic:
- `tiers`: definitions, descriptions, and rank hierarchy (0, 1, 2).
- `factor_weights`: weights for waiting time, age vulnerability, urgency, assistance, and disruption impact (sum = 100).
- `age_scoring`: thresholds for infants (<5), children (<12), seniors (>=60), and elderly requiring assistance (>=75).
- `ageing`: `rate_per_minute` (default: 0.1 pts/min = 6 pts/hr), linear, uncapped.
- `escalation`: `enabled`, `tier_2_max_wait_minutes` (default: 120), `escalate_to_tier` (1), `allow_escalation_to_tier_0` (false).
- `group_policy`: `strategy` ("highest_tier_member_average"), `companion_verification_required`, `max_unverified_group_size` (6).
- `reserved_vs_unreserved`: `auto_rank_reserved_above_unreserved` (false), `reserved_priority_bonus` (0.0).
- `walk_on_policy`: `individually_allocated` (false), `contribute_to_buffers` (true), `deduct_actual_boardings` (true).

---

## 4. Remaining Unresolved Policy Decisions

1. **Transport Authority Specific Precedence**: Different rail and transit authorities (e.g., Indian Railways vs. Transport for London vs. SNCF) have distinct legal frameworks regarding whether reserved ticket holders take absolute precedence over unreserved ticket holders during cancellations. The policy is configurable (`auto_rank_reserved_above_unreserved`), but final deployment requires signed operator authority sign-off.
2. **Medical Emergency Verification Workflows**: Currently, Tier 0 requires verified flags (`medical_emergency`, `verified_critical`). Physical station verification protocols (doctor certificates, station master stamp) need operator workflow definition outside the software platform.
3. **Escalation Threshold Under Severe Vehicle Deficits**: If recovery vehicles are insufficient for all Tier 1 and escalated Tier 2 passengers, the maximum wait threshold may need dynamic throttling to avoid flood-promoting all Tier 2 passengers into Tier 1 simultaneously.

---

## 5. Limitations

- **Heuristic Greedy Allocator**: In accordance with system requirements, the allocator uses an explainable, deterministic greedy approach with bounded reshuffling rather than an integer linear programming (ILP) solver. This ensures polynomial-time predictability and transparency at the cost of global optimality.
- **Unverified Companion Edge Cases**: Companion abuse prevention relies on group size thresholds (<= 6) and explicit flags. In the absence of digital identity verification (e.g., family ID or Aadhaar linkage), operator oversight remains necessary for large groups.
- **Single-Station Scope in Demo**: The hackathon demo simulates passengers departing Chennai Central; regional multi-station boarding cascades use simulated check-in and transit times.
