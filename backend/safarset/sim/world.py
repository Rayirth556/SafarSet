"""Static world definition for the SafarSet scenario.

Everything here is either REAL (taken from data/real) or explicitly SIMULATED. Labels are carried into the
generated scenario so the UI and tests can tell them apart.
"""

# Places a stranded passenger can be going to. `rail` lists railway station codes that serve the place.
PLACES = {
    "CENTRAL":     {"name": "Chennai Central", "rail": ["MAS"]},
    "AVADI":       {"name": "Avadi",           "rail": ["AVD"]},
    "POONAMALLEE": {"name": "Poonamallee",     "rail": []},            # no railway station: bus only
    "TIRUVALLUR":  {"name": "Tiruvallur",      "rail": ["TRL"]},
    "ARAKKONAM":   {"name": "Arakkonam",       "rail": ["AJJ"]},
    "KATPADI":     {"name": "Katpadi",         "rail": ["KPD"]},
    "VELLORE":     {"name": "Vellore",         "rail": ["KPD"]},       # Katpadi Jn is the railhead for Vellore
    "JOLARPETTAI": {"name": "Jolarpettai",     "rail": ["JTJ"]},
    "KOYAMBEDU":   {"name": "Koyambedu CMBT",  "rail": [], "transfer_only": True},
}

# Destination mix of the stranded passengers (weights, not percentages). SIMULATED.
# The cancelled train runs Chennai Central -> Jolarpettai, so many of its passengers are long-distance (Jolarpettai, Tiruvallur), with a suburban share for Avadi and Poonamallee. Tiruvallur and Jolarpettai are reached by train only (no direct bus), which is where
# the shortage (and the second-chart vacancies of the demo) show up.
DEST_WEIGHTS = {
    "ARAKKONAM": 0.10, "AVADI": 0.20, "KATPADI": 0.08, "VELLORE": 0.08,
    "TIRUVALLUR": 0.20, "POONAMALLEE": 0.18, "JOLARPETTAI": 0.16,
}

# Real MTC GTFS stop ids that serve each place (from data/real/reference/bus_stops.csv).
BUS_STOP_PLACES = {
    "MTC-10428": ["AVADI"],                      # Avadi Bus Terminus (a different GTFS stop with the same name)
    "MTC-10430": ["AVADI"],                      # Avadi Bus Terminus: the terminal stop of routes 120 R1 and 150 R1
    "MTC-5821": ["POONAMALLEE"],                 # Poonamallee Bus Terminus
    "MTC-9440": ["POONAMALLEE"],                 # Poonamallee
    "MTC-9437": ["POONAMALLEE"],                 # Poonamallee
    "MTC-5831": ["TIRUVALLUR"],                  # Thiruvallur Terminal
    "MTC-5822": ["KOYAMBEDU"],                   # M.G.R.Koyambedu Bus Terminus
}

# Real MTC routes used, split by role in the scenario.
MTC_SPECIAL_ROUTES = ["MTC-22836", "MTC-22798", "MTC-23210", "MTC-22758", "MTC-22244"]  # direct, Avadi/Poonamallee
MTC_TRANSFER_ROUTES = {"KOYAMBEDU": "MTC-23213", "POONAMALLEE": "MTC-22836", "TIRUVALLUR": "MTC-22780"}

# Coach classes (see data/real/capacities.json for per-coach seats and class ranks).
RESERVED_CLASSES = ["SL", "3A", "CC", "2S"]

# SIMULATED intercity services (no real TNSTC/SETC data exists in the feed). Offsets in minutes from first stop.
INTERCITY_ROUTES = {
    "SIM-IC-CENTRAL": {   # special dispatched from Chennai Central
        "name": "SIMULATED special: Chennai Central - Vellore",
        "stops": [("Chennai Central", ["CENTRAL"], 0), ("Arakkonam", ["ARAKKONAM"], 100),
                  ("Katpadi", ["KATPADI"], 170), ("Vellore", ["VELLORE"], 185)],
    },
    "SIM-IC-KOY": {       # regular TNSTC-style service from Koyambedu (second leg of the MTC+TNSTC alternative)
        "name": "SIMULATED regular: Koyambedu CMBT - Vellore",
        "stops": [("Koyambedu CMBT", ["KOYAMBEDU"], 0), ("Katpadi", ["KATPADI"], 150), ("Vellore", ["VELLORE"], 165)],
    },
}

# Minimum time (min) to change between MTC and the connecting service. PLACEHOLDER.
MIN_CONNECTION_MIN = 20

# Each dispatched MTC route must reach this place (scenario validation; guards against unmapped terminal stops).
ROUTE_EXPECTED_PLACE = {"MTC-22836": "POONAMALLEE", "MTC-22798": "POONAMALLEE", "MTC-23210": "POONAMALLEE",
                        "MTC-22758": "AVADI", "MTC-22244": "AVADI"}
