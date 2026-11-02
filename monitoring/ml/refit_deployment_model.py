"""Refit the frozen validation-selected model for deployment without rescoring holdout.

This consumes accuracy_tuning_validation.json, fits its frozen settings on all
usable historical rows for operational forecasts, and explicitly retains the
old holdout scores as previous-model results. It does not evaluate holdout rows.
"""

import json
from pathlib import Path

import joblib
import pandas as pd

try:
    from .features import FEATURES, engineer_features
    from .train_model import _make_pipeline
except ImportError:  # Allows direct execution as a script.
    from features import FEATURES, engineer_features
    from train_model import _make_pipeline


ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = Path(__file__).with_name("model_metrics.json")
SELECTION_PATH = Path(__file__).with_name("accuracy_tuning_validation.json")
MODEL_PATH = Path(__file__).with_name("random_forest.pkl")
DATA_PATH = ROOT / "datasets" / "integrated_monthly.csv"


def main() -> dict:
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    chosen = selection["selected_candidate"]
    parameters = chosen["parameters"]
    cutoff = float(chosen["predicted_count_cutoff"])

    source = pd.read_csv(DATA_PATH)
    allowed = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    if "case_observation_status" not in source or not source["case_observation_status"].isin(allowed).all():
        raise ValueError("Cannot refit: monthly data includes unverified case-reporting status.")
    data = engineer_features(source, include_target=True)
    data = data.dropna(subset=["target_next_cases", "cases_lag_1"]).reset_index(drop=True)
    if data.empty:
        raise ValueError("Cannot refit: no usable barangay-month rows are available.")

    pipeline = _make_pipeline(parameters)
    pipeline.fit(data[FEATURES], data["target_next_cases"])

    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    metrics.setdefault("previous_model_evaluation", {
        "parameters": metrics.get("validation_selected_parameters"),
        "predicted_hotspot_cutoff_cases": metrics.get("predicted_hotspot_cutoff_cases"),
        "validation_hotspot_classification": metrics.get("validation_hotspot_classification"),
        "case_count_metrics": {
            key: metrics.get(key) for key in ("mae", "rmse", "r2")
        },
        "final_test_period": {
            "start": metrics.get("final_test_target_start"),
            "end": metrics.get("final_test_target_end"),
            "rows": metrics.get("test_rows"),
        },
        "hotspot_classification_evaluation": metrics.get("hotspot_classification_evaluation"),
        "status": "Previously inspected holdout results for the pre-update model; not a fresh evaluation of the active deployment.",
    })

    validation = chosen
    tn = int(validation["confusion_matrix"]["tn"])
    fp = int(validation["confusion_matrix"]["fp"])
    fn = int(validation["confusion_matrix"]["fn"])
    tp = int(validation["confusion_matrix"]["tp"])
    negative_support = tn + fp
    positive_support = tp + fn
    negative_precision = tn / (tn + fn) if tn + fn else 0.0
    negative_recall = tn / (tn + fp) if tn + fp else 0.0
    negative_f1 = (
        2 * negative_precision * negative_recall / (negative_precision + negative_recall)
        if negative_precision + negative_recall else 0.0
    )
    positive_precision = tp / (tp + fp) if tp + fp else 0.0
    positive_recall = tp / (tp + fn) if tp + fn else 0.0
    positive_f1 = (
        2 * positive_precision * positive_recall / (positive_precision + positive_recall)
        if positive_precision + positive_recall else 0.0
    )
    metrics["validation_selected_parameters"] = parameters
    metrics["validation_selected_predicted_hotspot_cutoff_cases"] = cutoff
    metrics["validation_selected_hotspot_metrics"] = {
        key: validation[key]
        for key in (
            "accuracy", "precision", "recall", "f1", "mae", "rmse",
            "predicted_hotspot_rows", "confusion_matrix",
        )
    }
    metrics["validation_selection_rule"] = selection["selection_rule"]
    metrics["validation_model_selection_rule"] = selection["selection_rule"]
    metrics["validation_candidate_scores"] = selection["candidate_results"]
    metrics["validation_selection_report"] = SELECTION_PATH.name
    metrics["validation_rows"] = selection["validation_rows"]
    metrics["validation_start"] = selection["validation_reference_start"]
    metrics["validation_end"] = selection["validation_reference_end"]
    metrics["validation_target_end"] = selection["validation_target_end"]
    metrics["predicted_hotspot_cutoff_cases"] = cutoff
    metrics["validation_objective"] = selection["selection_rule"]
    metrics["validation_hotspot_classification"] = {
        "rows": selection["validation_rows"],
        "threshold_cases": 2,
        "predicted_count_cutoff": cutoff,
        "positive_class": "at_least_2_observed_cases",
        "accuracy": validation["accuracy"],
        "precision": validation["precision"],
        "recall": validation["recall"],
        "f1": validation["f1"],
        "per_class": {
            "not_hotspot": {
                "precision": round(negative_precision, 4),
                "recall": round(negative_recall, 4),
                "f1": round(negative_f1, 4),
                "support": negative_support,
            },
            "hotspot": {
                "precision": round(positive_precision, 4),
                "recall": round(positive_recall, 4),
                "f1": round(positive_f1, 4),
                "support": positive_support,
            },
        },
        "actual_hotspot_rows": positive_support,
        "predicted_hotspot_rows": validation["predicted_hotspot_rows"],
        "confusion_matrix": {
            "labels": ["not_hotspot", "hotspot"],
            "rows_actual_columns_predicted": [[tn, fp], [fn, tp]],
            "true_negative": tn,
            "false_positive": fp,
            "false_negative": fn,
            "true_positive": tp,
        },
    }
    metrics["validation_precision_recall_constraints"] = {
        "precision_at_least": 0.85,
        "recall_at_least": 0.40,
        "observed_hotspot_threshold_cases": 2,
        "selected_predicted_count_cutoff_cases": cutoff,
    }
    metrics["hotspot_definition"] = (
        f"Observed evaluation hotspot: at least 2 cases. Model planning-review flag: "
        f"predicted count >= {cutoff:g}. The thresholds are internal project rules, "
        "not official DOH outbreak definitions."
    )
    metrics["active_deployment"] = {
        "algorithm": parameters["algorithm"],
        "parameters": parameters,
        "predicted_hotspot_cutoff_cases": cutoff,
        "validation_reference_start": selection["validation_reference_start"],
        "validation_reference_end": selection["validation_reference_end"],
        "validation_target_end": selection["validation_target_end"],
        "validation_rows": selection["validation_rows"],
        "validation_accuracy": validation["accuracy"],
        "validation_accuracy_pct": round(validation["accuracy"] * 100, 2),
        "validation_precision": validation["precision"],
        "validation_precision_pct": round(validation["precision"] * 100, 2),
        "validation_recall": validation["recall"],
        "validation_recall_pct": round(validation["recall"] * 100, 2),
        "validation_f1": validation["f1"],
        "validation_f1_pct": round(validation["f1"] * 100, 2),
        "validation_mae": validation["mae"],
        "validation_rmse": validation["rmse"],
        "validation_confusion_matrix": validation["confusion_matrix"],
        "training_rows_after_selection": int(len(data)),
        "later_independent_evaluation_available": False,
        "status": "Planning support only; validation was previously used for model selection.",
    }
    metrics["final_test_policy"] = (
        "The previously inspected holdout results describe the previous model settings. "
        "They were not rescored or used to choose the current model. A new, later untouched "
        "period is required to confirm current deployment performance."
    )
    metrics["final_deployment_fit_policy"] = (
        "After validation settings were frozen, the deployment pipeline was refit on all "
        "currently usable historical rows. No holdout score was recalculated by this refit."
    )

    joblib.dump({
        "pipeline": pipeline,
        "metrics": metrics,
        "predicted_hotspot_threshold": cutoff,
    }, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics["active_deployment"], indent=2))
    return metrics["active_deployment"]


if __name__ == "__main__":
    main()
