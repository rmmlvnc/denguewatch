"""Train and evaluate DengueWatch's monthly tree-ensemble forecasting model.

Input must contain one row per barangay/month with these columns:
barangay, year, month, case_count, rainfall_mm, temperature_c, humidity_pct.
The target is the following month's case count in the same barangay.
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.metrics import classification_report

try:
    from .features import FEATURES, engineer_features
    from .definition import (
        FORECAST_GEOGRAPHIC_UNIT,
        FORECAST_HORIZON,
        FORECAST_TARGET,
        OBSERVED_HOTSPOT_THRESHOLD,
        PREDICTED_HOTSPOT_THRESHOLD,
        PREDICTION_DEFINITION,
    )
except ImportError:  # Allows: python monitoring/ml/train_model.py ...
    from features import FEATURES, engineer_features
    from definition import (
        FORECAST_GEOGRAPHIC_UNIT,
        FORECAST_HORIZON,
        FORECAST_TARGET,
        OBSERVED_HOTSPOT_THRESHOLD,
        PREDICTED_HOTSPOT_THRESHOLD,
        PREDICTION_DEFINITION,
    )


def prepare_data(csv_path: Path) -> pd.DataFrame:
    data = engineer_features(pd.read_csv(csv_path), include_target=True)
    return data.dropna(subset=['target_next_cases', 'cases_lag_1']).reset_index(drop=True)


def _make_pipeline(parameters: dict, feature_columns=FEATURES) -> Pipeline:
    """Build a fresh preprocessing/model pipeline for one candidate."""
    feature_columns = list(feature_columns)
    numeric_features = [name for name in feature_columns if name != 'barangay']
    preprocess = ColumnTransformer([
        ('barangay', OneHotEncoder(handle_unknown='ignore'), ['barangay']),
        ('numeric', SimpleImputer(strategy='median'), numeric_features),
    ])
    if parameters['algorithm'] != 'RandomForestRegressor':
        raise ValueError('DengueWatch production training is restricted to RandomForestRegressor.')
    model_class = RandomForestRegressor
    return Pipeline([
        ('preprocess', preprocess),
        ('model', model_class(
            n_estimators=parameters['n_estimators'],
            criterion=parameters.get('criterion', 'squared_error'),
            max_depth=parameters.get('max_depth'),
            random_state=42,
            min_samples_leaf=parameters['min_samples_leaf'],
            max_features=parameters['max_features'],
            n_jobs=-1,
        )),
    ])


def _baseline_predictions(data: pd.DataFrame, test_data: pd.DataFrame) -> dict[str, np.ndarray]:
    """Generate next-month baselines from case values available at issue time."""
    case_lookup = data.set_index(['barangay', 'period'])['case_count']
    persistence = test_data['case_count'].to_numpy(dtype=float)
    seasonal = []
    trailing_three = []
    for row in test_data[['barangay', 'period']].itertuples(index=False):
        target_period = row.period + pd.DateOffset(months=1)
        seasonal_period = target_period - pd.DateOffset(years=1)
        seasonal.append(case_lookup.get((row.barangay, seasonal_period), np.nan))
        previous = [
            case_lookup.get((row.barangay, row.period - pd.DateOffset(months=offset)), np.nan)
            for offset in range(3)
        ]
        trailing_three.append(float(np.mean(previous)) if not pd.isna(previous).any() else np.nan)
    return {
        'persistence': persistence,
        'seasonal_naive_same_month_last_year': np.asarray(seasonal, dtype=float),
        'trailing_3_month_mean': np.asarray(trailing_three, dtype=float),
    }


def _score_forecasts(actual: pd.Series, predicted: np.ndarray) -> dict:
    return {
        'rows': int(len(actual)),
        'mae': round(float(mean_absolute_error(actual, predicted)), 4),
        'rmse': round(float(mean_squared_error(actual, predicted) ** 0.5), 4),
    }


def _score_hotspot_classification(
    actual_counts,
    predicted_counts,
    actual_threshold: int,
    predicted_threshold: float | None = None,
) -> dict:
    """Score the threshold-defined hotspot task separately from count error."""
    predicted_threshold = predicted_threshold or actual_threshold
    actual_hotspot = np.asarray(actual_counts, dtype=float) >= actual_threshold
    predicted_hotspot = np.asarray(predicted_counts, dtype=float) >= predicted_threshold
    per_class_precision, per_class_recall, per_class_f1, per_class_support = precision_recall_fscore_support(
        actual_hotspot,
        predicted_hotspot,
        labels=[False, True],
        average=None,
        zero_division=0,
    )
    matrix = confusion_matrix(actual_hotspot, predicted_hotspot, labels=[False, True])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    return {
        'rows': int(len(actual_hotspot)),
        'threshold_cases': int(actual_threshold),
        'predicted_count_cutoff': predicted_threshold,
        'positive_class': f'at_least_{actual_threshold}_observed_cases',
        # Keep positive-class convenience metrics for baseline comparison,
        # and retain class-wise metrics so both hotspot and non-hotspot
        # performance can be reviewed as requested by the adviser.
        'precision': round(float(per_class_precision[1]), 4),
        'recall': round(float(per_class_recall[1]), 4),
        'f1': round(float(per_class_f1[1]), 4),
        'accuracy': round(float((tn + tp) / len(actual_hotspot)), 4) if len(actual_hotspot) else 0.0,
        'per_class': {
            'not_hotspot': {
                'precision': round(float(per_class_precision[0]), 4),
                'recall': round(float(per_class_recall[0]), 4),
                'f1': round(float(per_class_f1[0]), 4),
                'support': int(per_class_support[0]),
            },
            'hotspot': {
                'precision': round(float(per_class_precision[1]), 4),
                'recall': round(float(per_class_recall[1]), 4),
                'f1': round(float(per_class_f1[1]), 4),
                'support': int(per_class_support[1]),
            },
        },
        'actual_hotspot_rows': int(actual_hotspot.sum()),
        'predicted_hotspot_rows': int(predicted_hotspot.sum()),
        'confusion_matrix': {
            'labels': ['not_hotspot', 'hotspot'],
            'rows_actual_columns_predicted': [[tn, fp], [fn, tp]],
            'true_negative': tn,
            'false_positive': fp,
            'false_negative': fn,
            'true_positive': tp,
        },
    }


def train(csv_path: Path, output_path: Path, metrics_path: Path) -> dict:
    source_data = pd.read_csv(csv_path)
    if 'case_observation_status' not in source_data.columns:
        raise ValueError(
            'The source dataset has no case_observation_status field. Rebuild the '
            'monthly dataset and verify zero-report completeness before training.'
        )
    unverified = source_data['case_observation_status'].eq(
        'no_records_zero_vs_missing_unverified'
    )
    invalid_status = ~source_data['case_observation_status'].isin([
        'cases_present_line_list_count', 'zero_confirmed_by_cho',
    ])
    if unverified.any() or invalid_status.any():
        raise ValueError(
            f'{int(unverified.sum())} barangay-month cells have no source rows, '
            f'and {int(invalid_status.sum())} cells have no recognized reporting status. '
            'The source does not confirm whether empty cells are true zero reports '
            'or missing reports. Training is blocked until CHO reporting completeness '
            'is verified; mark only documented zero reports as '
            "'zero_confirmed_by_cho' in case_observation_status."
        )
    data = prepare_data(csv_path)
    weather_metadata_path = csv_path.parent / 'weather_source.json'
    try:
        weather_metadata = json.loads(weather_metadata_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        weather_metadata = {}
    if len(data) < 50:
        raise ValueError('At least 50 usable barangay-month rows are required.')

    # Use a chronological outer split closest to 75/25 while keeping whole
    # months together (all barangays from a month stay in one partition).
    # Inside the earlier 75% development period, reserve the later quarter
    # for validation and tune candidates without touching the final holdout.
    periods = sorted(data['period'].unique())
    if len(periods) < 10:
        raise ValueError('At least ten distinct months are required for train, validation, and final test periods.')
    outer_train_end = min(len(periods) - 1, max(1, int(np.ceil(len(periods) * 0.75))))
    train_end = max(1, int(outer_train_end * 0.75))
    validation_end = outer_train_end
    train_periods = periods[:train_end]
    validation_periods = periods[train_end:validation_end]
    final_test_periods = periods[validation_end:]
    if not train_periods or not validation_periods or not final_test_periods:
        raise ValueError('Chronological train/validation/final-test partitions must each contain at least one month.')

    train_data = data[data['period'].isin(train_periods)]
    validation_data = data[data['period'].isin(validation_periods)]
    final_test_data = data[data['period'].isin(final_test_periods)]
    # Select hyperparameters using validation months inside the earlier
    # development partition. The later 25% test period is not used for selection.
    # The user-selected production model is Random Forest Regression. Keep
    # candidate tuning within this estimator family; do not switch to
    # ExtraTrees based on validation scores.
    candidates = [
        {'algorithm': 'RandomForestRegressor', 'criterion': 'squared_error', 'n_estimators': 300, 'min_samples_leaf': 1, 'max_features': 0.8, 'max_depth': None},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'squared_error', 'n_estimators': 300, 'min_samples_leaf': 3, 'max_features': 0.8, 'max_depth': 12},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'squared_error', 'n_estimators': 400, 'min_samples_leaf': 5, 'max_features': 0.8, 'max_depth': 12},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'squared_error', 'n_estimators': 500, 'min_samples_leaf': 8, 'max_features': 1.0, 'max_depth': 10},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'squared_error', 'n_estimators': 500, 'min_samples_leaf': 12, 'max_features': 0.8, 'max_depth': 8},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'absolute_error', 'n_estimators': 200, 'min_samples_leaf': 1, 'max_features': 0.8, 'max_depth': 10},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'absolute_error', 'n_estimators': 200, 'min_samples_leaf': 3, 'max_features': 0.8, 'max_depth': 12},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'absolute_error', 'n_estimators': 200, 'min_samples_leaf': 5, 'max_features': 1.0, 'max_depth': None},
        {'algorithm': 'RandomForestRegressor', 'criterion': 'absolute_error', 'n_estimators': 300, 'min_samples_leaf': 8, 'max_features': 0.8, 'max_depth': 10},
    ]
    candidate_results = []
    candidate_cutoff_results = []
    # The review cutoff is a project configuration fixed before this training
    # run. Compare model settings at that cutoff; do not choose a different
    # cutoff by repeatedly inspecting the final holdout.
    candidate_predicted_cutoffs = (PREDICTED_HOTSPOT_THRESHOLD,)
    for parameters in candidates:
        candidate_pipeline = _make_pipeline(parameters)
        candidate_pipeline.fit(
            train_data[FEATURES],
            train_data['target_next_cases'],
        )
        validation_prediction = np.maximum(
            0, candidate_pipeline.predict(validation_data[FEATURES])
        )
        val_mae = float(mean_absolute_error(
            validation_data['target_next_cases'], validation_prediction
        ))
        val_rmse = float(mean_squared_error(
            validation_data['target_next_cases'], validation_prediction
        ) ** 0.5)
        cutoff_scores = []
        for cutoff in candidate_predicted_cutoffs:
            score = _score_hotspot_classification(
                validation_data['target_next_cases'],
                validation_prediction,
                OBSERVED_HOTSPOT_THRESHOLD,
                cutoff,
            )
            score['predicted_count_cutoff'] = cutoff
            cutoff_scores.append(score)
            candidate_cutoff_results.append({
                'parameters': parameters,
                'predicted_count_cutoff': cutoff,
                'validation_mae': val_mae,
                'validation_rmse': val_rmse,
                'validation_hotspot': score,
            })
        candidate_results.append({
            'parameters': parameters,
            'validation_mae': val_mae,
            'validation_rmse': val_rmse,
            'validation_hotspot_by_predicted_cutoff': cutoff_scores,
        })
    # Select on validation classification accuracy while keeping the project's
    # existing precision and recall floors. The later-period holdout does not
    # participate in model or cutoff selection.
    minimum_precision = 0.85
    minimum_recall = 0.40
    eligible = [row for row in candidate_cutoff_results
                if row['validation_hotspot']['precision'] >= minimum_precision
                and row['validation_hotspot']['recall'] >= minimum_recall]
    if not eligible:
        raise ValueError(
            'No validation candidate meets the minimum hotspot precision and recall '
            'constraints; the deployed model settings were not selected.'
        )
    selected = max(eligible, key=lambda result: (
        result['validation_hotspot']['accuracy'],
        result['validation_hotspot']['f1'],
        -result['validation_mae'],
        -result['predicted_count_cutoff'],
    ))
    selected_parameters = selected['parameters']
    selected_predicted_cutoff = selected['predicted_count_cutoff']
    selection_rule = (
        f'Highest unweighted chronological validation hotspot accuracy among RandomForestRegressor '
        f'parameter candidates at the configured predicted-count cutoff ({PREDICTED_HOTSPOT_THRESHOLD:g}), '
        'subject to precision >= 85% and recall >= 40%; ties use higher F1, then lower case-count MAE.'
    )

    # Record validation metrics at the fixed precision-focused review cutoff.
    validation_pipeline = _make_pipeline(selected_parameters)
    validation_pipeline.fit(
        train_data[FEATURES],
        train_data['target_next_cases'],
    )
    validation_predicted = np.maximum(
        0, validation_pipeline.predict(validation_data[FEATURES])
    )
    validation_hotspot = _score_hotspot_classification(
        validation_data['target_next_cases'],
        validation_predicted,
        OBSERVED_HOTSPOT_THRESHOLD,
        selected_predicted_cutoff,
    )
    unweighted_validation_pipeline = _make_pipeline(selected_parameters)
    unweighted_validation_pipeline.fit(
        train_data[FEATURES], train_data['target_next_cases']
    )
    unweighted_validation_predicted = np.maximum(
        0, unweighted_validation_pipeline.predict(validation_data[FEATURES])
    )
    unweighted_validation_hotspot = _score_hotspot_classification(
        validation_data['target_next_cases'],
        unweighted_validation_predicted,
        OBSERVED_HOTSPOT_THRESHOLD,
        selected_predicted_cutoff,
    )

    # Score the later-period holdout after model settings are selected. This
    # historical holdout has been inspected in prior project iterations, so
    # its scores must not be described as an untouched independent test.
    evaluation_data = pd.concat([train_data, validation_data]).sort_values(['period', 'barangay'])
    evaluation_pipeline = _make_pipeline(selected_parameters)
    evaluation_pipeline.fit(
        evaluation_data[FEATURES],
        evaluation_data['target_next_cases'],
    )
    predicted = np.maximum(0, evaluation_pipeline.predict(final_test_data[FEATURES]))
    actual = final_test_data['target_next_cases']
    y_true = (actual.to_numpy() >= OBSERVED_HOTSPOT_THRESHOLD).astype(int)
    y_pred = (predicted >= selected_predicted_cutoff).astype(int)

    report = classification_report(
        y_true,
        y_pred,
        labels=[0, 1],
        target_names=["Not hotspot", "Hotspot"],
        zero_division=0,
        output_dict=True,
    )
    print(f"{'Class':<16}{'Precision':>12}{'Recall':>11}{'F1-score':>12}{'Support':>11}")
    for class_name in ("Not hotspot", "Hotspot"):
        scores = report[class_name]
        print(
            f"{class_name:<16}{scores['precision'] * 100:>10.2f}%"
            f"{scores['recall'] * 100:>9.2f}%"
            f"{scores['f1-score'] * 100:>10.2f}%"
            f"{int(scores['support']):>11}"
        )
    print(
        f"{'Accuracy':<16}{'':>12}{'':>11}"
        f"{report['accuracy'] * 100:>10.2f}%{len(y_true):>11}"
    )
    for average_name, label in (("Macro avg", "macro avg"), ("Weighted avg", "weighted avg")):
        scores = report[label]
        print(
            f"{average_name:<16}{scores['precision'] * 100:>10.2f}%"
            f"{scores['recall'] * 100:>9.2f}%"
            f"{scores['f1-score'] * 100:>10.2f}%"
            f"{int(scores['support']):>11}"
        )
    # Persistence is the minimum useful baseline for a next-month forecast:
    # predict that the next monthly total will equal this month's total.
    # A model should not be presented as an improvement unless it beats this
    # baseline on the same chronological holdout period.
    baseline_predictions = _baseline_predictions(data, final_test_data)
    baseline_predictions['persistence'] = np.maximum(0, baseline_predictions['persistence'])
    baseline_predictions['seasonal_naive_same_month_last_year'] = np.maximum(
        0, baseline_predictions['seasonal_naive_same_month_last_year']
    )
    baseline_predictions['trailing_3_month_mean'] = np.maximum(
        0, baseline_predictions['trailing_3_month_mean']
    )
    baseline = baseline_predictions['persistence']
    model_mae = float(mean_absolute_error(actual, predicted))
    model_rmse = float(mean_squared_error(actual, predicted) ** 0.5)
    baseline_mae = float(mean_absolute_error(actual, baseline))
    baseline_rmse = float(mean_squared_error(actual, baseline) ** 0.5)
    baseline_comparison = {}
    ordered_test_periods = sorted(final_test_data['period'].unique())
    period_to_block = {
        period: index // 4 for index, period in enumerate(ordered_test_periods)
    }
    row_block_ids = final_test_data['period'].map(period_to_block).to_numpy()
    for name, values in baseline_predictions.items():
        if len(values) != len(actual) or np.isnan(values).any():
            raise ValueError(f'The {name} baseline cannot be calculated for every final-test row.')
        blocks = []
        target_periods = final_test_data['period'] + pd.DateOffset(months=1)
        block_frame = pd.DataFrame({
            'actual': actual.to_numpy(),
            'predicted': values,
            'target_period': target_periods.to_numpy(),
            'block_id': row_block_ids,
        })
        for block_id, block in block_frame.groupby('block_id', sort=True):
            scores = _score_forecasts(block['actual'], block['predicted'].to_numpy())
            scores.update({
                'target_period_start': pd.Timestamp(block['target_period'].min()).strftime('%Y-%m'),
                'target_period_end': pd.Timestamp(block['target_period'].max()).strftime('%Y-%m'),
            })
            blocks.append(scores)
        baseline_comparison[name] = {
            'overall': _score_forecasts(actual, values),
            'four_month_test_blocks': blocks,
        }
    model_blocks = []
    model_block_frame = pd.DataFrame({
        'actual': actual.to_numpy(),
        'predicted': predicted,
        'target_period': (final_test_data['period'] + pd.DateOffset(months=1)).to_numpy(),
        'block_id': row_block_ids,
    })
    for _, block in model_block_frame.groupby('block_id', sort=True):
        scores = _score_forecasts(block['actual'], block['predicted'].to_numpy())
        scores.update({
            'target_period_start': pd.Timestamp(block['target_period'].min()).strftime('%Y-%m'),
            'target_period_end': pd.Timestamp(block['target_period'].max()).strftime('%Y-%m'),
        })
        model_blocks.append(scores)
    hotspot_classification = {
        'task': 'Flag barangays for planning review using the predicted-count cutoff; the observed hotspot label has a separate actual-case threshold.',
        'threshold_cases': OBSERVED_HOTSPOT_THRESHOLD,
        'predicted_count_cutoff': selected_predicted_cutoff,
        'positive_class': f'at_least_{OBSERVED_HOTSPOT_THRESHOLD}_observed_cases',
        'model_overall': _score_hotspot_classification(
            actual, predicted, OBSERVED_HOTSPOT_THRESHOLD, selected_predicted_cutoff
        ),
        'model_four_month_test_blocks': [],
        'simple_baseline_comparison': {},
    }
    for _, block in model_block_frame.groupby('block_id', sort=True):
        scores = _score_hotspot_classification(
            block['actual'], block['predicted'], OBSERVED_HOTSPOT_THRESHOLD, selected_predicted_cutoff
        )
        scores.update({
            'target_period_start': pd.Timestamp(block['target_period'].min()).strftime('%Y-%m'),
            'target_period_end': pd.Timestamp(block['target_period'].max()).strftime('%Y-%m'),
        })
        hotspot_classification['model_four_month_test_blocks'].append(scores)
    for name, values in baseline_predictions.items():
        baseline_blocks = []
        for _, block in model_block_frame.assign(baseline=values).groupby('block_id', sort=True):
            scores = _score_hotspot_classification(
                block['actual'], block['baseline'], OBSERVED_HOTSPOT_THRESHOLD, selected_predicted_cutoff
            )
            scores.update({
                'target_period_start': pd.Timestamp(block['target_period'].min()).strftime('%Y-%m'),
                'target_period_end': pd.Timestamp(block['target_period'].max()).strftime('%Y-%m'),
            })
            baseline_blocks.append(scores)
        hotspot_classification['simple_baseline_comparison'][name] = {
            'overall': _score_hotspot_classification(
                actual, values, OBSERVED_HOTSPOT_THRESHOLD, selected_predicted_cutoff
            ),
            'four_month_test_blocks': baseline_blocks,
        }
    model_hotspot_beats_all_baselines_overall = all(
        hotspot_classification['model_overall']['f1'] > comparison['overall']['f1']
        for comparison in hotspot_classification['simple_baseline_comparison'].values()
    )
    model_hotspot_beats_all_baselines_each_block = all(
        model_block['f1'] > baseline_block['f1']
        for name, comparison in hotspot_classification['simple_baseline_comparison'].items()
        for model_block, baseline_block in zip(
            hotspot_classification['model_four_month_test_blocks'],
            comparison['four_month_test_blocks'],
        )
    )
    model_beats_all_baselines_each_block = all(
        model_block['mae'] < baseline_block['mae']
        and model_block['rmse'] < baseline_block['rmse']
        for name in baseline_comparison
        for model_block, baseline_block in zip(
            model_blocks, baseline_comparison[name]['four_month_test_blocks']
        )
    )
    model_beats_all_baselines_overall = all(
        model_mae < score['overall']['mae'] and model_rmse < score['overall']['rmse']
        for score in baseline_comparison.values()
    )
    beats_persistence = (
        model_mae < baseline_mae and model_rmse < baseline_rmse
    )
    mae_change_pct = (
        ((baseline_mae - model_mae) / baseline_mae) * 100
        if baseline_mae > 0 else None
    )
    datasets_dir = Path(__file__).resolve().parents[2] / 'datasets'
    synthetic_manifest_path = datasets_dir / 'synthetic_supplement' / 'manifest.json'
    try:
        synthetic_manifest = json.loads(synthetic_manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        synthetic_manifest = None
    historical_manifest_path = datasets_dir / 'cho_historical' / 'manifest.json'
    try:
        historical_manifest = json.loads(historical_manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        historical_manifest = None
    historical_datasets = historical_manifest.get('historical_datasets', {}) if historical_manifest else {}
    metrics = {
        'dataset_rows': int(len(pd.read_csv(csv_path))),
        'case_source_file': 'WILBUR_DSO_dengue_2018_2026_authoritative.csv',
        'case_source_quality_audit': 'dengue_dataset_quality.json',
        'case_source_original_dataset_files': json.loads(
            (Path(__file__).resolve().parents[2] / 'datasets' / 'dengue_dataset_quality.json').read_text(encoding='utf-8')
        ).get('source_files', []),
        'case_source_all_rows_retained': json.loads(
            (Path(__file__).resolve().parents[2] / 'datasets' / 'dengue_dataset_quality.json').read_text(encoding='utf-8')
        ).get('all_rows_retained'),
        'included_cho_historical_source_rows': sum(
            item.get('rows', item.get('rows_by_admission_date', 0))
            for item in historical_datasets.values()
        ),
        'cho_historical_source_attribution': (
            historical_manifest.get('source_attribution') if historical_manifest else None
        ),
        'cho_historical_exact_duplicate_extra_rows': sum(
            (item.get('exact_duplicate_extra_rows') or 0) for item in historical_datasets.values()
        ),
        'excluded_synthetic_supplement_rows': synthetic_manifest.get('total_rows', 0) if synthetic_manifest else 0,
        'excluded_synthetic_supplement_years': [item.get('year') for item in synthetic_manifest.get('datasets', [])] if synthetic_manifest else [],
        'synthetic_supplement_requested_demo_rows': {str(key): value for key, value in synthetic_manifest.get('requested_row_counts', {}).items()} if synthetic_manifest else {},
        'synthetic_supplement_training_policy': 'The earlier explicitly synthetic 2018-2019 submissions remain archived and excluded; the newer 2018-2019 CHO-verified submissions are included in the active source.',
        'weather_missing_months': sorted({
            f"{int(row.year):04d}-{int(row.month):02d}"
            for row in source_data.loc[
                source_data[['rainfall_mm', 'temperature_c', 'humidity_pct']].isna().any(axis=1),
                ['year', 'month'],
            ].itertuples(index=False)
        }),
        'weather_rows_with_missing_values': int(
            source_data[['rainfall_mm', 'temperature_c', 'humidity_pct']].isna().any(axis=1).sum()
        ),
        'training_weather_source': weather_metadata.get('source', 'Not documented'),
        'training_weather_source_status': weather_metadata.get('weather_source_status', 'Not documented'),
        'training_weather_scope': weather_metadata.get('weather_scope', 'Not documented'),
        'training_weather_distinct_grid_cells': int(
            source_data[['grid_latitude', 'grid_longitude']].dropna().drop_duplicates().shape[0]
        ) if {'grid_latitude', 'grid_longitude'}.issubset(source_data.columns) else None,
        'source_no_record_month_cells': int(
            source_data.get('case_observation_status', pd.Series(dtype=object))
            .eq('no_records_zero_vs_missing_unverified').sum()
        ),
        'source_zero_month_cells_under_user_completeness_confirmation': int(
            source_data.get('case_observation_status', pd.Series(dtype=object))
            .eq('zero_confirmed_by_cho').sum()
        ),
        'usable_rows': int(len(data)),
        'training_rows': int(len(train_data)),
        'validation_rows': int(len(validation_data)),
        'test_rows': int(len(final_test_data)),
        'outer_training_rows': int(len(train_data) + len(validation_data)),
        'outer_training_share_pct': round((len(train_data) + len(validation_data)) / len(data) * 100, 2),
        'outer_test_share_pct': round(len(final_test_data) / len(data) * 100, 2),
        'outer_training_months': int(len(train_periods) + len(validation_periods)),
        'outer_test_months': int(len(final_test_periods)),
        'outer_split_policy': 'Chronological approximately 75/25 outer split by whole reference month; all barangays from a month remain in one partition. The earlier 75% development period is internally split into fitting and validation periods for model selection.',
        'validation_scheme': 'chronological_inner_validation_with_previously_inspected_later_holdout',
        'outer_training_period_start': pd.Timestamp(train_periods[0]).strftime('%Y-%m'),
        'outer_training_period_end': pd.Timestamp(validation_periods[-1]).strftime('%Y-%m'),
        'training_period_start': pd.Timestamp(train_periods[0]).strftime('%Y-%m'),
        'training_period_end': pd.Timestamp(train_periods[-1]).strftime('%Y-%m'),
        'validation_start': pd.Timestamp(validation_periods[0]).strftime('%Y-%m'),
        'validation_end': pd.Timestamp(validation_periods[-1]).strftime('%Y-%m'),
        'final_test_start': pd.Timestamp(final_test_periods[0]).strftime('%Y-%m'),
        'final_test_end': pd.Timestamp(final_test_periods[-1]).strftime('%Y-%m'),
        'final_test_target_start': (pd.Timestamp(final_test_periods[0]) + pd.DateOffset(months=1)).strftime('%Y-%m'),
        'final_test_target_end': (pd.Timestamp(final_test_periods[-1]) + pd.DateOffset(months=1)).strftime('%Y-%m'),
        'validation_selected_parameters': selected_parameters,
        'validation_selected_predicted_hotspot_cutoff_cases': selected_predicted_cutoff,
        'validation_selected_hotspot_metrics': selected['validation_hotspot'],
        'validation_selection_candidate_cutoff_scores': candidate_cutoff_results,
        'validation_candidate_scores': [
            {
                **result,
                'validation_mae': round(result['validation_mae'], 4),
                'validation_rmse': round(result['validation_rmse'], 4),
            }
            for result in candidate_results
        ],
        'validation_model_selection_rule': selection_rule,
        'validation_objective': 'Maximize unweighted hotspot classification accuracy subject to at least 85% precision and 40% recall; ties use F1, case-count MAE, then lower cutoff.',
        'validation_precision_recall_constraints': {
            'precision_at_least': 0.85,
            'recall_at_least': 0.40,
            'observed_hotspot_threshold_cases': OBSERVED_HOTSPOT_THRESHOLD,
            'predicted_count_cutoff_cases': selected_predicted_cutoff,
        },
        'mae': round(model_mae, 4),
        'rmse': round(model_rmse, 4),
        'r2': round(float(r2_score(actual, predicted)), 4) if len(actual) > 1 else None,
        'persistence_baseline_name': 'Persistence (same as most recent month)',
        'persistence_baseline_mae': round(baseline_mae, 4),
        'persistence_baseline_rmse': round(baseline_rmse, 4),
        'beats_persistence_baseline': beats_persistence,
        'baseline_comparison': baseline_comparison,
        'hotspot_classification_evaluation': hotspot_classification,
        'hotspot_precision_target_pct': 85.0,
        'validation_hotspot_classification': validation_hotspot,
        'unweighted_validation_hotspot_classification': unweighted_validation_hotspot,
        'training_objective': 'Select the Random Forest settings and predicted-count cutoff by validation hotspot accuracy subject to minimum precision and recall constraints; every training row has equal weight.',
        'fit_training_hotspot_rows': int(
            (train_data['target_next_cases'] >= OBSERVED_HOTSPOT_THRESHOLD).sum()
        ),
        'fit_training_non_hotspot_rows': int(
            (train_data['target_next_cases'] < OBSERVED_HOTSPOT_THRESHOLD).sum()
        ),
        'validation_hotspot_precision_target_met': validation_hotspot['precision'] >= 0.85,
        'final_test_hotspot_precision_target_met': (
            hotspot_classification['model_overall']['precision'] >= 0.85
        ),
        'model_four_month_test_blocks': model_blocks,
        'baseline_comparison_rule': 'Retain as a candidate for further evaluation only if model MAE and RMSE both beat persistence, seasonal-naive, and trailing-3-month-mean baselines over the full final test and every consecutive four-month block.',
        'beats_all_baselines_overall': model_beats_all_baselines_overall,
        'beats_all_baselines_each_test_block': model_beats_all_baselines_each_block,
        'mae_change_vs_baseline_pct': round(mae_change_pct, 1) if mae_change_pct is not None else None,
        # Forecasts are intentionally restricted to planning support.  This
        # is particularly important when the model fails the baseline check.
        'hotspot_classification_retention_rule': 'The model must also have a higher hotspot F1 than persistence, seasonal-naive, and trailing-3-month-mean baselines overall and in every consecutive four-month test block. Precision, recall, F1, and confusion counts are reported separately from count errors.',
        'beats_all_hotspot_baselines_overall': model_hotspot_beats_all_baselines_overall,
        'beats_all_hotspot_baselines_each_test_block': model_hotspot_beats_all_baselines_each_block,
        'deployment_status': 'experimental_candidate' if model_beats_all_baselines_overall and model_beats_all_baselines_each_block and model_hotspot_beats_all_baselines_overall and model_hotspot_beats_all_baselines_each_block else 'planning_support_only',
        'blood_type_feature_policy': (
            'Blood type remains available only for aggregate historical profile '
            'display; it is excluded from machine-learning inputs because it is '
            'not part of the study prediction framework.'
        ),
        'weather_feature_policy': (
            'Uses rainfall, mean temperature, and mean relative humidity observed '
            'through the forecast issue month, plus their one-month lags. Missing '
            'weather values are imputed within the training-fitted pipeline.'
        ),
        'case_history_feature_policy': (
            'For a one-month-ahead forecast, case-count inputs are the two '
            'latest complete months available at forecast issue time: the '
            'issue month and the immediately preceding month. Partial current '
            'month reports are excluded. Older case lags and rolling case '
            'averages are not model inputs.'
        ),
        'geographic_feature_policy': (
            'Uses official barangay identity and boundary-derived representative '
            'latitude/longitude as geographic inputs; GIS polygons remain the map '
            'visualization layer.'
        ),
        'privacy_protections': [
            'Use only de-identified barangay-month aggregates.',
            'Lag aggregate features by one month to prevent future-data leakage.',
            'Do not include individual blood-type values in forecast outputs.',
        ],
        'features': FEATURES,
        'target': FORECAST_TARGET,
        'forecast_horizon': FORECAST_HORIZON,
        'geographic_unit': FORECAST_GEOGRAPHIC_UNIT,
        'hotspot_definition': PREDICTION_DEFINITION,
        'hotspot_threshold_cases': OBSERVED_HOTSPOT_THRESHOLD,
        'predicted_hotspot_cutoff_cases': selected_predicted_cutoff,
        'algorithm': selected_parameters['algorithm'],
        'scikit_learn_version': sklearn.__version__,
        'pandas_version': pd.__version__,
        'preprocessing_fit_policy': 'For candidate selection, preprocessing is fitted on training months only and applied to validation months. For the final test evaluation, preprocessing is fitted on the earlier training plus validation months; final-test rows are never used to fit preprocessing or select parameters.',
        'temporal_partition_policy': 'Partitions are chronological and grouped by whole reference calendar month, so all barangays from the same month remain in one partition.',
        'final_test_policy': 'Hyperparameters are selected on validation data; the later-period holdout is not used for parameter selection within a run. This holdout has been inspected in prior project iterations and is not an untouched independent test for new changes. Deployment refitting occurs only after metrics are recorded.',
        'forecast_issue_information_policy': 'Predictors are limited to the issue-month case/weather values and lagged values available at that forecast cutoff; the next-month target and all later observations are excluded from features.',
        'final_deployment_fit_policy': 'After the test score is recorded, the deployment pipeline is refit without sample weights on all available usable historical rows.',
        'random_state': 42,
        'warning': (
            'Planning-support forecast only; validate with authorized health '
            'personnel. It must not be used as a confirmed outbreak or an '
            'automatic alert.'
        ),
    }
    metrics['source_data_quality_note'] = (
        'No unverified empty barangay-month cells were used for this training run. '
        f"{metrics['source_zero_month_cells_under_user_completeness_confirmation']} empty cells were treated as zero under the user's dataset-completeness confirmation; no separate CHO zero-report register was provided."
    )
    # Refit the deployable model on all usable rows after recording holdout
    # metrics. Holdout results do not select settings within this run.
    pipeline = _make_pipeline(selected_parameters)
    pipeline.fit(
        data[FEATURES],
        data['target_next_cases'],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        'pipeline': pipeline,
        'metrics': metrics,
        'predicted_hotspot_threshold': selected_predicted_cutoff,
    }, output_path)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    return metrics


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('csv', type=Path, help='Integrated monthly CSV dataset')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('random_forest.pkl'))
    parser.add_argument('--metrics', type=Path, default=Path(__file__).with_name('model_metrics.json'))
    args = parser.parse_args()
    print(json.dumps(train(args.csv, args.output, args.metrics), indent=2))
