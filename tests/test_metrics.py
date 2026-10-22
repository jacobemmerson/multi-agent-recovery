from mar.metrics import counterfactual_changed, taint_for_run


def test_changed_set_is_positional_and_excludes_fault(build_run):
    faulted = build_run("a", ["x'", "y"], [("s1", ["t:f0"]), ("s2", ["t:f1"])], ["e1", "e2'"], fault_artifact_id="t:f0")
    twin = build_run("b", ["x", "y"], [("s1", ["t:f0"]), ("s2'", ["t:f1"])], ["e1", "e2"])
    assert counterfactual_changed(faulted, twin, "t:f0") == {"t:p1", "t:exec:t:p1"}


def test_taint_reports_under_and_over(build_run):
    faulted = build_run("a", ["x'", "y"], [("s1", ["t:f0"]), ("s2", ["t:f1"])], ["e1", "e2'"], fault_artifact_id="t:f0")
    twin = build_run("b", ["x", "y"], [("s1", ["t:f0"]), ("s2'", ["t:f1"])], ["e1", "e2"])
    t = taint_for_run(faulted, twin)
    assert t["declared_descendants"] == 2 and t["counterfactual_changed"] == 2
    assert t["under_taint"] == 2 and t["over_taint"] == 2 and t["ignored"] is False


def test_unequal_step_counts_count_missing_partner_as_changed(build_run):
    faulted = build_run("a", ["x'"], [("s1", ["t:f0"]), ("s2", ["t:f0"])], ["e1", "e2"], fault_artifact_id="t:f0")
    twin = build_run("b", ["x"], [("s1", ["t:f0"])], ["e1"])
    assert counterfactual_changed(faulted, twin, "t:f0") == {"t:p1", "t:exec:t:p1"}


def test_identical_downstream_is_ignored(build_run):
    faulted = build_run("a", ["x'"], [("s1", ["t:f0"])], ["e1"], fault_artifact_id="t:f0")
    twin = build_run("b", ["x"], [("s1", ["t:f0"])], ["e1"])
    assert taint_for_run(faulted, twin)["ignored"] is True
