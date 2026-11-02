"""Evaluate direct hotspot classifiers on the existing rolling windows.

This is validation-only. It deliberately does not create or replace a deployed
model artifact because the available later holdout has already been inspected.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:
    from .exploratory_rolling_validation import (
        DATA_PATH,
        DEVELOPMENT_SOURCE_END,
        HOTSPOT_THRESHOLD,
        _rolling_folds,
    )
    from .features import FEATURES, engineer_features
except ImportError:
    from exploratory_rolling_validation import (
        DATA_PATH,
        DEVELOPMENT_SOURCE_END,
        HOTSPOT_THRESHOLD,
        _rolling_folds,
    )
    from features import FEATURES, engineer_features


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = Path(__file__).with_name("hotspot_classifier_rolling_validation.json")
THRESHOLDS = (0.30, 0.40, 0.50, 0.60, 0.70, 0.80)
CANDIDATES = [
    {"name": "RF classifier baseline", "n_estimators": 300, "max_depth": None,
     "min_samples_leaf": 2, "max_features": 0.8, "class_weight": None},
    {"name": "RF classifier depth 10", "n_estimators": 300, "max_depth": 10,
     "min_samples_leaf": 2, "max_features": 0.8, "class_weight": None},
    {"name": "RF classifier conservative", "n_estimators": 500, "max_depth": 10,
     "min_samples_leaf": 4, "max_features": 0.8, "class_weight": None},
    {"name": "RF classifier balanced", "n_estimators": 300, "max_depth": 10,
     "min_samples_leaf": 2, "max_features": 0.8, "class_weight": "balanced_subsample"},
    {"name": "RF classifier balanced conservative", "n_estimators": 500, "max_depth": 10,
     "min_samples_leaf": 4, "max_features": 0.8, "class_weight": "balanced_subsample"},
]


def _pipeline(candidate):
    numeric = [column for column in FEATURES if column != "barangay"]
    preprocessing = ColumnTransformer([
        ("barangay", OneHotEncoder(handle_unknown="ignore"), ["barangay"]),
        ("numeric", SimpleImputer(strategy="median"), numeric),
    ])
    classifier = RandomForestClassifier(
        n_estimators=candidate["n_estimators"],
        max_depth=candidate["max_depth"],
        min_samples_leaf=candidate["min_samples_leaf"],
        max_features=candidate["max_features"],
        class_weight=candidate["class_weight"],
        random_state=42,
        n_jobs=-1,
    )
    return Pipeline([("preprocess", preprocessing), ("model", classifier)])


def _score(actual, probability, threshold):
    actual = np.asarray(actual, dtype=bool)
    predicted = np.asarray(probability) >= threshold
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(
        actual, predicted, labels=[False, True]
    ).ravel())
    return {
        "probability_threshold": threshold,
        "precision": round(float(precision_score(actual, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(actual, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(actual, predicted, zero_division=0)), 4),
        "flagged_rows": int(predicted.sum()),
        "confusion_matrix_tn_fp_fn_tp": [tn, fp, fn, tp],
    }


def _count_metrics(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return {
        "mae": round(float(np.mean(np.abs(actual - predicted))), 4),
        "rmse": round(float(np.sqrt(np.mean((actual - predicted) ** 2))), 4),
    }


def main():
    source = pd.read_csv(DATA_PATH)
    status_col = "case_observation_status"
    accepted = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    if status_col not in source or not source[status_col].isin(accepted).all():
        raise ValueError("Monthly data has unverified zero or missing-report rows; classifier training stopped.")

    source_dates = pd.to_datetime({
        "year": source["year"].astype(int),
        "month": source["month"].astype(int),
        "day": 1,
    })
    source = source.loc[source_dates <= DEVELOPMENT_SOURCE_END].copy()
    data = engineer_features(source, include_target=True)
    data = data.dropna(subset=["target_next_cases", "cases_lag_1"]).reset_index(drop=True)
    periods = sorted(data["period"].unique())
    folds = _rolling_folds(periods)

    actual_parts = []
    prediction_parts = {candidate["name"]: [] for candidate in CANDIDATES}
    fold_results = []
    baseline_parts = {"persistence": [], "trailing_3_month_mean": []}
    case_lookup = data.set_index(["barangay", "period"])["case_count"]

    for fold_number, (train_periods, validation_periods) in enumerate(folds, start=1):
        train = data[data["period"].isin(train_periods)]
        validation = data[data["period"].isin(validation_periods)]
        actual_counts = validation["target_next_cases"].to_numpy(dtype=float)
        actual_flags = actual_counts >= HOTSPOT_THRESHOLD
        actual_parts.append(actual_flags)

        baseline_parts["persistence"].append(
            validation["case_count"].to_numpy(dtype=float) >= HOTSPOT_THRESHOLD
        )
        trailing = []
        for row in validation[["barangay", "period"]].itertuples(index=False):
            prior = [
                case_lookup.get((row.barangay, row.period - pd.DateOffset(months=lag)), np.nan)
                for lag in range(3)
            ]
            if pd.isna(prior).any():
                raise ValueError(f"Trailing mean unavailable in fold {fold_number}.")
            trailing.append(float(np.mean(prior)) >= HOTSPOT_THRESHOLD)
        baseline_parts["trailing_3_month_mean"].append(np.asarray(trailing, dtype=bool))

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
            model = _pipeline(candidate)
            train_flags = (train["target_next_cases"].to_numpy(dtype=float) >= HOTSPOT_THRESHOLD).astype(int)
            model.fit(train[FEATURES], train_flags)
            class_index = list(model.named_steps["model"].classes_).index(1)
            probability = model.predict_proba(validation[FEATURES])[:, class_index]
            prediction_parts[candidate["name"]].append(probability)
            fold_entry["candidates"][candidate["name"]] = {
                "threshold_results": [
                    _score(actual_flags, probability, threshold)
                    for threshold in THRESHOLDS
                ]
            }
        fold_results.append(fold_entry)

    actual_all = np.concatenate(actual_parts)
    candidate_results = []
    for candidate in CANDIDATES:
        probability = np.concatenate(prediction_parts[candidate["name"]])
        threshold_results = [_score(actual_all, probability, threshold) for threshold in THRESHOLDS]
        candidate_results.append({
            "name": candidate["name"],
            "parameters": {key: value for key, value in candidate.items() if key != "name"},
            "threshold_results": threshold_results,
            "thresholds_meeting_precision_85_recall_75": [
                result["probability_threshold"] for result in threshold_results
                if result["precision"] >= 0.85 and result["recall"] >= 0.75
            ],
            "best_f1_threshold_result": max(threshold_results, key=lambda result: result["f1"]),
        })

    actual_counts = data.loc[data["period"].isin(
        [period for _, validation_periods in folds for period in validation_periods]
    ), "target_next_cases"].to_numpy(dtype=float)
    baseline_results = {}
    for name, pieces in baseline_parts.items():
        flags = np.concatenate(pieces)
        baseline_results[name] = {
            **_score(actual_all, flags.astype(float), 0.5),
            "interpretation": "Count baseline converted to a hotspot flag using the six-case cutoff.",
        }

    report = {
        "analysis_type": "exploratory_direct_hotspot_classifier_rolling_validation_only",
        "validation_rows": int(len(actual_all)),
        "validation_reference_start": pd.Timestamp(min(fold[1][0] for fold in folds)).strftime("%Y-%m"),
        "validation_reference_end": pd.Timestamp(max(fold[1][-1] for fold in folds)).strftime("%Y-%m"),
        "validation_windows": len(folds),
        "target": "1 if observed next-month barangay case_count >= 6; otherwise 0",
        "positive_class": "potential planning hotspot",
        "thresholds": list(THRESHOLDS),
        "fold_policy": "Expanding chronological windows; all barangays from a reference month remain together; preprocessing fits on training rows only.",
        "feature_policy": "Uses the shared case-lag, prior rolling-count, seasonal, barangay, location, and weather features. Missing weather source cells are not filled in the CSV; fold-local median imputation is part of the model pipeline.",
        "source_policy": "Uses datasets/integrated_monthly.csv after verifying its case_observation_status values; synthetic 2018-2019 supplements are not in this active monthly source.",
        "later_holdout_scored": False,
        "validation_previously_used_for_model_selection": True,
        "confusion_matrix_order": "TN, FP, FN, TP",
        "candidate_results": candidate_results,
        "baseline_results": baseline_results,
        "fold_results": fold_results,
        "decision": "Exploratory only. Do not deploy a classifier or claim future 85% performance from these previously explored validation periods. Assess the selected candidate on a newly collected untouched future period.",
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "validation_rows": report["validation_rows"],
        "validation_windows": report["validation_windows"],
        "candidate_results": [
            {"name": result["name"], "best_f1": result["best_f1_threshold_result"],
             "thresholds_meeting_precision_85_recall_75": result["thresholds_meeting_precision_85_recall_75"]}
            for result in candidate_results
        ],
        "baseline_results": baseline_results,
        "output": str(OUTPUT_PATH),
    }, indent=2))
    return report


if __name__ == "__main__":
    main()
