"""Write a SIMULATED scenario to data/simulated/scenario_seed<seed>.json.

Usage: python scripts/generate_scenario.py [seed] [n_passengers]
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from safarset.sim.generator import dumps, generate  # noqa: E402

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
sc = generate(seed, n_passengers=n)
out = root / "data" / "simulated" / f"scenario_seed{seed}.json"
out.write_text(dumps(sc) + "\n", encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
print("warnings:", sc["meta"]["warnings"])
print("demand by destination (heads):", sc["summary"]["demand_heads_by_place"])
print("vehicles:", {r: sum(1 for v in sc['vehicles'] if v['role'] == r) for r in ("ALLOCATION", "TRANSFER_LEG", "TO_BE_CANCELLED")})
for s in sc["timeline"]["steps"]:
    print(s["at"], s["kind"], s["type"], s["payload"])
