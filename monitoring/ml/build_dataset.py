"""Build a barangay-month dengue/weather dataset for model training.

Weather is requested from Open-Meteo's Historical Weather API at a
boundary-derived representative point for each official barangay. Cache
fallbacks are labeled with their original spatial scope; no weather values are
invented. Keep the generated metadata with the research records for audit.
"""

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

try:
    from monitoring.locations import ILIGAN_BARANGAYS, canonicalize_barangay, is_iligan_city
    from monitoring.ml.features import BLOOD_TYPES, BLOOD_TYPE_COLUMNS
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from monitoring.locations import ILIGAN_BARANGAYS, canonicalize_barangay, is_iligan_city
    from monitoring.ml.features import BLOOD_TYPES, BLOOD_TYPE_COLUMNS

BOUNDARY_PATH = Path(__file__).resolve().parents[2] / 'static' / 'data' / 'iligan_barangays.geojson'


def load_barangay_coordinates() -> dict[str, tuple[float, float]]:
    """Return boundary-derived representative points in (lat, lon) order."""
    try:
        features = json.loads(BOUNDARY_PATH.read_text(encoding='utf-8')).get('features', [])
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f'Could not read official barangay boundaries: {error}') from error

    def coordinate_pairs(value):
        if (
            isinstance(value, list) and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            yield float(value[0]), float(value[1])
        elif isinstance(value, list):
            for child in value:
                yield from coordinate_pairs(child)

    coordinates = {}
    for feature in features:
        name = canonicalize_barangay(feature.get('properties', {}).get('brgy_name'))
        points = list(coordinate_pairs(feature.get('geometry', {}).get('coordinates', [])))
        if name and points:
            # Use the mean of boundary vertices as a reproducible representative
            # point. Open-Meteo will snap this coordinate to its weather grid;
            # adjacent barangays may therefore still share a grid estimate.
            coordinates[name] = (
                sum(latitude for longitude, latitude in points) / len(points),
                sum(longitude for longitude, latitude in points) / len(points),
            )
    missing = set(ILIGAN_BARANGAYS) - set(coordinates)
    if missing:
        raise RuntimeError(f'No representative boundary coordinate for: {", ".join(sorted(missing))}')
    return {name: coordinates[name] for name in ILIGAN_BARANGAYS}


def read_cases(dataset_dir: Path) -> pd.DataFrame:
    """Read only the selected CHO master case file; never merge other datasets."""
    records = []
    authoritative = dataset_dir / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv'
    if not authoritative.is_file():
        raise FileNotFoundError(f'Required CHO master dengue dataset is missing: {authoritative}')
    with authoritative.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            city = row.get('(Current Address) City / Municipality')
            if '(Current Address) City / Municipality' in row and not is_iligan_city(city):
                continue
            barangay = canonicalize_barangay(row.get('(Current Address) Barangay'))
            date = pd.to_datetime(row.get('DAdmit'), errors='coerce')
            blood_type = str(row.get('Blood Type') or row.get('Bloodtype') or row.get('BloodType') or '').strip().upper().replace(' ', '')
            if barangay and pd.notna(date):
                records.append({'barangay': barangay, 'date': date, 'blood_type': blood_type})
    if not records:
        raise ValueError('No valid dengue case rows were found.')
    return pd.DataFrame(records)


def fetch_weather(start_date: str, end_date: str, locations: dict[str, tuple[float, float]]) -> tuple[pd.DataFrame, str]:
    """Fetch ERA5 daily data in small coordinate batches and aggregate monthly."""
    records = []
    request_urls = []
    names = list(locations)
    for offset in range(0, len(names), 10):
        batch_names = names[offset:offset + 10]
        params = {
            'latitude': ','.join(f'{locations[name][0]:.6f}' for name in batch_names),
            'longitude': ','.join(f'{locations[name][1]:.6f}' for name in batch_names),
            'start_date': start_date,
            'end_date': end_date,
            'daily': 'temperature_2m_mean,precipitation_sum,relative_humidity_2m_mean',
            'timezone': 'Asia/Manila',
            # ERA5 has all three requested fields. ERA5-Land returns null for
            # precipitation in the archive, so it cannot fill rainfall gaps.
            'models': 'era5',
        }
        url = 'https://archive-api.open-meteo.com/v1/archive?' + urlencode(params)
        request_urls.append(url)
        for attempt in range(5):
            try:
                with urlopen(url, timeout=90) as response:
                    payload = json.load(response)
                break
            except Exception as error:
                # Open-Meteo may return HTTP 429 when several coordinate
                # batches are requested together. Retry politely before failing.
                if getattr(error, 'code', None) != 429 or attempt == 4:
                    raise
                time.sleep(10 * (attempt + 1))
        location_payloads = payload if isinstance(payload, list) else [payload]
        if len(location_payloads) != len(batch_names):
            raise RuntimeError(f'Open-Meteo returned {len(location_payloads)} locations for {len(batch_names)} requested barangays.')

        for name, location in zip(batch_names, location_payloads):
            if location.get('error'):
                raise RuntimeError(f'Open-Meteo error for {name}: {location.get("reason", "unspecified API error")}')
            daily = pd.DataFrame(location.get('daily') or {}).rename(columns={
                'time': 'date', 'temperature_2m_mean': 'temperature_c',
                'precipitation_sum': 'rainfall_mm',
                'relative_humidity_2m_mean': 'humidity_pct',
            })
            if daily.empty:
                continue
            daily['date'] = pd.to_datetime(daily['date'])
            daily['month_date'] = daily['date'].dt.to_period('M').dt.to_timestamp()
            monthly = daily.groupby('month_date', as_index=False).agg(
                temperature_c=('temperature_c', 'mean'),
                rainfall_mm=('rainfall_mm', 'sum'),
                humidity_pct=('humidity_pct', 'mean'),
                weather_days=('date', 'nunique'),
                temperature_days=('temperature_c', 'count'),
                rainfall_days=('rainfall_mm', 'count'),
                humidity_days=('humidity_pct', 'count'),
            )
            days_in_month = monthly['month_date'].dt.days_in_month
            monthly.loc[monthly['temperature_days'] < days_in_month, 'temperature_c'] = pd.NA
            monthly.loc[monthly['rainfall_days'] < days_in_month, 'rainfall_mm'] = pd.NA
            monthly.loc[monthly['humidity_days'] < days_in_month, 'humidity_pct'] = pd.NA
            monthly['barangay'] = name
            monthly['requested_latitude'] = locations[name][0]
            monthly['requested_longitude'] = locations[name][1]
            monthly['grid_latitude'] = location.get('latitude')
            monthly['grid_longitude'] = location.get('longitude')
            monthly['weather_observation_status'] = np.where(
                (monthly['temperature_days'] == days_in_month)
                & (monthly['rainfall_days'] == days_in_month)
                & (monthly['humidity_days'] == days_in_month),
                'open_meteo_era5_reanalysis_month_complete',
                'open_meteo_era5_reanalysis_partial_month',
            )
            records.append(monthly)
    if len(records) != len(names):
        received = {record['barangay'].iloc[0] for record in records}
        raise RuntimeError(f'Open-Meteo returned no usable daily values for: {", ".join(sorted(set(names) - received))}')
    return pd.concat(records, ignore_index=True), request_urls[0] if len(request_urls) == 1 else f'{len(request_urls)} batched archive requests (ERA5)'


def merge_weather_cache(cached: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    """Keep existing weather and replace only rows with newly fetched archive data."""
    key = ['barangay', 'month_date']
    combined = pd.concat([cached, fetched], ignore_index=True, sort=False)
    combined['_source_priority'] = combined['weather_observation_status'].astype(str).str.startswith('open_meteo_era5_reanalysis').astype(int)
    combined = combined.sort_values('_source_priority').drop_duplicates(key, keep='last')
    return combined.drop(columns='_source_priority').reset_index(drop=True)


def load_cached_weather(dataset_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Reuse per-barangay cached weather; label legacy city-point values honestly."""
    cache_path = dataset_dir / 'integrated_monthly.csv'
    if not cache_path.is_file():
        raise RuntimeError('No cached weather dataset is available.')
    cached = pd.read_csv(cache_path)
    keep = ['year', 'month', 'rainfall_mm', 'temperature_c', 'humidity_pct']
    keep += [column for column in (
        'barangay', 'requested_latitude', 'requested_longitude', 'grid_latitude',
        'grid_longitude', 'weather_days', 'temperature_days', 'rainfall_days',
        'humidity_days', 'weather_observation_status',
    ) if column in cached]
    cached = cached[keep]
    cached['date'] = pd.to_datetime(dict(year=cached.year, month=cached.month, day=1))
    cached['month_date'] = cached['date']
    if 'barangay' not in cached:
        cached['barangay'] = None
    for column in ('requested_latitude', 'requested_longitude', 'grid_latitude', 'grid_longitude',
                   'weather_days', 'temperature_days', 'rainfall_days', 'humidity_days'):
        if column not in cached:
            cached[column] = pd.NA
    if 'weather_observation_status' not in cached:
        cached['weather_observation_status'] = 'cached_city_point_not_barangay_specific'
    return cached


def build(dataset_dir: Path, output: Path, metadata: Path) -> pd.DataFrame:
    cases = read_cases(dataset_dir)
    cases['month_date'] = cases['date'].dt.to_period('M').dt.to_timestamp()
    # Only model months explicitly covered by the project's CHO completeness
    # confirmation. The master line list can contain provisional rows outside
    # that window; including them would silently treat an incomplete month as
    # a complete training target.
    completeness_path = dataset_dir / 'case_reporting_completeness.json'
    completeness = json.loads(completeness_path.read_text(encoding='utf-8'))
    if completeness.get('status') != 'complete_for_modeling_scope' or not completeness.get('no_case_rows_mean_confirmed_zero'):
        raise ValueError(
            'Case reporting completeness is not confirmed. Update '
            'case_reporting_completeness.json from an authorized source before modeling.'
        )
    start = pd.Period(completeness['coverage_start'], freq='M').to_timestamp()
    end = pd.Period(completeness['coverage_end'], freq='M').to_timestamp()
    cases = cases[cases['month_date'].between(start, end)].copy()
    if cases.empty:
        raise ValueError('The authoritative case dataset has no valid rows in its confirmed coverage window.')
    locations = load_barangay_coordinates()
    previous_weather_metadata = {}
    try:
        previous_weather_metadata = json.loads(metadata.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        pass
    cached_weather = load_cached_weather(dataset_dir, start, end)
    cached_weather = cached_weather[cached_weather['month_date'].between(start, end)].copy()
    expected_weather_months = list(pd.date_range(start, end, freq='MS'))
    # The old cache had rows for 2018–2019 but its three weather fields were
    # blank. Find gaps at the barangay-month level, rather than assuming that a
    # present month row contains weather.
    weather_fields = ['rainfall_mm', 'temperature_c', 'humidity_pct']
    if cached_weather['barangay'].notna().any():
        missing_weather_months = sorted(
            cached_weather.loc[cached_weather[weather_fields].isna().any(axis=1), 'month_date'].unique()
        )
        cached_has_barangay_points = True
    else:
        missing_weather_months = expected_weather_months
        cached_has_barangay_points = False
    fetched_parts = []
    fetch_error = None
    # Group consecutive missing months into compact archive requests. This
    # avoids re-downloading years of already-cached data on every dataset build.
    if missing_weather_months:
        ranges = []
        range_start = range_end = pd.Timestamp(missing_weather_months[0])
        for month in missing_weather_months[1:]:
            month = pd.Timestamp(month)
            if month == range_end + pd.offsets.MonthBegin(1):
                range_end = month
            else:
                ranges.append((range_start, range_end))
                range_start = range_end = month
        ranges.append((range_start, range_end))
        try:
            for range_start, range_end in ranges:
                fetched, _ = fetch_weather(
                    range_start.strftime('%Y-%m-%d'),
                    (range_end + pd.offsets.MonthEnd(0)).strftime('%Y-%m-%d'),
                    locations,
                )
                fetched_parts.append(fetched)
        except Exception as error:
            fetch_error = error

    if fetched_parts:
        fetched_weather = pd.concat(fetched_parts, ignore_index=True)
        weather = merge_weather_cache(cached_weather, fetched_weather) if cached_has_barangay_points else fetched_weather
        weather_source = 'Open-Meteo Historical Weather API ERA5 (per-barangay representative points; missing-period values merged with cached archive values)'
        weather_note = None
        weather_source_status = 'archive_fetched_per_barangay'
        weather_retrieved_at = datetime.now(timezone.utc).isoformat()
        source_url = 'https://archive-api.open-meteo.com/v1/archive (daily ERA5; missing periods fetched in coordinate batches)'
    elif not missing_weather_months:
        # A complete cache is a successful no-op, not a failed live API call.
        # Preserve its recorded provenance and retrieval timestamp. If the
        # weather rows themselves identify the ERA5 gap-fill, recover that
        # provenance even if a previous no-network rebuild marked the cache as
        # merely cached.
        weather = cached_weather
        statuses = weather['weather_observation_status'].dropna().astype(str)
        contains_era5_gapfill = statuses.str.startswith('open_meteo_era5_reanalysis').any()
        if contains_era5_gapfill:
            weather_source = 'Open-Meteo Historical Weather API ERA5 for gap-filled rows; existing per-barangay archive values retained for other periods'
            weather_source_status = 'archive_fetched_per_barangay'
            source_url = 'https://archive-api.open-meteo.com/v1/archive (ERA5 gap-fill retained in local weather cache)'
        else:
            weather_source = previous_weather_metadata.get('source', 'Cached Open-Meteo historical values (per-barangay representative points)')
            weather_source_status = previous_weather_metadata.get('weather_source_status', 'cached_per_barangay_archive_used')
            source_url = previous_weather_metadata.get('source_url', 'local integrated_monthly.csv weather cache')
        weather_retrieved_at = previous_weather_metadata.get('weather_retrieved_at_utc')
        weather_note = previous_weather_metadata.get('weather_retrieval_note')
        weather_scope = previous_weather_metadata.get('weather_scope', 'One representative point per barangay; adjacent barangays may share weather grid cells.')
    else:
        weather = cached_weather
        has_grid_coordinates = weather['grid_latitude'].notna().any()
        if has_grid_coordinates:
            weather_source = 'Cached Open-Meteo historical values (per-barangay representative points; mixed/legacy model provenance)'
            weather_scope = previous_weather_metadata.get('weather_scope', 'One representative point per barangay; adjacent barangays may share weather grid cells.')
            weather_source_status = 'live_archive_unavailable_cached_per_barangay'
        else:
            weather_source = 'Cached Open-Meteo values (legacy city-point coverage)'
            weather_scope = 'City-center point repeated across barangays; does not represent per-barangay spatial variation.'
            weather_source_status = 'live_archive_unavailable_legacy_city_cache_used'
        weather_retrieved_at = previous_weather_metadata.get('weather_retrieved_at_utc')
        source_url = 'local integrated_monthly.csv weather cache'
        if fetch_error:
            weather_note = f'Open-Meteo archive retrieval failed: {fetch_error}'
        else:
            weather_note = previous_weather_metadata.get('weather_retrieval_note')
    weather_scope = 'One boundary-derived representative point per official barangay; modeled grid-cell estimates, and adjacent barangays may share grid cells.'

    # Build the official barangay-month grid for the confirmed-complete period.
    # The completeness metadata records the project team's CHO verification.
    names = sorted(ILIGAN_BARANGAYS, key=str.casefold)
    months = pd.date_range(start, end, freq='MS')
    grid = pd.MultiIndex.from_product(
        [names, months], names=['barangay', 'month_date']
    ).to_frame(index=False)
    counts = cases.groupby(['barangay', 'month_date']).size().rename('case_count').reset_index()
    result = grid.merge(counts, how='left', on=['barangay', 'month_date'])
    result['case_count'] = result['case_count'].fillna(0).astype(int)
    result['case_observation_status'] = result['case_count'].map(
        lambda count: 'cases_present_line_list_count' if count else 'zero_confirmed_by_cho'
    )
    valid_blood = cases[cases['blood_type'].isin(BLOOD_TYPES)]
    blood_counts = valid_blood.groupby(['barangay', 'month_date', 'blood_type']).size().unstack(fill_value=0)
    blood_counts = blood_counts.reindex(columns=BLOOD_TYPES, fill_value=0).reset_index()
    result = result.merge(blood_counts, how='left', on=['barangay', 'month_date'])
    for blood_type, column in zip(BLOOD_TYPES, BLOOD_TYPE_COLUMNS):
        result[column] = (result[blood_type].fillna(0) / result['case_count'].replace(0, 1)).where(result['case_count'] > 0, 0.0)
    result = result.drop(columns=list(BLOOD_TYPES))
    if 'barangay' not in weather or weather['barangay'].isna().all():
        weather = weather.drop(columns=['barangay'], errors='ignore')
        result = result.merge(weather, how='left', left_on='month_date', right_on='date')
        if 'requested_latitude' not in result:
            result['requested_latitude'] = result['barangay'].map({name: point[0] for name, point in locations.items()})
            result['requested_longitude'] = result['barangay'].map({name: point[1] for name, point in locations.items()})
    else:
        result = result.merge(weather, how='left', left_on=['barangay', 'month_date'], right_on=['barangay', 'month_date'])
        result = result.drop(columns=['date'], errors='ignore')
    missing_weather_count = int(result[['rainfall_mm', 'temperature_c', 'humidity_pct']].isna().any(axis=1).sum())
    missing_weather_periods = sorted(
        result.loc[
            result[['rainfall_mm', 'temperature_c', 'humidity_pct']].isna().any(axis=1),
            'month_date',
        ].drop_duplicates()
    )
    result['year'] = result['month_date'].dt.year
    result['month'] = result['month_date'].dt.month
    result = result[[
        'barangay', 'year', 'month', 'case_count', 'case_observation_status', 'rainfall_mm',
        'temperature_c', 'humidity_pct', *BLOOD_TYPE_COLUMNS,
        'weather_observation_status', 'weather_days', 'temperature_days',
        'rainfall_days', 'humidity_days', 'requested_latitude',
        'requested_longitude', 'grid_latitude', 'grid_longitude',
    ]]
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    metadata.write_text(json.dumps({
        'source': weather_source,
        'weather_source_status': weather_source_status,
        'source_url': source_url,
        'locations': {name: {'latitude': lat, 'longitude': lon} for name, (lat, lon) in locations.items()},
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'weather_retrieved_at_utc': weather_retrieved_at,
        'weather_scope': weather_scope,
        'weather_model': 'ERA5 for newly filled periods; prior cached periods retain their recorded source/model provenance.',
        'weather_model_resolution_note': 'ERA5 reanalysis (approximately 0.25 degrees / 25 km) was requested explicitly for missing historical values because it provides all three required variables, including precipitation. ERA5-Land does not provide precipitation in this archive. Requested coordinates and API-returned grid coordinates are saved to audit shared grid cells.',
        'limitations': 'Open-Meteo archive values are reanalysis/model estimates and are not direct barangay station observations. Validate against PAGASA or other authorized station records before treating them as locally verified. If live retrieval fails, legacy city-point cache is retained and labeled as non-local fallback.',
        'location_scope': '44 official City of Iligan barangays (PSGC)',
        'psgc_source': 'https://psa.gov.ph/classification/psgc/barangays/1030900000',
        'rows': len(result),
        'case_coverage_start': str(completeness['coverage_start']),
        'case_coverage_end': str(completeness['coverage_end']),
        'case_completeness_source': completeness.get('source'),
        'case_completeness_confirmation': completeness.get('confirmed_by'),
        'case_rows_outside_confirmed_coverage_excluded': int(
            (pd.to_datetime(read_cases(dataset_dir)['date']).dt.to_period('M').dt.to_timestamp().gt(end)).sum()
        ),
        'weather_retrieval_note': weather_note,
        'weather_missing_months_requested': [pd.Timestamp(month).strftime('%Y-%m') for month in missing_weather_months],
        'weather_missing_model_rows': missing_weather_count,
        'weather_locations_requested': len(locations),
        'weather_grid_cells_returned': int(result[['grid_latitude', 'grid_longitude']].dropna().drop_duplicates().shape[0]),
        'weather_missing_periods': [pd.Timestamp(month).strftime('%Y-%m') for month in missing_weather_periods],
    }, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', type=Path, default=root / 'datasets')
    parser.add_argument('--output', type=Path, default=root / 'datasets' / 'integrated_monthly.csv')
    parser.add_argument('--metadata', type=Path, default=root / 'datasets' / 'weather_source.json')
    args = parser.parse_args()
    frame = build(args.datasets, args.output, args.metadata)
    print(f'Created {args.output} with {len(frame)} rows.')
