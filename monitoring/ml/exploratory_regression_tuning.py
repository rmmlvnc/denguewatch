"""Explore Random Forest regression settings on validation months only.

This diagnostic does not load or score the later-period holdout and never
rewrites the deployed estimator or its recorded holdout metrics. Validation
has previously informed model selection, so results are exploratory.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

try:
    from .features import FEATURES, engineer_features
    from .train_model import _make_pipeline
except ImportError:  # Allows direct execution as a script.
    from features import FEATURES, engineer_features
    from train_model import _make_pipeline


ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "datasets" / "integrated_monthly.csv"
OUTPUT_PATH = Path(__file__).with_name("regression_tuning_validation.json")

CANDIDATES = [
    {
        "name": "Current Random Forest",
        "algorithm": "RandomForestRegressor",
        "n_estimators": 300,
        "criterion": "squared_error",
        "min_samples_leaf": 2,
        "max_features": 0.8,
    },
    {
        "name": "Absolute error, max_features 0.8",
        "algorithm": "RandomForestRegressor",
        "n_estimators": 200,
        "criterion": "absolute_error",
        "min_samples_leaf": 3,
        "max_features": 0.8,
    },
    {
        "name": "Absolute error, max_features 0.6",
        "algorithm": "RandomForestRegressor",
        "n_estimators": 200,
        "criterion": "absolute_error",
        "min_samples_leaf": 3,
        "max_features": 0.6,
    },
    {
        "name": "Absolute error, max_features 0.5",
        "algorithm": "RandomForestRegressor",
        "n_estimators": 200,
        "criterion": "absolute_error",
        "min_samples_leaf": 3,
        "max_features": 0.5,
    },
]


def _scores(actual, predicted):
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "rmse": round(float(mean_squared_error(actual, predicted) ** 0.5), 4),
    }


def main():
    source = pd.read_csv(DATA_PATH)
    required_status = "case_observation_status"
    if required_status not in source:
        raise ValueError(f"Monthly source lacks {required_status}.")
    allowed = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    if not source[required_status].isin(allowed).all():
        raise ValueError("Source contains unverified or missing case-reporting status.")

    data = engineer_features(source, include_target=True)
    data = data.dropna(subset=["target_next_cases", "cases_lag_1"]).reset_index(drop=True)
    periods = sorted(data["period"].unique())
    train_end = max(1, int(len(periods) * 0.60))
    validation_end = max(train_end + 1, int(len(periods) * 0.80))
    validation_end = min(validation_end, len(periods) - 1)
    train_periods = periods[:train_end]
    validation_periods = periods[train_end:validation_end]
    train = data[data["period"].isin(train_periods)]
    validation = data[data["period"].isin(validation_periods)]
    actual = validation["target_next_cases"].to_numpy(dtype=float)

    baseline_prediction = np.maximum(0, validation["case_count"].to_numpy(dtype=float))
    results = [{
        "name": "Persistence baseline (current month count)",
        **_scores(actual, baseline_prediction),
    }]

    for parameters in CANDIDATES:
        pipeline = _make_pipeline(parameters)
        pipeline.fit(train[FEATURES], train["target_next_cases"])
        prediction = np.maximum(0, pipeline.predict(validation[FEATURES]))
        results.append({
            "name": parameters["name"],
            "parameters": {key: value for key, value in parameters.items() if key != "name"},
            **_scores(actual, prediction),
        })

    baseline = results[0]
    for result in results[1:]:
        result["beats_persistence_both_metrics"] = (
            result["mae"] < baseline["mae"] and result["rmse"] < baseline["rmse"]
        )

    report = {
        "analysis_type": "exploratory_chronological_validation_only",
        "validation_reference_month_start": pd.Timestamp(min(validation_periods)).strftime("%Y-%m"),
        "validation_reference_month_end": pd.Timestamp(max(validation_periods)).strftime("%Y-%m"),
        "validation_rows": int(len(validation)),
        "validation_rows_partitioned_by_whole_reference_month": True,
        "preprocessing_fit_policy": "Each candidate's imputer and encoder are fitted on training rows only.",
        "later_period_holdout_loaded_or_scored": False,
        "validation_previously_used_for_model_selection": True,
        "interpretation": (
            "Exploratory comparison only. Do not use these results as an independent performance claim "
            "or to promise improved future holdout performance. The live model and its recorded holdout "
            "metrics are not modified by this script."
        ),
        "results": results,
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
