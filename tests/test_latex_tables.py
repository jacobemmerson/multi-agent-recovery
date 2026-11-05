import pandas as pd

from scripts.latex_tables import baselines_table, propagation_table, render, taint_table


def _frame():
    rows = []
    for fid, ignored, under, over, util in (("finding_other_obvious", False, 1, 0, True), ("finding_other_obvious", True, 0, 2, True),
                                            ("plan_step_other_obvious", False, 0, 1, False)):
        changed = 1 - ignored
        rows.append({"condition": "none", "fault_id": fid, "fault_applied": True, "judged_ignored": ignored,
                     "judged_under_taint": under, "judged_over_taint": over, "judged_counterfactual_changed": changed,
                     "declared_descendants": over + changed - under,
                     "utility": util, "llm_calls": 5, "completion_tokens": 100, "seconds": 3.0, "irreversible_actions": 1,
                     "unauthorized_actions": 0, "discarded_artifacts": 0, "recovery_llm_calls": 0})
    rows.append({"condition": "none", "fault_id": None, "fault_applied": None, "utility": True, "llm_calls": 4})
    return pd.DataFrame(rows)


def test_propagation_table_has_one_row_per_template_with_rate_and_interval():
    table = propagation_table(_frame())
    assert table.index.tolist() == ["finding_other_obvious", "plan_step_other_obvious"]
    assert table.loc["finding_other_obvious", "n"] == 2 and table.loc["finding_other_obvious", "propagated"].startswith("0.50 [")


def test_taint_table_has_one_column_per_stage():
    table = taint_table(_frame())
    assert table.columns.tolist() == ["finding fault", "plan step fault"]
    assert table.loc["ignored (no downstream change)", "finding fault"] == "0.50"


def test_taint_table_reports_descendant_level_fractions():
    table = taint_table(_frame())
    assert table.loc["declared descendants unchanged", "finding fault"] == "1.00"  # 2 unchanged of 2 declared
    assert table.loc["changed artifacts not declared", "finding fault"] == "1.00"  # the one changed artifact was uncited
    assert table.loc["declared descendants unchanged", "plan step fault"] == "0.50"
    assert table.loc["changed artifacts not declared", "plan step fault"] == "0.00"


def test_baselines_table_uses_applied_faults_and_clean_utility():
    table = baselines_table(_frame())
    assert table.loc["none", "n"] == 3 and table.loc["none", "clean utility"] == "1.00"


def test_render_emits_booktabs_latex_with_caption_and_label():
    tex = render(propagation_table(_frame()), caption="Propagation", label="tab:prop")
    assert "\\toprule" in tex and "\\caption{Propagation}" in tex and "\\label{tab:prop}" in tex
    assert "finding\\_other\\_obvious" in tex
