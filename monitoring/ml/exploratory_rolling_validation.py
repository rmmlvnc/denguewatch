"""Compare forecasting candidates across chronological validation windows only.

The previously inspected later-period holdout is intentionally excluded. This
analysis is exploratory because the development period has informed past model
choices. It does not replace the saved production pipeline or its metrics.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
    r2_score,
)
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from .definition import OBSERVED_HOTSPOT_THRESHOLD, PREDICTED_HOTSPOT_THRESHOLD
    from .features import FEATURES, engineer_features
    from .train_model import _make_pipeline
except ImportError:  # Allows direct execution as a script.
    from definition import OBSERVED_HOTSPOT_THRESHOLD, PREDICTED_HOTSPOT_THRESHOLD
    from features import FEATURES, engineer_features
    from train_model import _make_pipeline


ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "datasets" / "integrated_monthly.csv"
OUTPUT_PATH = Path(__file__).with_name("rolling_validation_exploration.json")
HOTSPOT_THRESHOLD = OBSERVED_HOTSPOT_THRESHOLD

# Existing final-test reference months begin in 2024-06. Limit this exploratory
# run to reference months through 2024-05 (target month through 2024-06), before
# any previously inspected final-test target can enter feature comparison.
DEVELOPMENT_SOURCE_END = pd.Timestamp("2024-05-01")

CANDIDATES = [{
    # Hold the already-selected Random Forest settings fixed so this experiment
    # isolates changes to the lag/rolling feature set.
    "name": "Selected Random Forest (fixed settings)",
    "algorithm": "RandomForestRegressor",
    "criterion": "absolute_error",
    "n_estimators": 200,
    "min_samples_leaf": 1,
    "max_features": 0.8,
    "max_depth": 10,
}]


def _candidate_pipeline(parameters, feature_columns=None):
    """Build a fold-local estimator pipeline for tree or Poisson candidates."""
    feature_columns = list(FEATURES if feature_columns is None else feature_columns)
    if parameters.get("feature_policy") == "exclude_weather":
        excluded = {
            "rainfall_mm", "temperature_c", "humidity_pct",
            "rainfall_lag_1", "temperature_lag_1", "humidity_lag_1",
        }
        feature_columns = [name for name in feature_columns if name not in excluded]

    if parameters["algorithm"] != "PoissonRegressor":
        return _make_pipeline(parameters, feature_columns=feature_columns), feature_columns

    numeric = [name for name in feature_columns if name != "barangay"]
    preprocess = ColumnTransformer([
        ("barangay", OneHotEncoder(handle_unknown="ignore"), ["barangay"]),
        ("numeric", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), numeric),
    ])
    return Pipeline([
        ("preprocess", preprocess),
        ("model", PoissonRegressor(alpha=parameters["alpha"], max_iter=2000)),
    ]), feature_columns


def _score(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.maximum(0, np.asarray(predicted, dtype=float))
    return {
        "rows": int(len(actual)),
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "rmse": round(float(mean_squared_error(actual, predicted) ** 0.5), 4),
        "r2": round(float(r2_score(actual, predicted)), 4) if len(actual) > 1 else None,
    }


def _hotspot_score(actual, predicted):
    actual_flag = np.asarray(actual, dtype=float) >= HOTSPOT_THRESHOLD
    predicted_flag = np.asarray(predicted, dtype=float) >= PREDICTED_HOTSPOT_THRESHOLD
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(
        actual_flag, predicted_flag, labels=[False, True]
    ).ravel())
    return {
        "threshold_cases": HOTSPOT_THRESHOLD,
        "predicted_count_cutoff": PREDICTED_HOTSPOT_THRESHOLD,
        "accuracy": round(float(accuracy_score(actual_flag, predicted_flag)), 4),
        "precision": round(float(precision_score(actual_flag, predicted_flag, zero_division=0)), 4),
        "recall": round(float(recall_score(actual_flag, predicted_flag, zero_division=0)), 4),
        "f1": round(float(f1_score(actual_flag, predicted_flag, zero_division=0)), 4),
        "predicted_hotspot_rows": int(predicted_flag.sum()),
        "confusion_matrix_actual_rows_predicted_columns": [[tn, fp], [fn, tp]],
    }


def _feature_variants():
    """Feature sets for an apples-to-apples history-feature comparison."""
    base = list(FEATURES)
    longer_lags = [*base, "cases_lag_2", "cases_lag_3", "cases_lag_6", "cases_lag_12"]
    rolling = [*longer_lags, "cases_roll_3", "cases_roll_6"]
    momentum = [*rolling, "case_momentum"]
    return {
        "active_features": base,
        "active_plus_longer_case_lags": longer_lags,
        "longer_lags_plus_rolling_averages": rolling,
        "longer_lags_rolling_averages_and_momentum": momentum,
    }


def _rolling_folds(periods):
    """Return expanding-window folds; validation blocks never overlap."""
    initial_train_size = int(len(periods) * 0.60)
    remaining = len(periods) - initial_train_size
    fold_count = 4
    if initial_train_size < 24 or remaining < fold_count * 4:
        raise ValueError("Not enough development months for four rolling validation windows.")
    block_size = remaining // fold_count
    folds = []
    start = initial_train_size
    for fold_number in range(fold_count):
        end = len(periods) if fold_number == fold_count - 1 else start + block_size
        folds.append((periods[:start], periods[start:end]))
        start = end
    return folds


def main():
    source = pd.read_csv(DATA_PATH)
    status_column = "case_observation_status"
    if status_column not in source:
        raise ValueError(f"Monthly source lacks {status_column}.")
    permitted_statuses = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    if not source[status_column].isin(permitted_statuses).all():
        raise ValueError("Source includes unverified zero or missing-report cells.")

    source_period = pd.to_datetime({
        "year": source["year"].astype(int),
        "month": source["month"].astype(int),
        "day": 1,
    })
    # The final source month is the next-month target for the last development
    # reference month. No previously inspected holdout rows are feature-engineered.
    source = source.loc[source_period <= DEVELOPMENT_SOURCE_END].copy()
    data = engineer_features(source, include_target=True)
    data = data.dropna(subset=["target_next_cases", "cases_lag_1"]).reset_index(drop=True)
    periods = sorted(data["period"].unique())
    folds = _rolling_folds(periods)
    feature_variants = _feature_variants()

    fold_results = []
    predictions_by_candidate = {
        (candidate["name"], variant_name): []
        for candidate in CANDIDATES
        for variant_name in feature_variants
    }
    actual_parts = []
    baseline_parts = {"persistence": [], "seasonal_naive": [], "trailing_3_month_mean": []}

    for fold_number, (train_periods, validation_periods) in enumerate(folds, start=1):
        train = data[data["period"].isin(train_periods)]
        validation = data[data["period"].isin(validation_periods)]
        if train.empty or validation.empty:
            raise ValueError(f"Rolling fold {fold_number} has an empty partition.")
        actual = validation["target_next_cases"].to_numpy(dtype=float)
        actual_parts.append(actual)

        persistence = np.maximum(0, validation["case_count"].to_numpy(dtype=float))
        seasonal = []
        trailing = []
        case_lookup = data.set_index(["barangay", "period"])["case_count"]
        for row in validation[["barangay", "period"]].itertuples(index=False):
            target_period = row.period + pd.DateOffset(months=1)
            seasonal_period = target_period - pd.DateOffset(years=1)
            seasonal.append(case_lookup.get((row.barangay, seasonal_period), np.nan))
            recent = [
                case_lookup.get((row.barangay, row.period - pd.DateOffset(months=lag)), np.nan)
                for lag in range(3)
            ]
            trailing.append(float(np.mean(recent)) if not pd.isna(recent).any() else np.nan)
        if np.isnan(seasonal).any() or np.isnan(trailing).any():
            raise ValueError(f"A simple baseline is unavailable in rolling fold {fold_number}.")
        baseline_parts["persistence"].append(persistence)
        baseline_parts["seasonal_naive"].append(np.maximum(0, np.asarray(seasonal, dtype=float)))
        baseline_parts["trailing_3_month_mean"].append(np.maximum(0, np.asarray(trailing, dtype=float)))

        fold_entry = {
            "fold": fold_number,
            "training_reference_start": pd.Timestamp(min(train_periods)).strftime("%Y-%m"),
            "training_reference_end": pd.Timestamp(max(train_periods)).strftime("%Y-%m"),
            "validation_reference_start": pd.Timestamp(min(validation_periods)).strftime("%Y-%m"),
            "validation_reference_end": pd.Timestamp(max(validation_periods)).strftime("%Y-%m"),
            "rows": int(len(validation)),
            "candidates": {},
        }
        for candidate in CANDIDATES:
            fold_entry["candidates"][candidate["name"]] = {}
            for variant_name, variant_columns in feature_variants.items():
                pipeline, feature_columns = _candidate_pipeline(
                    candidate, feature_columns=variant_columns
                )
                pipeline.fit(train[feature_columns], train["target_next_cases"])
                predicted = np.maximum(0, pipeline.predict(validation[feature_columns]))
                predictions_by_candidate[(candidate["name"], variant_name)].append(predicted)
                fold_entry["candidates"][candidate["name"]][variant_name] = {
                    "features": feature_columns,
                    **_score(actual, predicted),
                    "hotspot": _hotspot_score(actual, predicted),
                }
        fold_results.append(fold_entry)

    actual_all = np.concatenate(actual_parts)
    baselines_all = {name: np.concatenate(parts) for name, parts in baseline_parts.items()}
    candidate_summary = []
    for candidate in CANDIDATES:
        for variant_name, feature_columns in feature_variants.items():
            predicted_all = np.concatenate(
                predictions_by_candidate[(candidate["name"], variant_name)]
            )
            candidate_summary.append({
                "name": candidate["name"],
                "feature_variant": variant_name,
                "features": feature_columns,
                "parameters": {key: value for key, value in candidate.items() if key not in {"name", "feature_policy"}},
                **_score(actual_all, predicted_all),
                "hotspot": _hotspot_score(actual_all, predicted_all),
                "fold_mae": [fold["candidates"][candidate["name"]][variant_name]["mae"] for fold in fold_results],
                "fold_rmse": [fold["candidates"][candidate["name"]][variant_name]["rmse"] for fold in fold_results],
            })

    baseline_summary = {
        name: {**_score(actual_all, prediction), "hotspot": _hotspot_score(actual_all, prediction)}
        for name, prediction in baselines_all.items()
    }
    selected = min(candidate_summary, key=lambda item: (item["mae"], item["rmse"]))
    report = {
        "analysis_type": "exploratory_expanding_window_validation_only",
        "source_cutoff_inclusive": DEVELOPMENT_SOURCE_END.strftime("%Y-%m"),
        "validation_reference_start": pd.Timestamp(min(fold[1][0] for fold in folds)).strftime("%Y-%m"),
        "validation_reference_end": pd.Timestamp(max(fold[1][-1] for fold in folds)).strftime("%Y-%m"),
        "validation_windows": len(folds),
        "validation_rows": int(len(actual_all)),
        "partition_policy": "Expanding chronological training windows; validation blocks do not overlap; all barangays for a reference month remain together.",
        "preprocessing_policy": "A fresh imputer and encoder are fitted on each fold's training rows only.",
        "case_feature_policy": (
            "Lag, rolling-average, and momentum features are calculated separately per barangay, "
            "from prior completed monthly records only. Rolling means use shift(1), so the current "
            "reference-month count is excluded from those rolling features. All rows from each "
            "reference month remain in the same fold."
        ),
        "hotspot_evaluation_policy": (
            f"Observed hotspot = next-month case count >= {HOTSPOT_THRESHOLD}; "
            f"predicted hotspot = model forecast >= {PREDICTED_HOTSPOT_THRESHOLD}. "
            "These are the project's current internal review thresholds."
        ),
        "feature_variants": {name: columns for name, columns in feature_variants.items()},
        "later_holdout_start": "2024-06",
        "later_period_holdout_scored": False,
        "later_period_rows_used_for_features_or_tuning": False,
        "validation_previously_used_for_model_selection": True,
        "selected_by_validation_mae_then_rmse": {
            "model": selected["name"],
            "feature_variant": selected["feature_variant"],
        },
        "baseline_results": baseline_summary,
        "candidate_results": candidate_summary,
        "fold_results": fold_results,
        "interpretation": (
            "Exploratory only: prior development-period results have informed earlier model choices. "
            "Do not treat this as an independent final test or replace the deployed model solely on this result. "
            "Confirm the selected pipeline on a newly collected later period before claiming improved future performance."
        ),
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
