"""Backend inference service used by CHO and LGU prediction pages."""

from calendar import month_name, monthrange
import csv
from collections import Counter, defaultdict
import math
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta

import joblib
import pandas as pd
from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from .features import FEATURES, engineer_features
from .definition import (
    FORECAST_GEOGRAPHIC_UNIT,
    FORECAST_HORIZON,
    FORECAST_TARGET,
    RISK_LEVEL_MODERATE_THRESHOLD,
    OBSERVED_HOTSPOT_THRESHOLD,
    PREDICTED_HOTSPOT_THRESHOLD,
    EXPLORATORY_REVIEW_THRESHOLD,
    PREDICTION_DEFINITION,
)
from monitoring.locations import ILIGAN_BARANGAYS, canonicalize_barangay, is_iligan_city


# This statement is exposed beside every forecast that was trained with the
# aggregate blood-type columns.  It deliberately prohibits individual use.
BLOOD_TYPE_FEATURE_NOTICE = (
    'Blood type is not used for an individual risk decision or diagnosis. '
    'If present in training, it is de-identified historical barangay-month '
    'aggregate data, lagged by one month. Individual blood-type values are not '
    'included in forecast outputs; access to clinical records remains limited '
    'to authorized health personnel.'
)
MINIMUM_AGGREGATE_RECORDS = 5


def _include_latest_confirmed_system_data(data: pd.DataFrame) -> tuple[pd.DataFrame, str, bool]:
    """Append CHO-confirmed cases only through the latest completed month.

    This keeps live inference aligned with training: each forecast uses the
    two latest complete case months, never partial current-month reports.
    Draft, Pending, and Rejected reports are excluded from the input.
    """
    from monitoring.models import DengueCase, Weather

    today = datetime.now(ZoneInfo('Asia/Manila')).date()
    completed_cutoff = today.replace(day=1) - timedelta(days=1)
    data = data[
        (data['year'] < completed_cutoff.year)
        | ((data['year'] == completed_cutoff.year) & (data['month'] <= completed_cutoff.month))
    ].copy()
    if data.empty:
        raise ValueError('The monthly dataset has no completed months of data.')
    source_year = int(data['year'].max())
    source_month = int(data.loc[data['year'] == source_year, 'month'].max())
    first_live = date(source_year + (source_month == 12), (source_month % 12) + 1, 1)

    system_cases = DengueCase.objects.filter(
        case_status='Confirmed',
        barangay__isnull=False,
        date_reported__gte=first_live,
        date_reported__lte=completed_cutoff,
    ).exclude(
        user_account__username='dataset_importer',
        remarks__istartswith='Imported from workbook',
    )
    case_rows = list(system_cases.annotate(
        year=ExtractYear('date_reported'),
        month=ExtractMonth('date_reported'),
    ).values('barangay__barangay_name', 'year', 'month').annotate(
        cases=Sum('case_count'),
    ))
    if not case_rows:
        return data, f"Historical dataset through {month_name[source_month]} {source_year}; no newer confirmed system cases", False

    live_year, live_month = max((int(row['year']), int(row['month'])) for row in case_rows)
    live_through = date(live_year, live_month, monthrange(live_year, live_month)[1])

    weather_rows = Weather.objects.filter(
        date__gte=first_live,
        date__lte=live_through,
        barangay__isnull=False,
    ).annotate(
        year=ExtractYear('date'),
        month=ExtractMonth('date'),
    ).values('barangay__barangay_name', 'year', 'month').annotate(
        temperature=Avg('temperature'), rainfall=Sum('rainfall'), humidity=Avg('humidity'),
    )
    weather_by_period_area = {
        (int(row['year']), int(row['month']), canonicalize_barangay(row['barangay__barangay_name'])): row
        for row in weather_rows
    }
    cases_by_period_area = {
        (int(row['year']), int(row['month']), canonicalize_barangay(row['barangay__barangay_name'])): int(row['cases'] or 0)
        for row in case_rows
    }
    confirmed_system_periods = {
        (int(row['year']), int(row['month']))
        for row in case_rows
        if int(row['cases'] or 0) > 0
    }
    latest_weather = {}
    for _, row in data.sort_values(['year', 'month']).iterrows():
        name = canonicalize_barangay(row['barangay'])
        if name:
            latest_weather[name] = row

    blood_columns = [column for column in data.columns if column.startswith('blood_') and column.endswith('_share')]
    new_rows = []
    year, month = first_live.year, first_live.month
    while (year, month) <= (live_year, live_month):
        for name in ILIGAN_BARANGAYS:
            weather = weather_by_period_area.get((year, month, name))
            fallback = latest_weather.get(name)
            row = {
                'barangay': name,
                'year': year,
                'month': month,
                'case_count': cases_by_period_area.get((year, month, name), 0),
                '_confirmed_system_period': (year, month) in confirmed_system_periods,
                '_confirmed_system_cases_for_area': (year, month, name) in cases_by_period_area,
                'rainfall_mm': float(weather['rainfall']) if weather and weather['rainfall'] is not None else float(fallback['rainfall_mm']) if fallback is not None else 0.0,
                'temperature_c': float(weather['temperature']) if weather and weather['temperature'] is not None else float(fallback['temperature_c']) if fallback is not None else 0.0,
                'humidity_pct': float(weather['humidity']) if weather and weather['humidity'] is not None else float(fallback['humidity_pct']) if fallback is not None else 0.0,
            }
            row.update({
                column: float(fallback[column]) if fallback is not None else 0.0
                for column in blood_columns
            })
            new_rows.append(row)
        month += 1
        if month == 13:
            month = 1
            year += 1

    combined = pd.concat([data, pd.DataFrame(new_rows)], ignore_index=True)
    source_label = (
        f"CHO-confirmed system records through {live_through.strftime('%B %Y')} "
        + "(completed months only)"
        + "; monthly system weather is used where available, with latest historical barangay weather as fallback"
    )
    return combined, source_label, False


def _most_common(counter: Counter, default: str = 'Not available') -> str:
    """Return the most common valid label from a Counter."""
    return counter.most_common(1)[0][0] if counter else default


def _age_group(value: object) -> str | None:
    """Convert a patient age into a readable public-health age group."""
    try:
        age = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > 120:
        return None
    if age <= 5:
        return '0–5 years'
    if age <= 12:
        return '6–12 years'
    if age <= 19:
        return '13–19 years'
    if age <= 39:
        return '20–39 years'
    if age <= 59:
        return '40–59 years'
    return '60+ years'


