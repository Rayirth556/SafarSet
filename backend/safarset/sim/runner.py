"""Play the scripted demo timeline against the event loop, in process (Phase 8 plays the same script over the API)."""

_ACTOR = {"TRAIN_CANCELLED": "sim", "LOAD_REPORT": "field", "NOSHOWS_REPORTED": "field"}


def play_step(engine, step):
    """Execute one timeline step against the engine and return its result."""
    now = step["at_min"]
    if step["kind"] == "sim_event":
        return engine.handle(step["type"], _ACTOR.get(step["type"], "sim"), step["payload"], now)
    if step["kind"] == "system":
        return engine.ensure_plan(now)
    if step["kind"] == "operator_action" and step["type"] == "APPROVE_BATCH":
        return engine.approve(None, now)
    raise ValueError(f"unknown timeline step {step['kind']}/{step['type']}")


def play_timeline(engine, scenario, on_step=None):
    """Run every step in order. sim_event -> engine.handle; system -> make sure a fresh plan is pending; operator_action
    APPROVE_BATCH -> engine.approve. on_step(step, result) is called after each step (for assertions). Returns results."""
    results = []
    for step in scenario["timeline"]["steps"]:
        res = play_step(engine, step)
        results.append(res)
        if on_step:
            on_step(step, res)
    return results
