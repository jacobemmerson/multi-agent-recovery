from mar.artifacts import Finding, PlanStep, ProvenanceGraph
from mar.recovery import POLICIES, AlwaysVerify, NoRecovery, RestartScratch, RestartStage


def graph():
    g = ProvenanceGraph()
    g.add(Finding(id="t:f0", producer="r", task_id="t", source="s"))
    g.add(PlanStep(id="t:p0", producer="p", task_id="t", index=0, cites=["t:f0"]))
    return g


def test_restart_scratch_discards_everything():
    assert RestartScratch().on_reveal("t:f0", graph(), None).restart_from == "scratch"


def test_restart_stage_restarts_at_fault_stage():
    assert RestartStage().on_reveal("t:f0", graph(), None).restart_from == "findings"
    assert RestartStage().on_reveal("t:p0", graph(), None).restart_from == "plan"


def test_no_recovery_and_always_verify_do_not_restart():
    assert NoRecovery().on_reveal("t:f0", graph(), None).restart_from is None
    assert AlwaysVerify().on_reveal("t:f0", graph(), None).restart_from is None
    assert AlwaysVerify().verify_every_artifact is True and NoRecovery().verify_every_artifact is False


def test_policies_are_looked_up_by_condition_name():
    assert POLICIES["restart_stage"] is RestartStage and POLICIES["none"] is NoRecovery
