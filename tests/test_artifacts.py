from mar.artifacts import ExecutedStep, Finding, PlanStep, ProvenanceGraph


def graph():
    g = ProvenanceGraph()
    g.add(Finding(id="f1", producer="researcher", task_id="t", source="s1"))
    g.add(Finding(id="f2", producer="researcher", task_id="t", source="s2"))
    g.add(PlanStep(id="p1", producer="planner", task_id="t", index=0, cites=["f1"]))
    g.add(PlanStep(id="p2", producer="planner", task_id="t", index=1, cites=["f2"]))
    g.add(ExecutedStep(id="e1", producer="executor", task_id="t", plan_step_id="p1", cites=["p1"]))
    return g


def test_descendants_follow_cites_transitively():
    assert graph().descendants("f1") == {"p1", "e1"}
    assert graph().descendants("f2") == {"p2"}
    assert graph().descendants("e1") == set()


def test_ancestors():
    assert graph().ancestors("e1") == {"p1", "f1"}
