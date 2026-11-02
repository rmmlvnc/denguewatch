"""Create a privacy-safe data inventory and an unverified weekly candidate grid.

Run with: python monitoring/ml/data_feasibility.py
The generated files contain aggregate counts only, never line-list fields.
"""

import json
from pathlib import Path

import pandas as pd

try:
    from monitoring.locations import ILIGAN_BARANGAYS, canonicalize_barangay, is_iligan_city
    from monitoring.ml.build_dataset import read_cases
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from monitoring.locations import ILIGAN_BARANGAYS, canonicalize_barangay, is_iligan_city
    from monitoring.ml.build_dataset import read_cases


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / 'datasets'
COMPLETENESS_PATH = DATASETS / 'case_reporting_completeness.json'


def _active_source_rows() -> tuple[list[Path], pd.DataFrame]:
    authoritative = DATASETS / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv'
    if not authoritative.is_file():
        raise FileNotFoundError(f'Required CHO master dengue dataset is missing: {authoritative}')
    return [authoritative], pd.read_csv(authoritative, dtype=object, encoding='utf-8-sig')


def build_inventory() -> dict:
    source_files, raw = _active_source_rows()
    if raw.empty:
        raise ValueError('No active individual-case source file was found.')
    completeness = json.loads(COMPLETENESS_PATH.read_text(encoding='utf-8')) if COMPLETENESS_PATH.exists() else {}
    complete_case_coverage = completeness.get('no_case_rows_mean_confirmed_zero') is True

    barangay_column = '(Current Address) Barangay'
    date_column = 'DAdmit'
    normalized_barangay = raw.get(barangay_column, pd.Series(index=raw.index, dtype=object)).map(canonicalize_barangay)
    admitted = pd.to_datetime(
        raw.get(date_column, pd.Series(index=raw.index, dtype=object)),
        errors='coerce', format='mixed',
    )
    city_column = '(Current Address) City / Municipality'
    city_ok = raw[city_column].map(is_iligan_city) if city_column in raw else pd.Series(True, index=raw.index)
    usable = normalized_barangay.notna() & admitted.notna() & city_ok

    cases = pd.DataFrame({
        'barangay': normalized_barangay[usable].values,
        'admit_date': admitted[usable].values,
    })
    cases['week_start'] = cases['admit_date'].dt.to_period('W-SUN').dt.start_time.dt.normalize()
    week_counts = cases.groupby(['barangay', 'week_start']).size().rename('reported_case_count').reset_index()

    first_week = cases['week_start'].min()
    last_week = cases['week_start'].max()
    weeks = pd.date_range(first_week, last_week, freq='W-MON')
    grid = pd.MultiIndex.from_product(
        [sorted(ILIGAN_BARANGAYS, key=str.casefold), weeks],
        names=['barangay', 'week_start'],
    ).to_frame(index=False)
    weekly = grid.merge(week_counts, how='left', on=['barangay', 'week_start'])
    weekly['reported_case_count'] = weekly['reported_case_count'].fillna(0).astype(int)
    if complete_case_coverage:
        weekly['reporting_status'] = weekly['reported_case_count'].map(
            lambda count: 'cases_present_line_list_count' if count else 'zero_confirmed_by_cho'
        )
        weekly['zero_confirmed_by_surveillance'] = weekly['reported_case_count'].eq(0)
        weekly['eligible_for_model_training'] = True
    else:
        weekly['reporting_status'] = weekly['reported_case_count'].map(
            lambda count: 'cases_present_completeness_unknown' if count else 'no_records_zero_vs_missing_unverified'
        )
        weekly['zero_confirmed_by_surveillance'] = False
        weekly['eligible_for_model_training'] = False
    weekly['week_end'] = weekly['week_start'] + pd.Timedelta(days=6)
    weekly = weekly[['barangay', 'week_start', 'week_end', 'reported_case_count', 'reporting_status',
                     'zero_confirmed_by_surveillance', 'eligible_for_model_training']]
    weekly_path = DATASETS / 'weekly_feasibility_candidate.csv'
    weekly.to_csv(weekly_path, index=False)

    duplicate_fields = [
        field for field in (
            barangay_column, date_column, 'Sex', 'AgeYears', 'BloodType',
            '(Current Address) Sitio / Purok / Street Name',
        ) if field in raw.columns
    ]
    duplicate_frame = raw.loc[usable, duplicate_fields].copy()
    duplicate_frame[barangay_column] = normalized_barangay[usable].values
    duplicate_frame[date_column] = admitted[usable].dt.strftime('%Y-%m-%d').values
    possible_duplicate_rows = int(duplicate_frame.duplicated(keep='first').sum()) if duplicate_fields else 0

    monthly_path = DATASETS / 'integrated_monthly.csv'
    monthly = pd.read_csv(monthly_path) if monthly_path.exists() else pd.DataFrame()
    if complete_case_coverage and not monthly.empty and 'case_observation_status' in monthly:
        no_case_rows = monthly['case_observation_status'].eq('no_records_zero_vs_missing_unverified')
        monthly.loc[no_case_rows, 'case_observation_status'] = 'zero_confirmed_by_cho'
        monthly.to_csv(monthly_path, index=False)
    periods = monthly[['year', 'month']].drop_duplicates().sort_values(['year', 'month']) if not monthly.empty else pd.DataFrame()
    grid_duplicates = int(monthly.duplicated(['barangay', 'year', 'month']).sum()) if not monthly.empty else None
    if not monthly.empty and 'case_observation_status' in monthly:
        no_record_months = int(pd.to_numeric(monthly['case_count'], errors='coerce').fillna(0).eq(0).sum())
        confirmed_zero_months = int(monthly['case_observation_status'].eq('zero_confirmed_by_cho').sum())
    else:
        no_record_months = int(pd.to_numeric(monthly.get('case_count'), errors='coerce').eq(0).sum()) if not monthly.empty else 0
        confirmed_zero_months = 0
    quality_path = DATASETS / 'dengue_dataset_quality.json'
    quality = json.loads(quality_path.read_text(encoding='utf-8')) if quality_path.exists() else {}
    weather_path = DATASETS / 'weather_source.json'
    weather = json.loads(weather_path.read_text(encoding='utf-8')) if weather_path.exists() else {}
    model_metrics_path = ROOT / 'monitoring' / 'ml' / 'model_metrics.json'
    model_metrics = json.loads(model_metrics_path.read_text(encoding='utf-8')) if model_metrics_path.exists() else {}
    synthetic_manifest_path = DATASETS / 'synthetic_supplement' / 'manifest.json'
    synthetic_manifest = json.loads(synthetic_manifest_path.read_text(encoding='utf-8')) if synthetic_manifest_path.exists() else None
    historical_manifest_path = DATASETS / 'cho_historical' / 'manifest.json'
    historical_manifest = json.loads(historical_manifest_path.read_text(encoding='utf-8')) if historical_manifest_path.exists() else None

    report = {
        'generated_from': [path.name for path in source_files],
        'consolidated_case_source_lineage': {
            'authoritative_file': (DATASETS / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv').name,
            'original_dataset_files': quality.get('source_files', []),
            'original_dataset_file_count': len(quality.get('source_files', [])),
            'quality_audit_source_rows': quality.get('source_row_count'),
            'authoritative_source_rows': int(len(raw)),
            'row_count_matches_quality_audit': quality.get('source_row_count') == len(raw),
            'all_source_rows_retained': quality.get('all_rows_retained'),
            'historical_2018_2019_sources': historical_manifest.get('historical_datasets', {}) if historical_manifest else {},
            'note': 'The active consolidated line list contains the 2018-2019 and 2020-2026 dengue datasets, confirmed by the project team as CHO-verified. Earlier explicitly synthetic 2018-2019 demo copies remain separately archived and excluded.',
        },
        'active_case_source_verification': 'The project team confirms all active 2018-2026 dengue case datasets were verified by CHO. Earlier files explicitly marked synthetic remain excluded.',
        'synthetic_supplement': synthetic_manifest,
        'generated_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'privacy': 'Aggregate inventory only; no patient-level data is included.',
        'patient_line_list': {
            'source_rows': int(len(raw)),
            'usable_rows_with_valid_admission_date_and_official_barangay': int(usable.sum()),
            'rows_missing_or_unmatched_barangay': int(normalized_barangay.isna().sum()),
            'rows_missing_or_invalid_admission_date': int(admitted.isna().sum()),
            'admission_date_range': [cases['admit_date'].min().date().isoformat(), cases['admit_date'].max().date().isoformat()],
            'official_barangays_present': int(cases['barangay'].nunique()),
            'potential_duplicate_matches': possible_duplicate_rows,
            'exact_duplicate_extra_rows': quality.get('exact_duplicate_extra_rows'),
            'rows_with_one_or_more_missing_requested_fields': quality.get('rows_with_one_or_more_missing_requested_fields'),
            'rows_without_official_iligan_barangay_match': quality.get('rows_without_official_iligan_barangay_match'),
            'admission_date_year_mismatch_rows': quality.get('admission_date_year_mismatch_rows'),
            'duplicate_policy': 'Retain and flag for CHO review; no stable case identifier is present, so demographic/location matches are not automatically removed.',
            'record_type': 'Individual case line list; rows with valid DAdmit and official barangay are aggregated for model input.',
            'case_definition': 'DAdmit and current-address barangay are present; confirmation criteria and case-definition version are not represented in the source workbook.',
            'reporting_delay': 'Cannot be calculated; source has admission date but no received/entered date.',
        },
        'monthly_model_dataset': {
            'file': monthly_path.name,
            'rows': int(len(monthly)),
            'barangays': int(monthly['barangay'].nunique()) if not monthly.empty else 0,
            'periods': int(len(periods)),
            'period_start': f"{int(periods.iloc[0]['year']):04d}-{int(periods.iloc[0]['month']):02d}" if not periods.empty else None,
            'period_end': f"{int(periods.iloc[-1]['year']):04d}-{int(periods.iloc[-1]['month']):02d}" if not periods.empty else None,
            'duplicate_barangay_period_rows': grid_duplicates,
            'cells_with_no_source_records': no_record_months,
            'cells_with_zero_under_user_completeness_confirmation': confirmed_zero_months,
            'cells_with_zero_vs_missing_unverified': int(monthly['case_observation_status'].eq('no_records_zero_vs_missing_unverified').sum()) if not monthly.empty and 'case_observation_status' in monthly else None,
            'zero_semantics': (
                'Based on the project-team confirmation of CHO data completeness for the CHO-sourced dataset, covered barangay-months with no line-list rows are treated as zero cases.'
                if complete_case_coverage else
                'A zero is the count of rows found in this line-list extract, not a confirmed zero case report. No report-completeness data is supplied, so empty cells are zero-versus-missing unverified.'
            ),
            'training_gate': (
                'Zero-versus-missing ambiguity cleared by the recorded completeness confirmation; retraining is permitted, with remaining case-definition, duplicate, and reporting-delay limitations disclosed.'
                if complete_case_coverage else
                'Do not retrain while any no_records_zero_vs_missing_unverified cells remain. Only set zero_confirmed_by_cho when CHO documentation confirms that barangay-month was reported with zero cases.'
            ),
        },
        'weekly_feasibility_candidate': {
            'file': weekly_path.name,
            'rows': int(len(weekly)),
            'week_start': first_week.date().isoformat(),
            'week_end': last_week.date().isoformat(),
            'barangays': int(weekly['barangay'].nunique()),
            'weeks': int(weekly['week_start'].nunique()),
            'barangay_weeks_with_cases_present': int((weekly['reported_case_count'] > 0).sum()),
            'barangay_weeks_with_no_records_unverified': int(weekly['reporting_status'].eq('no_records_zero_vs_missing_unverified').sum()),
            'barangay_weeks_with_zero_under_user_completeness_confirmation': int(weekly['reporting_status'].eq('zero_confirmed_by_cho').sum()),
            'zero_policy': (
                'No-case weeks within the CHO-sourced dataset are treated as zero based on the project-team confirmation of CHO data completeness; a separate CHO zero-report register was not supplied.'
                if complete_case_coverage else
                'No-record rows are explicitly marked zero-versus-missing-unverified and excluded from model training until surveillance completeness is established.'
            ),
        },
        'weather': {
            'source': weather.get('source', 'Not documented'),
            'source_status': weather.get('weather_source_status', 'Not documented'),
            'source_url': weather.get('source_url'),
            'coordinates': weather.get('coordinates'),
            'scope': weather.get('weather_scope', 'Not documented'),
            'variables_and_units': {
                'temperature_c': 'monthly mean temperature, degrees Celsius',
                'rainfall_mm': 'monthly precipitation sum, millimeters',
                'humidity_pct': 'monthly mean of daily mean relative humidity, percent',
            },
            'matching': weather.get('weather_scope', 'Weather point matching is not documented.'),
            'model_resolution_note': weather.get('weather_model_resolution_note'),
            'limitations': weather.get('limitations'),
            'locations_requested': weather.get('weather_locations_requested'),
            'distinct_grid_cells_returned': weather.get('weather_grid_cells_returned'),
            'missing_barangay_month_weather_rows': weather.get('weather_missing_model_rows'),
            'missing_periods': weather.get('weather_missing_periods', []),
            'weather_retrieval_note': weather.get('weather_retrieval_note'),
        },
        'model_weather_compatibility': {
            'compatible': model_metrics.get('training_weather_source_status') == 'archive_fetched_per_barangay',
            'training_weather_scope': model_metrics.get('training_weather_scope'),
            'current_weather_scope': weather.get('weather_scope'),
            'note': 'The saved model was retrained using the current Open-Meteo historical monthly weather at one representative point per barangay.' if model_metrics.get('training_weather_source_status') == 'archive_fetched_per_barangay' else 'The saved model weather inputs do not match the current per-barangay weather archive.',
        },
        'governance_gaps': [
            'Document CHO authorization, access roles, retention, and approved transfer/storage method for source records.',
            'Obtain the CHO case definition/version and identify which records are confirmed versus suspected.',
            'Capture report-received dates and maintain the completeness confirmation for future data updates.',
            'Obtain a stable de-identified case key so true duplicate records can be resolved safely.',
            'Validate barangay representative-point reanalysis estimates against PAGASA or another authorized station source before operational use.',
        ],
        'modeling_decision': 'Monthly forecasting uses the project-team confirmation that the active CHO-verified case datasets are complete for the covered period and the current per-barangay Open-Meteo historical weather. The score remains provisional: case-definition version, report-received dates, and stable identifiers for safely resolving duplicates are not in the workbook; CHO review is needed before operational use.',
    }
    report['case_reporting_completeness_confirmation'] = completeness or None
    if complete_case_coverage:
        report['modeling_decision'] = (
            'Monthly forecasting is enabled using the recorded completeness confirmation and the updated per-barangay weather inputs. '
            'Scores remain provisional because the source does not document the CHO case definition, report-received dates, or stable identifiers for resolving duplicate records; final test performance must beat simple baselines.'
        )
    (DATASETS / 'data_feasibility_inventory.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    _write_markdown(report)
    return report


def _write_markdown(report: dict) -> None:
    patient = report['patient_line_list']
    monthly = report['monthly_model_dataset']
    weekly = report['weekly_feasibility_candidate']
    weather = report['weather']
    compatibility = report['model_weather_compatibility']
    completeness = report.get('case_reporting_completeness_confirmation') or {}
    synthetic_manifest = report.get('synthetic_supplement')
    historical_sources = report['consolidated_case_source_lineage'].get('historical_2018_2019_sources', {})
    lines = [
        '# DengueWatch data feasibility inventory', '',
        f"Generated: {report['generated_at_utc']}", '',
        'This inventory contains aggregate quality counts only. It does not contain patient-level data.', '',
        '## Case data', '',
        f"- Active source: `{', '.join(report['generated_from'])}`.",
        f"- Source verification: {report['active_case_source_verification']}",
        f"- Consolidated source lineage: {report['consolidated_case_source_lineage']['authoritative_source_rows']} active rows versus {report['consolidated_case_source_lineage']['quality_audit_source_rows']} in the quality audit (match: {report['consolidated_case_source_lineage']['row_count_matches_quality_audit']}).",
        f"- Import policy: {report['consolidated_case_source_lineage']['note']}",
        *[
            f"- CHO-verified {year} records: {item.get('rows', item.get('rows_by_admission_date', 0))} rows by admission date; "
            f"{item.get('exact_duplicate_extra_rows', 0)} exact-repeat rows retained; "
            f"{item.get('rows_with_unmatched_barangay', 0)} rows have an unmatched official barangay; "
            f"source SHA-256 `{item.get('sha256', 'recorded in the consolidated source audit')}`."
            for year, item in sorted(historical_sources.items())
        ],
        f"- Original source files: {', '.join(report['consolidated_case_source_lineage']['original_dataset_files'])}.",
        f"- Record type: {patient['record_type']}",
        f"- Source rows: {patient['source_rows']}; usable rows with valid admission date and official barangay: {patient['usable_rows_with_valid_admission_date_and_official_barangay']}.",
        f"- Admission-date range: {patient['admission_date_range'][0]} to {patient['admission_date_range'][1]}; official barangays present: {patient['official_barangays_present']}.",
        f"- Missing/unmatched barangay: {patient['rows_missing_or_unmatched_barangay']}; invalid/missing admission date: {patient['rows_missing_or_invalid_admission_date']}.",
        f"- Potential duplicate matches: {patient['potential_duplicate_matches']}. No stable case ID is present, so matches are retained for CHO review rather than automatically deleted.",
        f"- Exact duplicate extra rows flagged by the source quality audit: {patient['exact_duplicate_extra_rows']}; these are retained. Potential demographic/location matches are a separate, broader review category.",
        f"- Case definition: {patient['case_definition']}",
        f"- Reporting delay: {patient['reporting_delay']}", '',
        f"- Completeness confirmation: {completeness.get('confirmation_method', 'No completeness confirmation is recorded.')}",
        '## Existing monthly model input', '',
        f"- `{monthly['file']}` has {monthly['rows']} rows for {monthly['barangays']} barangays and {monthly['periods']} months ({monthly['period_start']} through {monthly['period_end']}); duplicate barangay-month rows: {monthly['duplicate_barangay_period_rows']}.",
        f"- Empty line-list cells: {monthly['cells_with_no_source_records']}; zero cells under the project-team CHO completeness confirmation: {monthly['cells_with_zero_under_user_completeness_confirmation']}.",
        f"- Zero interpretation: {monthly['zero_semantics']}",
        f"- Retraining gate: {monthly['training_gate']}", '',
        '## Archived synthetic demonstration files', '',
        (
            f"- {synthetic_manifest['total_rows']} rows are archived separately across {len(synthetic_manifest['datasets'])} synthetic files; they are excluded from official case totals, maps, alerts, model training, and validation. The filenames and manifest identify them as synthetic; the eight-column CSVs do not have an extra per-row flag."
            if synthetic_manifest else
            '- No synthetic supplemental files are recorded.'
        ),
        '- These earlier synthetic files remain excluded from totals, maps, alerts, model training, and validation. The latest CHO-verified rows are described above and are part of the active consolidated source.',
        '## Weekly feasibility candidate', '',
        f"- `{weekly['file']}` creates {weekly['rows']} barangay-week rows for {weekly['weeks']} weeks ({weekly['week_start']} through {weekly['week_end']}).",
        f"- Barangay-weeks with cases present: {weekly['barangay_weeks_with_cases_present']}; no-record barangay-weeks: {weekly['barangay_weeks_with_no_records_unverified']}.",
        f"- Zero policy: {weekly['zero_policy']}",
        '- No-case weeks are treated as zero under the same project-team confirmation of CHO data completeness; the project does not yet have a separate CHO completeness register to independently verify that assertion.', '',
        '## Weather', '',
        f"- Source: {weather['source']}.",
        f"- Retrieval status: {weather['source_status']}.",
        f"- Variables: {', '.join(f'{name} ({unit})' for name, unit in weather['variables_and_units'].items())}.",
        f"- Matching: {weather['matching']}",
        f"- Spatial resolution: {weather['model_resolution_note']}",
        f"- Limitation: {weather['limitations']}", '',
        *([f"- Location points requested: {weather['locations_requested']}; distinct returned grid cells: {weather['distinct_grid_cells_returned']}. Missing barangay-month weather rows: {weather['missing_barangay_month_weather_rows']}."] if weather.get('locations_requested') is not None else []),
        *([f"- Missing weather periods: {', '.join(weather['missing_periods'])}. These feature values remain blank in the modeling dataset; the training pipeline imputes missing inputs." ] if weather['missing_periods'] else []),
        '## Existing model compatibility', '',
        f"- Compatible with updated weather history: {compatibility['compatible']}",
        f"- Training weather scope: {compatibility['training_weather_scope']}",
        f"- Current weather scope: {compatibility['current_weather_scope']}",
        f"- {compatibility['note']}", '',
        '## Feasibility actions', '',
        *[f'- {item}' for item in report['governance_gaps']], '',
        f"**Current modeling decision:** {report['modeling_decision']}", '',
        'Refresh this inventory after source data or weather inputs change with `python monitoring/ml/data_feasibility.py`.',
    ]
    (ROOT / 'docs').mkdir(exist_ok=True)
    (ROOT / 'docs' / 'data_feasibility_inventory.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    inventory = build_inventory()
    print(json.dumps({
        'patient_source_rows': inventory['patient_line_list']['source_rows'],
        'usable_patient_rows': inventory['patient_line_list']['usable_rows_with_valid_admission_date_and_official_barangay'],
        'potential_duplicate_matches': inventory['patient_line_list']['potential_duplicate_matches'],
        'weekly_candidate_rows': inventory['weekly_feasibility_candidate']['rows'],
        'monthly_period_range': [inventory['monthly_model_dataset']['period_start'], inventory['monthly_model_dataset']['period_end']],
    }, indent=2))
