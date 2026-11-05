import random

from safarset.scoring.interface import ScoreContext
from safarset.scoring.stub import FACTORS, default_weights, score

W = default_weights()


def group(**kw):
    attrs = {"ages": [30], "disability": False, "pregnant": False, "deadline_min": None, **kw.pop("attrs", {})}
    return {"size": len(attrs["ages"]), "reserved": True, "waiting_since": 840, "attrs": attrs, **kw}


def sc(g, now=840):
    return score(g, ScoreContext(now_min=now, weights=W))


def test_weights_come_from_the_config_file():
    assert set(W) == {"medical_disability", "senior_60_plus", "child_or_pregnant", "hard_deadline", "reserved_pnr", "ageing_per_hour"}


def test_breakdown_is_complete_and_sums_to_total():
    r = sc(group(attrs={"ages": [70], "disability": True, "deadline_min": 1000}), now=900)
    assert [f for f, _ in r["breakdown"]] == FACTORS
    assert abs(sum(p for _, p in r["breakdown"]) - r["total"]) < 1e-6


def test_each_factor_scores_its_weight():
    base = sc(group())["total"]
    assert sc(group(attrs={"ages": [65]}))["total"] - base == W["senior_60_plus"]
    assert sc(group(attrs={"ages": [8, 30]}))["total"] - base == W["child_or_pregnant"]
    assert sc(group(attrs={"pregnant": True}))["total"] - base == W["child_or_pregnant"]
    assert sc(group(attrs={"disability": True}))["total"] - base == W["medical_disability"]
    assert sc(group(attrs={"deadline_min": 1200}))["total"] - base == W["hard_deadline"]
    assert base - sc(group(reserved=False))["total"] == W["reserved_pnr"]


def test_group_scores_as_its_highest_member_not_the_sum():
    senior, child = sc(group(attrs={"ages": [65]}))["total"], sc(group(attrs={"ages": [8]}))["total"]
    both = sc(group(attrs={"ages": [65, 8]}))["total"]
    assert both == max(senior, child) < senior + child


def test_ageing_grows_with_waiting_and_a_long_enough_wait_outranks_medical_need():
    medical = group(attrs={"disability": True}, waiting_since=840)
    assert sc(group(reserved=False), now=900)["total"] > sc(group(reserved=False), now=840)["total"]
    short_waiter = group(reserved=False, waiting_since=840 - 60)       # waited 1 h longer: +6 points, not enough
    long_waiter = group(reserved=False, waiting_since=840 - 12 * 60)   # waited 12 h longer: nobody is starved
    for now in (840, 1000, 5000):                                      # true at any clock reading (linear ageing)
        assert sc(short_waiter, now)["total"] < sc(medical, now)["total"]
        assert sc(long_waiter, now)["total"] > sc(medical, now)["total"]
    assert sc(short_waiter, 840)["total"] < sc(medical, 840)["total"]


def test_relative_order_is_invariant_to_the_clock():
    """Linear ageing means stored scores order groups exactly as fresh scores would (the shed-order argument)."""
    rng = random.Random(7)
    gs = [group(waiting_since=rng.randint(700, 840), reserved=rng.random() < 0.7,
                attrs={"ages": [rng.randint(1, 80) for _ in range(rng.randint(1, 4))], "disability": rng.random() < 0.1,
                       "pregnant": rng.random() < 0.05, "deadline_min": rng.choice([None, 1000])}) for _ in range(60)]
    def order(now):
        return [i for i, _ in sorted(enumerate(gs), key=lambda x: (-sc(x[1], now)["total"], x[0]))]
    assert order(840) == order(900) == order(2000)


def test_scorer_is_deterministic():
    g = group(attrs={"ages": [70, 9]})
    assert sc(g) == sc(g)
