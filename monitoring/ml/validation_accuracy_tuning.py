"""Compare hotspot cutoffs and Random Forest settings on development data only.

The final chronological holdout is excluded from feature engineering, fitting,
cutoff selection, and scoring. Validation has informed prior iterations, so this
is an exploratory model-selection aid rather than independent confirmation.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
)

try:
    from .features import FEATURES, engineer_features
    from .train_model import _make_pipeline
except ImportError:  # Allows direct execution as a script.
    from features import FEATURES, engineer_features
    from train_model import _make_pipeline


ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "datasets" / "integrated_monthly.csv"
METRICS_PATH = Path(__file__).with_name("model_metrics.json")
OUTPUT_PATH = Path(__file__).with_name("accuracy_tuning_validation.json")
CUTOFFS = (2.0, 2.7, 3.0)
OBSERVED_HOTSPOT_THRESHOLD = 2


def main() -> dict:
    source = pd.read_csv(DATA_PATH)
    status = source.get("case_observation_status")
    allowed = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    if status is None or not status.isin(allowed).all():
        raise ValueError("Source must contain only verified or confirmed-zero reporting statuses.")

    # Match train_model.py exactly: first engineer one-step targets, then split
    # the usable reference periods chronologically by whole month.
    data = engineer_features(source, include_target=True)
    data = data.dropna(subset=["target_next_cases", "cases_lag_1"]).reset_index(drop=True)
    periods = sorted(data["period"].unique())
    outer_end = min(len(periods) - 1, max(1, int(np.ceil(len(periods) * 0.75))))
    fit_end = max(1, int(outer_end * 0.75))
    validation_reference_periods = periods[fit_end:outer_end]
    if not validation_reference_periods:
        raise ValueError("The chronological validation partition is empty.")
    last_target_period = pd.Timestamp(max(validation_reference_periods)) + pd.DateOffset(months=1)
    fit_periods = periods[:fit_end]
    fit = data[data["period"].isin(fit_periods)]
    validation = data[data["period"].isin(validation_reference_periods)]
    if fit.empty or validation.empty:
        raise ValueError("The chronological fit or validation partition is empty.")

    saved = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    candidates = [item["parameters"] for item in saved["validation_candidate_scores"]]
    actual_count = validation["target_next_cases"].to_numpy(dtype=float)
    actual_flag = actual_count >= OBSERVED_HOTSPOT_THRESHOLD
    results = []

    for parameters in candidates:
        pipeline = _make_pipeline(parameters)
        pipeline.fit(fit[FEATURES], fit["target_next_cases"])
        prediction = np.maximum(0, pipeline.predict(validation[FEATURES]))
        regression = {
            "mae": round(float(mean_absolute_error(actual_count, prediction)), 4),
            "rmse": round(float(mean_squared_error(actual_count, prediction) ** 0.5), 4),
        }
        for cutoff in CUTOFFS:
            predicted_flag = prediction >= cutoff
            tn, fp, fn, tp = (int(value) for value in confusion_matrix(
                actual_flag, predicted_flag, labels=[False, True]
            ).ravel())
            results.append({
                "parameters": parameters,
                "predicted_count_cutoff": cutoff,
                **regression,
                "accuracy": round(float(accuracy_score(actual_flag, predicted_flag)), 4),
                "precision": round(float(precision_score(actual_flag, predicted_flag, zero_division=0)), 4),
                "recall": round(float(recall_score(actual_flag, predicted_flag, zero_division=0)), 4),
                "f1": round(float(f1_score(actual_flag, predicted_flag, zero_division=0)), 4),
                "predicted_hotspot_rows": int(predicted_flag.sum()),
                "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
            })

    constraints = saved.get("validation_precision_recall_constraints", {})
    min_precision = float(constraints.get("precision_at_least", 0.85))
    min_recall = float(constraints.get("recall_at_least", 0.40))
    eligible = [row for row in results if row["precision"] >= min_precision and row["recall"] >= min_recall]
    if not eligible:
        raise ValueError(
            "No candidate/cutoff meets the saved precision and recall constraints; "
            "do not change the deployed threshold based on this run."
        )

    # Prioritize validation accuracy while preserving the existing minimum
    # precision/recall safeguards. F1 and count MAE break ties.
    selected = max(eligible, key=lambda row: (
        row["accuracy"], row["f1"], -row["mae"], -row["predicted_count_cutoff"]
    ))
    report = {
        "analysis_type": "exploratory_chronological_validation_only",
        "validation_reference_start": pd.Timestamp(min(validation_reference_periods)).strftime("%Y-%m"),
        "validation_reference_end": pd.Timestamp(max(validation_reference_periods)).strftime("%Y-%m"),
        "validation_target_end": last_target_period.strftime("%Y-%m"),
        "validation_rows": int(len(validation)),
        "observed_hotspot_threshold_cases": OBSERVED_HOTSPOT_THRESHOLD,
        "candidate_predicted_count_cutoffs": list(CUTOFFS),
        "selection_rule": (
            f"Highest validation accuracy among candidates with precision >= {min_precision:.0%} "
            f"and recall >= {min_recall:.0%}; ties use higher F1, lower MAE, then lower cutoff."
        ),
        "selected_candidate": selected,
        "candidate_results": results,
        "final_test_rows_used_for_fitting_or_scoring": False,
        "validation_previously_used_for_model_selection": True,
        "interpretation": (
            "Exploratory only. The selected validation score is not an independent performance claim. "
            "The previously inspected final holdout was not used. Confirm any change on newly collected "
            "future months before claiming improved generalization."
        ),
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
