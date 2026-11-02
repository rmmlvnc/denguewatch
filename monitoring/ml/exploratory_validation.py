"""Run exploratory cutoff and momentum comparisons on validation months only.

This script deliberately does not score or load the final-test predictions.
Results are development diagnostics, not an independent final evaluation.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
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
OUTPUT_PATH = Path(__file__).with_name("validation_threshold_analysis.json")
THRESHOLDS = (6, 7, 8, 9, 10, 12, 15)
OBSERVED_HOTSPOT_THRESHOLD = 6


def main() -> dict:
    source = pd.read_csv(DATA_PATH)
    if "case_observation_status" not in source:
        raise ValueError("Monthly source lacks case_observation_status.")
    allowed = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    invalid = ~source["case_observation_status"].isin(allowed)
    if invalid.any():
        raise ValueError(
            f"Validation analysis stopped: {int(invalid.sum())} rows have "
            "unverified reporting status."
        )

    data = engineer_features(source, include_target=True)
    data = data.dropna(subset=["target_next_cases", "cases_lag_1"]).reset_index(drop=True)

    # Match train_model.py's current chronological outer 75/25 split and its
    # inner 75/25 development fit/validation split. Never score the final test.
    periods = sorted(data["period"].unique())
    outer_train_end = min(
        len(periods) - 1,
        max(1, int(np.ceil(len(periods) * 0.75))),
    )
    train_end = max(1, int(outer_train_end * 0.75))
    validation_end = outer_train_end
    train_periods = periods[:train_end]
    validation_periods = periods[train_end:validation_end]
    train = data[data["period"].isin(train_periods)]
    validation = data[data["period"].isin(validation_periods)]

    saved_metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    parameters = saved_metrics["validation_selected_parameters"]
    if parameters.get("algorithm") != "RandomForestRegressor":
        raise ValueError("The saved selected algorithm is not RandomForestRegressor.")

    actual_counts = validation["target_next_cases"].to_numpy(dtype=float)
    actual_hotspots = (actual_counts >= OBSERVED_HOTSPOT_THRESHOLD).astype(int)
    weather_features = {
        "rainfall_mm", "temperature_c", "humidity_pct",
        "rainfall_lag_1", "temperature_lag_1", "humidity_lag_1",
    }
    variants = {
        "current_features": list(FEATURES),
        "with_case_momentum": [*FEATURES, "case_momentum"],
        "without_weather": [name for name in FEATURES if name not in weather_features],
        "momentum_without_weather": [
            *[name for name in FEATURES if name not in weather_features],
            "case_momentum",
        ],
    }
    results = {}

    for variant, feature_columns in variants.items():
        pipeline = _make_pipeline(parameters, feature_columns=feature_columns)
        pipeline.fit(train[feature_columns], train["target_next_cases"])
        predicted_counts = np.maximum(
            0, pipeline.predict(validation[feature_columns])
        )
        predicted_counts = np.asarray(predicted_counts, dtype=float)

        threshold_rows = []
        for cutoff in THRESHOLDS:
            predicted_hotspots = (predicted_counts >= cutoff).astype(int)
            precision_value = float(precision_score(
                actual_hotspots, predicted_hotspots, zero_division=0
            ))
            recall_value = float(recall_score(
                actual_hotspots, predicted_hotspots, zero_division=0
            ))
            f1_value = float(f1_score(
                actual_hotspots, predicted_hotspots, zero_division=0
            ))
            threshold_rows.append({
                "predicted_count_cutoff": cutoff,
                "precision": round(precision_value, 4),
                "precision_pct": round(precision_value * 100, 2),
                "recall": round(recall_value, 4),
                "recall_pct": round(recall_value * 100, 2),
                "f1": round(f1_value, 4),
                "f1_pct": round(f1_value * 100, 2),
                "flagged_barangay_months": int(predicted_hotspots.sum()),
                "true_positives": int(((actual_hotspots == 1) & (predicted_hotspots == 1)).sum()),
                "false_positives": int(((actual_hotspots == 0) & (predicted_hotspots == 1)).sum()),
                "false_negatives": int(((actual_hotspots == 1) & (predicted_hotspots == 0)).sum()),
            })
        qualifying = [
            row["predicted_count_cutoff"]
            for row in threshold_rows
            if row["precision"] >= 0.85 and row["flagged_barangay_months"] > 0
        ]
        results[variant] = {
            "mae": round(float(mean_absolute_error(actual_counts, predicted_counts)), 4),
            "rmse": round(float(mean_squared_error(actual_counts, predicted_counts) ** 0.5), 4),
            "thresholds": threshold_rows,
            "cutoffs_meeting_85_percent_precision": qualifying,
        }

    report = {
        "analysis_type": "exploratory_chronological_validation_only",
        "validation_reference_month_start": pd.Timestamp(min(validation_periods)).strftime("%Y-%m"),
        "validation_reference_month_end": pd.Timestamp(max(validation_periods)).strftime("%Y-%m"),
        "validation_target_month_start": (pd.Timestamp(min(validation_periods)) + pd.DateOffset(months=1)).strftime("%Y-%m"),
        "validation_target_month_end": (pd.Timestamp(max(validation_periods)) + pd.DateOffset(months=1)).strftime("%Y-%m"),
        "validation_rows": int(len(validation)),
        "observed_hotspot_definition": f"observed next-month count >= {OBSERVED_HOTSPOT_THRESHOLD}",
        "candidate_predicted_count_cutoffs": list(THRESHOLDS),
        "model_parameters": parameters,
        "momentum_definition": "cases_lag_1 - cases_lag_2; derived only from prior completed monthly counts",
        "validation_was_previously_used_for_parameter_selection": True,
        "validation_split_policy": (
            "Matches current training workflow: chronological outer 75/25 by whole month; "
            "the outer development period is split into an earlier fit period and later validation period."
        ),
        "feature_experiments": list(variants),
        "final_test_scored_or_loaded": False,
        "interpretation": (
            "Exploratory validation diagnostics only. The validation period was already used "
            "for model selection. Selecting a cutoff or feature from these results requires "
            "a new future evaluation period for confirmatory performance claims. A higher "
            "predicted cutoff can increase precision while reducing recall and the number flagged."
        ),
        "variants": results,
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