def load_demographic_profiles(dataset_dir: Path) -> tuple[dict, dict, list[dict]]:
    """Summarize observed patient records globally and per barangay.

    These values describe historical records. They are not model predictions
    and must never be presented as personal susceptibility or diagnosis.
    """
    counters = defaultdict(lambda: {
        'blood': Counter(), 'sex': Counter(), 'age': Counter(),
        'purok': Counter(), 'records': 0,
    })
    overall = {
        'blood': Counter(), 'sex': Counter(), 'age': Counter(),
        'purok': Counter(), 'barangay': Counter(), 'records': 0,
    }
    yearly_blood = defaultdict(Counter)

    def record_year(row: dict) -> str | None:
        """Read a source year without exposing an individual record date."""
        value = row.get('Year') or row.get('year') or row.get('DAdmit') or row.get('Date Reported')
        try:
            text = str(value).strip()
            if len(text) == 4 and text.isdigit():
                return text
            parsed = pd.to_datetime(value, errors='coerce')
            return str(int(parsed.year)) if not pd.isna(parsed) else None
        except (TypeError, ValueError, OverflowError):
            return None

    authoritative = dataset_dir / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv'
    source_files = [authoritative] if authoritative.is_file() else []
    for path in source_files:
        try:
            with path.open(encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    city = row.get('(Current Address) City / Municipality')
                    if city is not None and not is_iligan_city(city):
                        continue
                    barangay = canonicalize_barangay(
                        row.get('(Current Address) Barangay')
                        or row.get('Barangay')
                        or row.get('barangay')
                    )
                    if not barangay:
                        continue

                    sex = str(row.get('Sex') or row.get('sex') or '').strip().title()
                    blood = str(
                        row.get('Blood Type') or row.get('Bloodtype')
                        or row.get('BloodType') or row.get('blood_type') or ''
                    ).strip().upper().replace(' ', '')
                    age = _age_group(
                        row.get('AgeYears') or row.get('Age') or row.get('age')
                    )
                    purok = str(
                        row.get('(Current Address) Sitio / Purok / Street Name')
                        or row.get('Purok') or row.get('purok') or ''
                    ).strip()

                    area = counters[barangay]
                    area['records'] += 1
                    overall['records'] += 1
                    overall['barangay'][barangay] += 1
                    if sex and sex not in {'N/A', 'Unknown'}:
                        area['sex'][sex] += 1
                        overall['sex'][sex] += 1
                    if blood in {'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'}:
                        area['blood'][blood] += 1
                        overall['blood'][blood] += 1
                        year = record_year(row)
                        if year:
                            yearly_blood[year][blood] += 1
                            yearly_blood[year]['__records__'] += 1
                    if age:
                        area['age'][age] += 1
                        overall['age'][age] += 1
                    if purok and purok.lower() not in {'n/a', 'not specified', 'unknown'}:
                        area['purok'][purok] += 1
                        overall['purok'][purok] += 1
        except (OSError, csv.Error):
            continue

    def summarize(values: dict) -> dict:
        blood_records = sum(values['blood'].values())
        return {
            'historical_records': values['records'],
            # Suppress small aggregate groups; no individual information is
            # used or displayed in the forecast interface.
            'common_blood_type': (
                _most_common(values['blood'])
                if blood_records >= MINIMUM_AGGREGATE_RECORDS
                else 'Not displayed'
            ),
            'blood_type_records': blood_records,
            'common_sex': _most_common(values['sex']),
            'common_age_group': _most_common(values['age']),
            'common_purok': _most_common(values['purok']),
            'common_barangay': _most_common(values.get('barangay', Counter())),
        }

    yearly_summary = []
    for year, counts in yearly_blood.items():
        record_count = counts['__records__']
        if record_count < MINIMUM_AGGREGATE_RECORDS:
            continue
        values = Counter({key: value for key, value in counts.items() if key != '__records__'})
        common = _most_common(values)
        yearly_summary.append({
            'year': year,
            'record_count': record_count,
            'common_blood_type': common,
            'common_blood_type_share': round(values[common] / record_count * 100, 1),
        })
    yearly_summary.sort(key=lambda item: item['year'], reverse=True)

    return (
        {name: summarize(values) for name, values in counters.items()},
        summarize(overall),
        yearly_summary,
    )


def planning_recommendation(risk_level: str) -> str:
    recommendations = {
        'Critical': 'Immediate CHO coordination and intensified field validation.',
        'High': 'Prioritize validation, source reduction, and resource planning.',
        'Moderate': 'Increase monitoring and reinforce community prevention.',
        'Low': 'Continue routine surveillance and prevention reminders.',
    }
    return recommendations.get(risk_level, 'Continue routine monitoring.')


def classify_risk(predicted_cases: float) -> str:
    """Thresholds shared with the DengueWatch hotspot map."""
    if predicted_cases >= 101:
        return 'Critical'
    if predicted_cases >= 51:
        return 'High'
    if predicted_cases >= RISK_LEVEL_MODERATE_THRESHOLD:
        return 'Moderate'
    return 'Low'


def _historical_month_ahead_estimates(data: pd.DataFrame, year: int) -> dict:
    """Generate historical persistence benchmarks without using target data.

    Within confirmed coverage, each target month uses the preceding month's
    count. After confirmed coverage ends, carry forward the last complete
    month's count so later test periods still have an explicit baseline rather
    than treating unreported months as zero. This remains a benchmark, not an
    ML forecast or a claim that post-coverage months are fully observed.
    """
    dataset_path = Path(settings.BASE_DIR) / 'datasets' / 'integrated_monthly.csv'
    completeness_path = Path(settings.BASE_DIR) / 'datasets' / 'case_reporting_completeness.json'
    completeness_mtime = completeness_path.stat().st_mtime_ns if completeness_path.is_file() else 0
    row_fingerprint = int(pd.util.hash_pandas_object(
        data[['year', 'month', 'barangay', 'case_count']], index=False,
    ).sum())
    cache_key = (
        f"hotspot_persistence_walk_forward_v3_{year}_"
        f"{dataset_path.stat().st_mtime_ns}_{completeness_mtime}_{row_fingerprint}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        completeness = json.loads(completeness_path.read_text(encoding='utf-8'))
        coverage_end = pd.Timestamp(f"{completeness['coverage_end']}-01")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        # Without a declared complete month, do not invent carried-forward
        # estimates for periods outside the observed source rows.
        coverage_end = None

    engineered = engineer_features(data, include_target=True)
    engineered['period'] = pd.to_datetime({
        'year': engineered['year'], 'month': engineered['month'], 'day': 1,
    })
    estimates = {}
    first_target = engineered['period'].min()
    target_periods = pd.date_range(
        start=first_target,
        end=pd.Timestamp(year=year, month=12, day=1),
        freq='MS',
    )
    for target_period in target_periods:
        issue_period = target_period - pd.DateOffset(months=1)
        if coverage_end is not None and issue_period > coverage_end:
            issue_period = coverage_end
        elif coverage_end is None and issue_period > engineered['period'].max():
            continue
        issue_rows = engineered[engineered['period'] == issue_period]
        if issue_rows.empty:
            continue
        estimates[target_period.strftime('%Y-%m')] = {
            canonicalize_barangay(row['barangay']): round(max(0, float(row['case_count'])), 2)
            for _, row in issue_rows.iterrows()
        }

    cache.set(cache_key, estimates, 24 * 60 * 60)
    return estimates


def model_evaluation_summary(metrics: dict | None) -> dict:
    """Describe a holdout evaluation without overstating forecast reliability.

    Compare the Random Forest with the trailing three-month mean on the same
    chronological holdout rows. A lower MAE is better. The output remains
    planning support even if a future training run beats the baseline.
    """
    metrics = metrics or {}

    def number(name: str):
        try:
            return float(metrics[name])
        except (KeyError, TypeError, ValueError):
            return None

    model_mae = number('mae')
    baseline_scores = (metrics.get('baseline_comparison') or {}).get(
        'trailing_3_month_mean', {},
    ).get('overall', {})
    try:
        baseline_mae = float(baseline_scores['mae'])
        baseline_rmse = float(baseline_scores['rmse'])
    except (KeyError, TypeError, ValueError):
        baseline_mae = None
        baseline_rmse = None
    model_rmse = number('rmse')
    comparison_available = model_mae is not None and baseline_mae is not None
    beats_baseline = comparison_available and model_mae < baseline_mae

    if comparison_available and baseline_mae > 0:
        difference = round(model_mae - baseline_mae, 4)
        percent = round(abs(difference) / baseline_mae * 100, 1)
        if beats_baseline:
            comparison_message = (
                f'The Random Forest MAE is {percent}% lower than the trailing three-month average. '
                'Continue to use forecasts as planning support only.'
            )
        else:
            comparison_message = (
                f'The Random Forest MAE is {percent}% higher than the trailing three-month average. '
                'The three-month average currently performs better, so forecasts '
                'must remain planning support only.'
            )
    else:
        difference = None
        percent = None
        comparison_message = (
            'Three-month baseline comparison is unavailable. Forecasts must remain planning '
            'support only until the model is evaluated on a chronological test set.'
        )

    return {
        'model_mae': model_mae,
        'model_rmse': model_rmse,
        'baseline_mae': baseline_mae,
        'baseline_rmse': baseline_rmse,
        'baseline_name': 'Trailing three-month average',
        'comparison_available': comparison_available,
        'beats_baseline': beats_baseline,
        'mae_difference': difference,
        'mae_difference_percent': percent,
        'comparison_message': comparison_message,
        'beats_all_baselines_overall': bool(metrics.get('beats_all_baselines_overall', False)),
        'beats_all_baselines_each_test_block': bool(metrics.get('beats_all_baselines_each_test_block', False)),
        'planning_status': metrics.get('deployment_status', 'planning_support_only'),
        'planning_support_only': True,
    }


def _weather_description(code: object, rain_mm: float) -> str:
    """Return a simple weather description from Open-Meteo WMO codes."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = -1

    descriptions = {
        0: 'Clear sky',
        1: 'Mainly clear',
        2: 'Partly cloudy',
        3: 'Overcast',
        45: 'Fog',
        48: 'Depositing rime fog',
        51: 'Light drizzle',
        53: 'Moderate drizzle',
        55: 'Dense drizzle',
        56: 'Freezing drizzle',
        57: 'Dense freezing drizzle',
        61: 'Slight rain',
        63: 'Moderate rain',
        65: 'Heavy rain',
        66: 'Freezing rain',
        67: 'Heavy freezing rain',
        71: 'Slight snow',
        73: 'Moderate snow',
        75: 'Heavy snow',
        77: 'Snow grains',
        80: 'Slight rain showers',
        81: 'Moderate rain showers',
        82: 'Violent rain showers',
        85: 'Slight snow showers',
        86: 'Heavy snow showers',
        95: 'Thunderstorm',
        96: 'Thunderstorm with slight hail',
        99: 'Thunderstorm with heavy hail',
    }
    description = descriptions.get(code, 'Weather data available')
    if rain_mm > 0 and code in {0, 1, 2, 3}:
        description = 'Rainfall recorded/forecast'
    return description


def _weather_effect(rain_mm: float, recent_rain_mm: float) -> tuple[str, str]:
    """Explain rainfall as a surveillance signal, not an immediate case forecast."""
    if rain_mm > 0 or recent_rain_mm > 0:
        return (
            'Rainfall signal',
            'Rainfall can create conditions favorable to mosquito breeding. '
            'Dengue cases are not expected to increase immediately from one rainy day; '
            'monitor the following days and weeks, especially if rainfall continues.',
        )
    return (
        'No rainfall signal',
        'No measurable rainfall is shown for the selected day. Continue routine '
        'dengue surveillance and prevention activities.',
    )


def fetch_live_weather(selected_date: date | None = None) -> dict:
    """Fetch weather for a selected Iligan City date plus a short surrounding window.

    Open-Meteo supports recent archived forecast days as well as upcoming forecast
    days. The selected day is used for the weather display and interpretation.
    The Random Forest forecast itself remains a monthly dengue forecast and is not
    changed by a single day's rainfall.
    """
    selected_date = selected_date or datetime.now(ZoneInfo('Asia/Manila')).date()
    today = datetime.now(ZoneInfo('Asia/Manila')).date()
    cache_key = f'iligan_weather_window_{selected_date.isoformat()}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    days_from_today = (selected_date - today).days
    if -7 <= days_from_today <= 7:
        params = {
            'latitude': 8.2280,
            'longitude': 124.2452,
            'daily': (
                'weather_code,temperature_2m_mean,precipitation_sum,'
                'rain_sum,precipitation_hours,relative_humidity_2m_mean'
            ),
            'timezone': 'Asia/Manila',
            'past_days': 7,
            'forecast_days': 7,
        }
        source = 'Open-Meteo weather forecast/archive'
        source_url = 'https://open-meteo.com/en/docs'
    else:
        # For an older requested date, use Open-Meteo's historical weather API.
        params = {
            'latitude': 8.2280,
            'longitude': 124.2452,
            'start_date': selected_date.isoformat(),
            'end_date': selected_date.isoformat(),
            'daily': (
                'weather_code,temperature_2m_mean,precipitation_sum,'
                'rain_sum,precipitation_hours,relative_humidity_2m_mean'
            ),
            'timezone': 'Asia/Manila',
        }
        source = 'Open-Meteo Historical Weather API'
        source_url = 'https://open-meteo.com/en/docs/historical-weather-api'

    base_url = (
        'https://api.open-meteo.com/v1/forecast'
        if -7 <= days_from_today <= 7
        else 'https://archive-api.open-meteo.com/v1/archive'
    )
    url = base_url + '?' + urlencode(params)

    with urlopen(url, timeout=20) as response:
        payload = json.load(response)

    daily = payload.get('daily', {})
    dates = daily.get('time', [])
    if not dates:
        raise ValueError('Weather API returned no daily weather records.')

    def value_at(key: str, target: str, default: float = 0.0):
        values = daily.get(key, [])
        try:
            index = dates.index(target)
            value = values[index]
            return default if value is None else value
        except (ValueError, IndexError, TypeError):
            return default

    selected_iso = selected_date.isoformat()
    rainfall = float(value_at('rain_sum', selected_iso, 0.0))
    precipitation = float(value_at('precipitation_sum', selected_iso, rainfall))
    temperature = float(value_at('temperature_2m_mean', selected_iso, 0.0))
    humidity = float(value_at('relative_humidity_2m_mean', selected_iso, 0.0))
    hours = float(value_at('precipitation_hours', selected_iso, 0.0))
    code = value_at('weather_code', selected_iso, -1)

    recent_rain = 0.0
    for d, value in zip(dates, daily.get('rain_sum', [])):
        if value is None:
            continue
        try:
            if selected_date - timedelta(days=6) <= date.fromisoformat(d) <= selected_date:
                recent_rain += float(value)
        except ValueError:
            continue

    label, effect = _weather_effect(rainfall, recent_rain)
    selected_is_today = selected_date == today

    result = {
        'selected_date': selected_iso,
        'selected_date_label': selected_date.strftime('%B %d, %Y'),
        'relative_label': 'Today' if selected_is_today else (
            'Yesterday' if selected_date == today - timedelta(days=1)
            else selected_date.strftime('%b %d')
        ),
        'weather_description': _weather_description(code, rainfall),
        'weather_code': code,
        'rainfall_mm': round(rainfall, 1),
        'precipitation_mm': round(precipitation, 1),
        'precipitation_hours': round(hours, 1),
        'temperature_c': round(temperature, 1),
        'humidity_pct': round(humidity, 1),
        'recent_7_day_rainfall_mm': round(recent_rain, 1),
        'weather_signal': label,
        'weather_effect': effect,
        'source': source,
        'source_url': source_url,
        'retrieved_at': datetime.now(ZoneInfo('Asia/Manila')).strftime('%B %d, %Y %I:%M %p'),
        'live': True,
    }
    cache.set(cache_key, result, 1800)
    return result


def fetch_barangay_archive_weather() -> tuple[dict[str, dict], str]:
    """Fetch the latest complete month's Open-Meteo archive per barangay point.

    Coordinates come from configured Barangay records where available, with
    boundary-derived representative points as a fallback. Open-Meteo returns
    modeled grid estimates, not station observations for each barangay.
    """
    today = datetime.now(ZoneInfo('Asia/Manila')).date()
    period_end = today.replace(day=1) - timedelta(days=1)
    period_start = period_end.replace(day=1)

    from monitoring.models import Barangay

    coordinates = {}
    for item in Barangay.objects.filter(
        barangay_name__in=ILIGAN_BARANGAYS,
    ).values('barangay_name', 'latitude', 'longitude'):
        if item['latitude'] is None or item['longitude'] is None:
            continue
        coordinates[item['barangay_name']] = (
            float(item['latitude']), float(item['longitude'])
        )

    missing_names = [name for name in ILIGAN_BARANGAYS if name not in coordinates]
    if missing_names:
        boundary_path = Path(settings.BASE_DIR) / 'static' / 'data' / 'iligan_barangays.geojson'
        try:
            features = json.loads(boundary_path.read_text(encoding='utf-8')).get('features', [])
        except (OSError, json.JSONDecodeError):
            features = []

        def coordinate_pairs(value):
            if (
                isinstance(value, list) and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))
            ):
                yield (float(value[1]), float(value[0]))
            elif isinstance(value, list):
                for child in value:
                    yield from coordinate_pairs(child)

        for feature in features:
            name = canonicalize_barangay(
                feature.get('properties', {}).get('brgy_name')
            )
            if name not in missing_names:
                continue
            points = list(coordinate_pairs(
                feature.get('geometry', {}).get('coordinates', [])
            ))
            if points:
                coordinates[name] = (
                    sum(point[0] for point in points) / len(points),
                    sum(point[1] for point in points) / len(points),
                )

    names = [name for name in ILIGAN_BARANGAYS if name in coordinates]
    if not names:
        return {}, ''

    period = period_end.strftime('%Y-%m')
    cache_key = f"openmeteo_barangay_archive_{period}_{len(names)}"
    cached = cache.get(cache_key)
    if cached:
        return cached, period

    params = {
        'latitude': ','.join(f'{coordinates[name][0]:.6f}' for name in names),
        'longitude': ','.join(f'{coordinates[name][1]:.6f}' for name in names),
        'start_date': period_start.isoformat(),
        'end_date': period_end.isoformat(),
        'daily': 'temperature_2m_mean,precipitation_sum,relative_humidity_2m_mean',
        'timezone': 'Asia/Manila',
    }
    url = 'https://archive-api.open-meteo.com/v1/archive?' + urlencode(params)
    try:
        with urlopen(url, timeout=25) as response:
            payload = json.load(response)
        locations = payload if isinstance(payload, list) else [payload]
        result = {}
        for name, location in zip(names, locations):
            daily = location.get('daily') or {}
            if len(daily.get('time', [])) != (period_end - period_start).days + 1:
                continue
            values = {}
            for api_name, result_name in (
                ('temperature_2m_mean', 'temperature_c'),
                ('precipitation_sum', 'rainfall_mm'),
                ('relative_humidity_2m_mean', 'humidity_pct'),
            ):
                available = [
                    float(value) for value in daily.get(api_name, [])
                    if value is not None and math.isfinite(float(value))
                ]
                if len(available) != len(daily['time']):
                    break
                if result_name == 'rainfall_mm':
                    values[result_name] = round(sum(available), 1)
                else:
                    values[result_name] = round(sum(available) / len(available), 1)
            if len(values) == 3:
                result[name] = values
        if result:
            cache.set(cache_key, result, 12 * 60 * 60)
            return result, period
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        pass
    return {}, period


def weather_date_options() -> list[dict]:
    """Return a compact date selector covering recent and upcoming weather."""
    today = datetime.now(ZoneInfo('Asia/Manila')).date()
    options = []
    for offset in range(-7, 8):
        selected = today + timedelta(days=offset)
        if offset == 0:
            label = f'Today — {selected.strftime("%b %d, %Y")}'
        elif offset == -1:
            label = f'Yesterday — {selected.strftime("%b %d, %Y")}'
        elif offset == 1:
            label = f'Tomorrow — {selected.strftime("%b %d, %Y")}'
        else:
            label = selected.strftime('%b %d, %Y')
        options.append({'value': selected.isoformat(), 'label': label})
    return options


def prediction_context(request=None) -> dict:
    """Build the shared prediction page context for CHO and LGU.

    The model is loaded only when the prediction page is requested.  Older
    saved scikit-learn pipelines can fail during unpickling after a version
    change (for example, the private ``_RemainderColsList`` error).  That
    condition is handled here so the Django page shows a useful message
    instead of returning HTTP 500.
    """

    model_path = Path(settings.ML_MODEL_PATH)
    dataset_path = Path(settings.BASE_DIR) / 'datasets' / 'integrated_monthly.csv'

    context = {
        'model_ready': False,
        'forecasts': [],
        'potential_hotspots': [],
        'model_metrics': {},
        'high_count': 0,
        'critical_count': 0,
        'moderate_count': 0,
        'low_count': 0,
        'priority_barangays': [],
        'planning_summary': {},
        'forecast_period': 'Unavailable',
        'case_data_period': 'Unavailable',
        'prediction_error': '',
        'weather': {},
        'demographic_summary': {},
        'blood_type_by_year': [],
        'blood_type_feature_notice': BLOOD_TYPE_FEATURE_NOTICE,
        'prediction_definition': PREDICTION_DEFINITION,
        'forecast_horizon': FORECAST_HORIZON,
        'forecast_geographic_unit': FORECAST_GEOGRAPHIC_UNIT,
        'forecast_target': FORECAST_TARGET,
        'observed_hotspot_threshold': OBSERVED_HOTSPOT_THRESHOLD,
        'predicted_hotspot_threshold': PREDICTED_HOTSPOT_THRESHOLD,
        'forecast_map_geojson': None,
        'prediction_data_source': 'Historical monthly dataset',
        'prediction_input_provisional': False,
    }

    if not model_path.exists():
        context['prediction_error'] = (
            'The Random Forest model file is missing. '
            'Retrain the model using the current project environment.'
        )
        return context

    if not dataset_path.exists():
        context['prediction_error'] = (
            'The integrated monthly dataset is missing. '
            'Build datasets/integrated_monthly.csv before generating predictions.'
        )
        return context

    # ---------------------------------------------------------
    # LOAD MODEL SAFELY
    # ---------------------------------------------------------
    try:
        artifact = joblib.load(model_path)
    except (
        AttributeError,
        ImportError,
        ModuleNotFoundError,
        ValueError,
        OSError,
    ) as exc:
        error_text = str(exc)

        if '_RemainderColsList' in error_text:
            context['prediction_error'] = (
                'The saved Random Forest model was created with a different '
                'scikit-learn version and cannot be loaded safely. '
                'The current project uses scikit-learn 1.9.0. '
                'Retrain the model with the current environment, then reload this page.'
            )
        else:
            context['prediction_error'] = (
                'The saved Random Forest model could not be loaded safely. '
                f'Details: {error_text}'
            )
        return context

    # Keep the operational hotspot cutoff attached to the exact estimator that
    # was selected using validation. Fall back for older model artifacts.
    try:
        deployed_hotspot_threshold = float(
            artifact.get('predicted_hotspot_threshold', PREDICTED_HOTSPOT_THRESHOLD)
        )
    except (AttributeError, TypeError, ValueError):
        deployed_hotspot_threshold = PREDICTED_HOTSPOT_THRESHOLD
    context['predicted_hotspot_threshold'] = deployed_hotspot_threshold

    # Keep the human-readable evaluation report current without rewriting or
    # loading an incompatible legacy estimator artifact. The JSON is generated
    # by the training/evaluation workflow and can contain baseline diagnostics
    # added after the last valid model fit.
    metrics_for_display = artifact.get('metrics', {})
    metrics_report_path = Path(__file__).with_name('model_metrics.json')
    try:
        current_metrics_report = json.loads(metrics_report_path.read_text(encoding='utf-8'))
        metrics_for_display = {**metrics_for_display, **current_metrics_report}
    except (OSError, json.JSONDecodeError):
        pass
    validation_hotspot = metrics_for_display.get('validation_hotspot_classification')
    if isinstance(validation_hotspot, dict):
        for metric in ('precision', 'recall', 'f1', 'accuracy'):
            validation_hotspot[f'{metric}_pct'] = round(
                float(validation_hotspot.get(metric, 0)) * 100, 2
            )
        confusion = validation_hotspot.get('confusion_matrix', {})
        true_positive = int(confusion.get('true_positive', 0))
        true_negative = int(confusion.get('true_negative', 0))
        false_positive = int(confusion.get('false_positive', 0))
        false_negative = int(confusion.get('false_negative', 0))
        classified_rows = int(validation_hotspot.get('rows', 0))
        if classified_rows:
            validation_hotspot['error_rate_pct'] = round(
                (false_positive + false_negative) / classified_rows * 100, 2,
            )
        validation_hotspot.update({
            'true_positive_count': true_positive,
            'true_negative_count': true_negative,
            'false_positive_count': false_positive,
            'false_negative_count': false_negative,
        })
    test_hotspot = metrics_for_display.get('hotspot_classification_evaluation', {}).get('model_overall', {})
    if isinstance(test_hotspot, dict):
        for metric in ('precision', 'recall', 'f1'):
            test_hotspot[f'{metric}_pct'] = round(
                float(test_hotspot.get(metric, 0)) * 100, 2
            )
        confusion = test_hotspot.get('confusion_matrix', {})
        true_positive = int(confusion.get('true_positive', 0))
        true_negative = int(confusion.get('true_negative', 0))
        false_positive = int(confusion.get('false_positive', 0))
        false_negative = int(confusion.get('false_negative', 0))
        classified_rows = int(test_hotspot.get('rows', 0))
        if classified_rows:
            test_hotspot['accuracy_pct'] = round(
                (true_positive + true_negative) / classified_rows * 100, 2,
            )
            test_hotspot['error_rate_pct'] = round(
                (false_positive + false_negative) / classified_rows * 100, 2,
            )
        test_hotspot.update({
            'true_positive_count': true_positive,
            'true_negative_count': true_negative,
            'false_positive_count': false_positive,
            'false_negative_count': false_negative,
        })
    validation_analysis_path = Path(__file__).with_name(
        'validation_threshold_analysis.json'
    )
    try:
        metrics_for_display['exploratory_validation_threshold_analysis'] = json.loads(
            validation_analysis_path.read_text(encoding='utf-8')
        )
    except (OSError, json.JSONDecodeError):
        pass
    regression_tuning_path = Path(__file__).with_name(
        'regression_tuning_validation.json'
    )
    try:
        metrics_for_display['exploratory_regression_tuning'] = json.loads(
            regression_tuning_path.read_text(encoding='utf-8')
        )
    except (OSError, json.JSONDecodeError):
        pass
    rolling_validation_path = Path(__file__).with_name(
        'rolling_validation_exploration.json'
    )
    try:
        rolling_validation = json.loads(
            rolling_validation_path.read_text(encoding='utf-8')
        )
        for candidate in rolling_validation.get('candidate_results', []):
            for metric in ('precision', 'recall', 'f1'):
                candidate['hotspot'][f'{metric}_pct'] = round(
                    candidate['hotspot'][metric] * 100, 2
                )
        for baseline in rolling_validation.get('baseline_results', {}).values():
            for metric in ('precision', 'recall', 'f1'):
                baseline['hotspot'][f'{metric}_pct'] = round(
                    baseline['hotspot'][metric] * 100, 2
                )
        metrics_for_display['exploratory_rolling_validation'] = rolling_validation
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass

    classifier_validation_path = Path(__file__).with_name(
        'hotspot_classifier_rolling_validation.json'
    )
    try:
        classifier_validation = json.loads(
            classifier_validation_path.read_text(encoding='utf-8')
        )
        for candidate in classifier_validation.get('candidate_results', []):
            for key in ('best_f1_threshold_result',):
                result = candidate.get(key)
                if result:
                    for metric in ('precision', 'recall', 'f1'):
                        result[f'{metric}_pct'] = round(result[metric] * 100, 2)
            high_precision = [
                result for result in candidate.get('threshold_results', [])
                if result.get('precision', 0) >= 0.85
            ]
            candidate['highest_precision_result'] = max(
                high_precision, key=lambda result: result['precision'],
                default=None,
            )
            if candidate['highest_precision_result']:
                result = candidate['highest_precision_result']
                for metric in ('precision', 'recall', 'f1'):
                    result[f'{metric}_pct'] = round(result[metric] * 100, 2)
        for baseline in classifier_validation.get('baseline_results', {}).values():
            for metric in ('precision', 'recall', 'f1'):
                baseline[f'{metric}_pct'] = round(baseline[metric] * 100, 2)
        metrics_for_display[
            'exploratory_hotspot_classifier_rolling_validation'
        ] = classifier_validation
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass

    try:
        data = pd.read_csv(dataset_path)
        data, live_data_source, input_provisional = _include_latest_confirmed_system_data(data)
        profiles, demographic_summary, blood_type_by_year = load_demographic_profiles(
            dataset_path.parent,
        )

        required_columns = {
            'year', 'month', 'case_count', 'barangay',
            'rainfall_mm', 'temperature_c', 'humidity_pct',
        }
        missing_columns = sorted(required_columns - set(data.columns))
        if missing_columns:
            raise ValueError(
                f"Integrated dataset is missing: {', '.join(missing_columns)}"
            )

        latest_year = int(data['year'].max())
        latest_month = int(
            data.loc[data['year'] == latest_year, 'month'].max()
        )

        engineered = engineer_features(
            data,
            include_target=False,
        )

        latest = engineered[
            (engineered['year'] == latest_year)
            & (engineered['month'] == latest_month)
        ].copy()

        if latest.empty:
            raise ValueError(
                'No rows are available for the latest dataset month.'
            )

        # Keep model input weather unchanged (the saved pipeline handles its
        # training-fitted imputation), while showing archived monthly weather
        # estimates for representative barangay locations in the table.
        weather_columns = ['rainfall_mm', 'temperature_c', 'humidity_pct']
        weather_history = data.copy()
        for column in weather_columns:
            weather_history[column] = pd.to_numeric(
                weather_history[column], errors='coerce'
            )
        weather_history = weather_history.dropna(subset=weather_columns).sort_values(
            ['year', 'month']
        )
        latest_weather_by_barangay = weather_history.drop_duplicates(
            'barangay', keep='last'
        ).set_index('barangay').to_dict('index')
        open_meteo_weather_by_barangay, open_meteo_weather_period = (
            fetch_barangay_archive_weather()
        )

        # -----------------------------------------------------
        # WEATHER INPUT / WEATHER DATE CONTEXT
        # -----------------------------------------------------
        selected_weather_date = datetime.now(ZoneInfo('Asia/Manila')).date()
        if request is not None:
            raw_weather_date = str(request.GET.get('weather_date', '')).strip()
            if raw_weather_date:
                try:
                    selected_weather_date = date.fromisoformat(raw_weather_date)
                except ValueError:
                    selected_weather_date = datetime.now(ZoneInfo('Asia/Manila')).date()

        try:
            weather = fetch_live_weather(selected_weather_date)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            ZeroDivisionError,
        ) as exc:
            weather = {
                'selected_date': selected_weather_date.isoformat(),
                'selected_date_label': selected_weather_date.strftime('%B %d, %Y'),
                'relative_label': selected_weather_date.strftime('%b %d'),
                'weather_description': 'Weather data unavailable',
                'weather_code': -1,
                'temperature_c': round(float(latest['temperature_c'].iloc[0]), 1),
                'rainfall_mm': round(float(latest['rainfall_mm'].iloc[0]), 1),
                'precipitation_mm': round(float(latest['rainfall_mm'].iloc[0]), 1),
                'precipitation_hours': 0,
                'humidity_pct': round(float(latest['humidity_pct'].iloc[0]), 1),
                'recent_7_day_rainfall_mm': round(float(latest['rainfall_mm'].iloc[0]), 1),
                'weather_signal': 'Weather unavailable',
                'weather_effect': 'Use the stored weather data and continue routine surveillance.',
                'source': 'Latest stored historical weather',
                'source_url': '',
                'retrieved_at': '',
                'live': False,
                'error': str(exc),
            }

        # The model predicts the next monthly case count. A single rainy day
        # must not be substituted for the model's monthly rainfall feature.
        # The selected weather day is therefore displayed as an explanatory
        # surveillance signal rather than falsely changing the RF prediction.
        input_year = latest_year
        input_month = latest_month

        # -----------------------------------------------------
        # MODEL FEATURES
        # -----------------------------------------------------
        features = artifact.get(
            'metrics',
        ).get(
            'features',
            FEATURES,
        )

        missing_features = [
            field
            for field in features
            if field not in latest.columns
        ]

        if missing_features:
            raise ValueError(
                'Dataset is missing model features: '
                + ', '.join(missing_features)
            )

        pipeline = artifact.get('pipeline')
        if pipeline is None:
            raise ValueError(
                'The saved model artifact does not contain a prediction pipeline.'
            )

        values = pipeline.predict(
            latest[features]
        )

        forecasts = []

        for (_, row), raw_value in zip(
            latest.iterrows(),
            values,
        ):
            predicted = max(
                0,
                round(float(raw_value), 2),
            )

            current = int(
                row['case_count']
            )

            change = round(
                predicted - current,
                2,
            )

            if change > 0.49:
                trend = 'Increasing'
                trend_class = 'trend-up'
            elif change < -0.49:
                trend = 'Decreasing'
                trend_class = 'trend-down'
            else:
                trend = 'Stable'
                trend_class = 'trend-stable'

            if change > 0:
                case_change_display = f'+{change:.2f}'
            else:
                case_change_display = f'{change:.2f}'

            profile = profiles.get(
                str(row['barangay']),
                {},
            )
            barangay_name = str(row['barangay'])
            display_weather = open_meteo_weather_by_barangay.get(barangay_name)
            if display_weather:
                display_weather_period = open_meteo_weather_period
                display_weather_source = 'Open-Meteo Historical Weather API'
            else:
                display_weather = latest_weather_by_barangay.get(barangay_name)
                display_weather_period = (
                    f"{int(display_weather['year']):04d}-{int(display_weather['month']):02d}"
                    if display_weather else None
                )
                display_weather_source = (
                    'Integrated monthly weather dataset (fallback)'
                    if display_weather else 'Unavailable'
                )

            risk_level = classify_risk(
                predicted
            )
            forecasts.append({
                'barangay': row['barangay'],
                'predicted_cases': predicted,
                'risk_level': risk_level,
                'current_cases': current,
                'case_change': change,
                'case_change_display': case_change_display,
                'trend': trend,
                'trend_class': trend_class,
                'rainfall_mm': round(float(display_weather['rainfall_mm']), 1) if display_weather else None,
                'temperature_c': round(float(display_weather['temperature_c']), 1) if display_weather else None,
                'humidity_pct': round(float(display_weather['humidity_pct']), 1) if display_weather else None,
                'weather_period': display_weather_period,
                'weather_source': display_weather_source,
                # Aggregate historical context only; it is never used to
                # describe an individual resident's risk or diagnosis.
                'historical_common_blood_type': profile.get(
                    'common_blood_type',
                    'Not displayed',
                ),
                'common_sex': profile.get(
                    'common_sex',
                    'Not available',
                ),
                'common_age_group': profile.get(
                    'common_age_group',
                    'Not available',
                ),
                'common_purok': profile.get(
                    'common_purok',
                    'Not available',
                ),
                'historical_records': profile.get(
                    'historical_records',
                    0,
                ),
                'recommendation': planning_recommendation(
                    risk_level
                ),
            })

        forecasts.sort(
            key=lambda item: item['predicted_cases'],
            reverse=True,
        )

        # Join forecasts to the same official barangay polygons used by the
        # historical hotspot map, so the AI map represents next month's
        # estimates rather than past case totals.
        boundary_path = Path(settings.BASE_DIR) / 'static' / 'data' / 'iligan_barangays.geojson'
        forecast_by_name = {
            canonicalize_barangay(row['barangay']): row for row in forecasts
        }
        try:
            with boundary_path.open(encoding='utf-8') as boundary_file:
                forecast_map_geojson = json.load(boundary_file)
            for feature in forecast_map_geojson.get('features', []):
                props = feature.setdefault('properties', {})
                forecast = forecast_by_name.get(
                    canonicalize_barangay(props.get('brgy_name', ''))
                )
                if forecast:
                    props.update({
                        'forecast_cases': forecast['predicted_cases'],
                        'current_cases': forecast['current_cases'],
                        'forecast_risk': forecast['risk_level'],
                        'forecast_trend': forecast['trend'],
                    })
        except (OSError, ValueError, TypeError):
            forecast_map_geojson = None

        priority_barangays = forecasts[:5]
        potential_hotspots = [
            item for item in forecasts
            if item['predicted_cases'] >= deployed_hotspot_threshold
        ]
        precision_candidate_hotspots = [
            item for item in forecasts
            if item['predicted_cases'] >= EXPLORATORY_REVIEW_THRESHOLD
        ]
        planning_summary = {
            'total_predicted_cases': round(
                sum(item['predicted_cases'] for item in forecasts),
                2,
            ),
            'increasing_barangays': sum(
                item['trend'] == 'Increasing' for item in forecasts
            ),
            'priority_barangays': len([
                item for item in forecasts
                if item['risk_level'] in {'High', 'Critical'}
            ]),
            'potential_hotspot_count': len(potential_hotspots),
            'historical_case_period': (
                f"{month_name[latest_month]} {latest_year}"
            ),
        }

        next_month = (
            1
            if input_month == 12
            else input_month + 1
        )

        next_year = (
            input_year + 1
            if input_month == 12
            else input_year
        )

        after_forecast_month = 1 if next_month == 12 else next_month + 1
        after_forecast_year = next_year + 1 if next_month == 12 else next_year
        from monitoring.models import DengueCase, MonthlyForecastSnapshot

        forecast_target_month = date(next_year, next_month, 1)
        for item in forecasts:
            MonthlyForecastSnapshot.objects.get_or_create(
                target_month=forecast_target_month,
                barangay=item['barangay'],
                defaults={'predicted_cases': item['predicted_cases']},
            )

        today = datetime.now(ZoneInfo('Asia/Manila')).date()
        current_month_start = today.replace(day=1)

        # Show current-month confirmed submissions in the actuals table as
        # month-to-date observations. They are informational only: do not add
        # this partial month to model inputs or treat missing barangays as zero.
        current_month_rows = DengueCase.objects.filter(
            case_status='Confirmed',
            barangay__isnull=False,
            date_reported__year=current_month_start.year,
            date_reported__month=current_month_start.month,
            date_reported__lte=today,
        ).exclude(
            user_account__username='dataset_importer',
            remarks__istartswith='Imported from workbook',
        ).values('barangay__barangay_name').annotate(cases=Sum('case_count'))
        current_month_actuals = {
            canonicalize_barangay(row['barangay__barangay_name']): int(row['cases'] or 0)
            for row in current_month_rows
            if canonicalize_barangay(row['barangay__barangay_name'])
        }
        if current_month_actuals:
            live_data_source += (
                f"; {sum(current_month_actuals.values())} confirmed system case(s) "
                f"reported in {month_name[current_month_start.month]} month to date "
                "for display only (not used as a complete model-input month)"
            )

        # Once a forecast month has ended, attach its confirmed monthly counts
        # to the original forecast snapshot. In-progress months remain pending.
        # A monthly grid can contain placeholder zeroes beyond the months for
        # which the source is confirmed complete. Only the declared coverage
        # window may be used as an observed actual in comparisons or snapshots.
        coverage_start = None
        coverage_end = None
        completeness_path = dataset_path.parent / 'case_reporting_completeness.json'
        try:
            completeness = json.loads(completeness_path.read_text(encoding='utf-8'))
            coverage_start = date.fromisoformat(f"{completeness['coverage_start']}-01")
            coverage_end = date.fromisoformat(f"{completeness['coverage_end']}-01")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Fail closed: without a valid coverage declaration, avoid treating
            # any dataset row as a complete monthly actual.
            coverage_end = None
        observed_by_month_barangay = {}
        for _, observed_row in data.iterrows():
            observed_month = date(int(observed_row['year']), int(observed_row['month']), 1)
            source_marker = observed_row.get('_confirmed_system_period', False)
            area_marker = observed_row.get('_confirmed_system_cases_for_area', False)
            source_has_confirmed_cases = bool(source_marker) if pd.notna(source_marker) else False
            area_has_confirmed_cases = bool(area_marker) if pd.notna(area_marker) else False
            if coverage_end is None or observed_month > coverage_end:
                # Outside complete historical coverage, count only barangays
                # with newly confirmed system reports. The live loader pads
                # other barangays with zeroes for forecasting; those zeroes
                # are not evidence of zero actual cases.
                if not source_has_confirmed_cases or not area_has_confirmed_cases:
                    continue
            observed_by_month_barangay[
                (int(observed_row['year']), int(observed_row['month']), canonicalize_barangay(observed_row['barangay']))
            ] = int(observed_row['case_count'] or 0)
        completed_snapshots = MonthlyForecastSnapshot.objects.filter(
            target_month__lt=current_month_start,
            actual_cases__isnull=True,
        )
        if coverage_end is not None:
            completed_snapshots = completed_snapshots.filter(target_month__lte=coverage_end)
        else:
            completed_snapshots = completed_snapshots.none()
        for snapshot in completed_snapshots:
            actual = observed_by_month_barangay.get((
                snapshot.target_month.year,
                snapshot.target_month.month,
                canonicalize_barangay(snapshot.barangay),
            ))
            if actual is not None:
                snapshot.actual_cases = actual
                snapshot.save(update_fields=['actual_cases'])

        # Browse historical data through the current month and the latest
        # saved next-month forecast, without extending beyond one month ahead.
        first_data_period = data[['year', 'month']].astype(int).sort_values(
            ['year', 'month'],
        ).iloc[0]
        map_start = coverage_start or date(
            int(first_data_period['year']), int(first_data_period['month']), 1,
        )
        next_calendar_month = date(
            current_month_start.year + (current_month_start.month == 12),
            current_month_start.month % 12 + 1,
            1,
        )
        latest_saved_target = MonthlyForecastSnapshot.objects.filter(
            target_month__lte=next_calendar_month,
        ).order_by('-target_month').values_list('target_month', flat=True).first()
        display_end = max(
            forecast_target_month,
            current_month_start,
            latest_saved_target or current_month_start,
        )
        hotspot_map_dates = [
            date(year, month, 1)
            for year in range(map_start.year, display_end.year + 1)
            for month in range(1, 13)
            if map_start <= date(year, month, 1) <= display_end
        ]
        # Keep the monthly citywide actual-vs-estimate table on the same range
        # as the map, including current month-to-date and the separate forecast.
        comparison_dates = hotspot_map_dates
        comparison_snapshots = MonthlyForecastSnapshot.objects.filter(
            target_month__in=hotspot_map_dates,
        )
        snapshots_by_month_barangay = {}
        predictions_by_month = defaultdict(list)
        for snapshot in comparison_snapshots:
            value = float(snapshot.predicted_cases)
            snapshots_by_month_barangay[(
                snapshot.target_month,
                canonicalize_barangay(snapshot.barangay),
            )] = value
            predictions_by_month[snapshot.target_month].append(value)

        # Fill missing monthly snapshots with a persistence benchmark. Saved
        # forecasts always take precedence over these historical estimates.
        historical_estimates = _historical_month_ahead_estimates(data, input_year)
        prediction_source_by_month = {
            period: 'Saved forecast'
            for period in predictions_by_month
        }
        last_complete_month_target = (
            date(coverage_end.year + (coverage_end.month == 12), coverage_end.month % 12 + 1, 1)
            if coverage_end else None
        )
        for period in hotspot_map_dates:
            period_key = period.strftime('%Y-%m')
            if period not in predictions_by_month and period_key in historical_estimates:
                values = list(historical_estimates[period_key].values())
                predictions_by_month[period].extend(values)
                prediction_source_by_month[period] = (
                    'Last complete-month persistence benchmark'
                    if last_complete_month_target and period > last_complete_month_target
                    else 'Historical persistence baseline'
                )

        monthly_actual_totals = defaultdict(int)
        actual_by_month_barangay = defaultdict(int)
        for (year, month, _barangay), count in observed_by_month_barangay.items():
            monthly_actual_totals[date(year, month, 1)] += count
            actual_by_month_barangay[(date(year, month, 1), _barangay)] = count

        if current_month_actuals:
            monthly_actual_totals[current_month_start] = sum(current_month_actuals.values())
            for barangay_name, count in current_month_actuals.items():
                actual_by_month_barangay[(current_month_start, barangay_name)] = count

        month_has_actuals = {
            date(year, month, 1)
            for year, month, _barangay in observed_by_month_barangay
        }
        if current_month_actuals:
            month_has_actuals.add(current_month_start)
        monthly_hotspot_map_data = {}
        for period in hotspot_map_dates:
            barangay_values = {}
            for feature in (forecast_map_geojson or {}).get('features', []):
                barangay_name = canonicalize_barangay(
                    feature.get('properties', {}).get('brgy_name', '')
                )
                actual = (
                    actual_by_month_barangay.get((period, barangay_name))
                    if period in month_has_actuals else None
                )
                predicted = snapshots_by_month_barangay.get((period, barangay_name))
                # Use the same historical estimate that feeds the monthly
                # citywide total for every barangay-month without a saved
                # forecast. This keeps map colors/popups aligned with the
                # monthly comparison table, including post-coverage baselines.
                if (
                    predicted is None
                    and prediction_source_by_month.get(period) in {
                        'Historical persistence baseline',
                        'Last complete-month persistence benchmark',
                    }
                ):
                    predicted = historical_estimates.get(period.strftime('%Y-%m'), {}).get(barangay_name)
                if actual is not None and predicted is not None and period < current_month_start:
                    rounded = math.floor(predicted + 0.5)
                    match = actual == rounded
                else:
                    rounded = math.floor(predicted + 0.5) if predicted is not None else None
                    match = None
                barangay_values[barangay_name] = {
                    'actual_cases': actual,
                    'actual_risk': classify_risk(actual) if actual is not None else None,
                    'predicted_cases': predicted,
                    'predicted_risk': classify_risk(predicted) if predicted is not None else None,
                    'match': match,
                    'rounded_prediction': rounded,
                    'prediction_source': prediction_source_by_month.get(period, ''),
                }
            monthly_hotspot_map_data[period.strftime('%Y-%m')] = barangay_values

        monthly_comparison = []
        for period in comparison_dates:
            predicted_values = predictions_by_month.get(period, [])
            predicted_total = round(sum(predicted_values), 2) if predicted_values else None
            has_actual_data = period in {
                date(year, month, 1) for year, month, _barangay in observed_by_month_barangay
            } or (period == current_month_start and bool(current_month_actuals))
            actual_total = monthly_actual_totals.get(period) if has_actual_data else None
            is_completed_month = period < current_month_start
            actual_is_in_coverage = coverage_end is not None and period <= coverage_end
            has_live_confirmed_reports = (
                actual_total is not None
                and period > (coverage_end or date.min)
                and actual_total > 0
            )
            actual_is_available = actual_is_in_coverage or has_live_confirmed_reports
            if not actual_is_available:
                # Keep future/uncovered periods out of actual-vs-predicted
                # comparisons even if a grid row or saved snapshot contains 0.
                actual_total = None
                status = 'Pending data'
                coverage_label = coverage_end.strftime('%B %Y') if coverage_end else 'unavailable'
                detail = (
                    f'Confirmed dataset coverage ends {coverage_label}. '
                    'Actual counts will appear after this month is added to the dataset and confirmed.'
                )
            elif period == current_month_start and has_live_confirmed_reports:
                status = 'Month to date · provisional'
                if predicted_total is not None:
                    source = prediction_source_by_month.get(period, 'Forecast')
                    detail = (
                        f'{actual_total} confirmed system case(s) recorded through {today.strftime("%B %d, %Y")}; '
                        f'{source.lower()} is {predicted_total:.2f} cases. The month is incomplete, '
                        'so this is not a finalized actual-versus-prediction comparison.'
                    )
                else:
                    detail = (
                        f'{actual_total} confirmed system case(s) recorded through {today.strftime("%B %d, %Y")}. '
                        'This is a provisional month-to-date count.'
                    )
            elif predicted_total is not None and actual_total is not None and is_completed_month:
                rounded_prediction = math.floor(predicted_total + 0.5)
                difference = actual_total - rounded_prediction
                status = 'Match' if difference == 0 else f'{abs(difference)} case(s) ' + ('above' if difference > 0 else 'below') + ' prediction'
                source = prediction_source_by_month.get(period, 'Forecast')
                detail = f'{source}. Actual {actual_total} · rounded estimate {rounded_prediction} · difference {difference:+d} cases.'
            elif predicted_total is not None:
                status = 'Forecast · actual pending'
                detail = 'Actual counts will be recorded after the month ends and confirmed monthly data is available.'
            elif actual_total is not None:
                status = 'Actual available · no forecast'
                detail = 'Confirmed actual; historical estimate unavailable for this period.'
            else:
                status = 'Not available yet'
                detail = 'This model forecasts one calendar month ahead.'
            monthly_comparison.append({
                'key': period.strftime('%Y-%m'),
                'period': period.strftime('%B %Y'),
                'actual_cases': actual_total,
                'actual_pending': not actual_is_available,
                'predicted_cases': predicted_total,
                'prediction_source': prediction_source_by_month.get(period, ''),
                'status': status,
                'detail': detail,
            })

        context.update({
            'model_ready': True,
            'prediction_data_source': live_data_source,
            'prediction_input_provisional': input_provisional,
            'prediction_definition': PREDICTION_DEFINITION,
            'forecast_horizon': FORECAST_HORIZON,
            'forecast_geographic_unit': FORECAST_GEOGRAPHIC_UNIT,
            'forecast_target': FORECAST_TARGET,
            'observed_hotspot_threshold': OBSERVED_HOTSPOT_THRESHOLD,
            'predicted_hotspot_threshold': deployed_hotspot_threshold,
            'exploratory_review_threshold': EXPLORATORY_REVIEW_THRESHOLD,
            'forecasts': forecasts,
            'forecast_map_geojson': forecast_map_geojson,
            'model_metrics': metrics_for_display,
            'model_evaluation': model_evaluation_summary(
                metrics_for_display,
            ),
            'high_count': sum(
                row['risk_level'] == 'High'
                for row in forecasts
            ),
            'critical_count': sum(
                row['risk_level'] == 'Critical'
                for row in forecasts
            ),
            'moderate_count': sum(
                row['risk_level'] == 'Moderate'
                for row in forecasts
            ),
            'low_count': sum(
                row['risk_level'] == 'Low'
                for row in forecasts
            ),
            'priority_barangays': priority_barangays,
            'potential_hotspots': potential_hotspots,
            'precision_candidate_hotspots': precision_candidate_hotspots,
            'planning_summary': planning_summary,
            'forecast_period': (
                f'{month_name[next_month]} {next_year}'
            ),
            'monthly_comparison': monthly_comparison,
            'monthly_hotspot_map_data': monthly_hotspot_map_data,
            'hotspot_map_months': [
                {'key': period.strftime('%Y-%m'), 'period': period.strftime('%B %Y')}
                for period in hotspot_map_dates
            ],
            'hotspot_map_start_period': map_start.strftime('%B %Y'),
            'hotspot_map_end_period': display_end.strftime('%B %Y'),
            'hotspot_map_default_period': current_month_start.strftime('%B %Y'),
            'actual_coverage_period': coverage_end.strftime('%B %Y') if coverage_end else 'unavailable',
            'case_data_period': (
                f'{month_name[latest_month]} {latest_year}'
            ),
            'weather': weather,
            'weather_date_options': weather_date_options(),
            'demographic_summary': demographic_summary,
            'blood_type_by_year': blood_type_by_year,
            'blood_type_feature_notice': BLOOD_TYPE_FEATURE_NOTICE,
        })

    except (
        AttributeError,
        ImportError,
        ModuleNotFoundError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        error_text = str(exc)

        if '_RemainderColsList' in error_text:
            context['prediction_error'] = (
                'The saved Random Forest model is incompatible with the '
                'installed scikit-learn version. Retrain the model using '
                'the current environment, then reload this page.'
            )
        else:
            context['prediction_error'] = (
                f'Prediction could not be generated: {error_text}'
            )

    return context
