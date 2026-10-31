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


from mar.metrics import aggregate, bootstrap_ci


def test_aggregate_joins_manifest_and_result(tmp_path, build_run):
    a = build_run("a", ["x"], [("s", ["t:f0"])])
    a.manifest.update(condition="none", fault_id=None, prompt_hashes={"executor": "h"})
    a.finish({"utility": True, "llm_calls": 3})
    b = build_run("b", ["x"], [])
    b.manifest.update(condition="restart_stage", fault_id="date")
    b.finish({"utility": False, "llm_calls": 5, "under_taint": 1})
    build_run("unfinished", [], [])
    df = aggregate(tmp_path, tmp_path / "agg.parquet")
    assert len(df) == 2 and {"run_id", "condition", "utility", "llm_calls", "under_taint"} <= set(df.columns)
    assert sorted(df["run_id"]) == ["a", "b"] and df.set_index("run_id").loc["a", "prompt_hashes"] == '{"executor": "h"}'
    assert (tmp_path / "agg.parquet").exists()


def test_bootstrap_ci_brackets_mean():
    lo, hi = bootstrap_ci([0, 1, 1, 1, 0, 1])
    assert lo <= 4 / 6 <= hi and lo >= 0 and hi <= 1
    assert bootstrap_ci([]) == (float("nan"), float("nan")) or all(x != x for x in bootstrap_ci([]))


def test_taint_for_run_accepts_custom_differs(build_run):
    faulted = build_run("a", ["x'", "y"], [("s1", ["t:f0"]), ("s2", ["t:f1"])], ["e1", "e2'"], fault_artifact_id="t:f0")
    twin = build_run("b", ["x", "y"], [("s1", ["t:f0"]), ("s2'", ["t:f1"])], ["e1", "e2"])
    never = taint_for_run(faulted, twin, differs=lambda a, b: False)
    assert never["counterfactual_changed"] == 0 and never["ignored"] is True
    always = taint_for_run(faulted, twin, differs=lambda a, b: True)
    assert always["counterfactual_changed"] == 5  # every artifact but the fault itself
