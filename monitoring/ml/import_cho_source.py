"""Import and audit the latest CHO dengue line list without dropping source rows.

Run from the repository root:
    python monitoring/ml/import_cho_source.py "C:/path/to/CHO.csv"

Creates a dated backup of the prior active line list and archives the uploaded
source before replacing the active canonical CSV. Patient-level values are
never printed by this script.
"""

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    from monitoring.locations import canonicalize_barangay, is_iligan_city
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from monitoring.locations import canonicalize_barangay, is_iligan_city


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "datasets"
ACTIVE = DATASETS / "WILBUR_DSO_dengue_2018_2026_authoritative.csv"
QUALITY = DATASETS / "dengue_dataset_quality.json"
MANIFEST = DATASETS / "cho_historical" / "manifest.json"
SOURCE_COLUMNS = [
    "Sex", "AgeYears", "(Current Address) City / Municipality",
    "(Current Address) Barangay", "(Current Address) Sitio / Purok / Street Name",
    "DAdmit", "Year", "BloodType",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def import_source(source: Path) -> dict:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    raw = pd.read_csv(source, dtype=object, keep_default_na=False, encoding="utf-8-sig")
    header_map = {
        "gender": "Sex", "age": "AgeYears", "city": "(Current Address) City / Municipality",
        "barangay": "(Current Address) Barangay", "purok": "(Current Address) Sitio / Purok / Street Name",
        "dateadmitted": "DAdmit", "year": "Year", "bloodtype": "BloodType",
    }
    mapped = {}
    for column in raw.columns:
        mapped[column] = header_map.get(_canonical_header(str(column)), str(column))
    data = raw.rename(columns=mapped).copy()
    missing_columns = [name for name in SOURCE_COLUMNS if name not in data]
    if missing_columns:
        raise ValueError(f"Required fields are missing: {', '.join(missing_columns)}")

    extra_columns = [column for column in data.columns if column not in SOURCE_COLUMNS]
    extra_values = data[extra_columns].astype(str).apply(
        lambda row: " | ".join(value.strip() for value in row if value.strip()), axis=1
    ) if extra_columns else pd.Series("", index=data.index)
    data["SourceExtraColumn"] = extra_values
    data["SourceWorkbook"] = source.name

    # Accept rows with mixed ISO and m/d/yyyy dates; pandas' strict vector
    # inference can otherwise mark later valid US-style dates as invalid.
    dates = pd.to_datetime(data["DAdmit"], errors="coerce", format="mixed")
    source_years = pd.to_numeric(data["Year"], errors="coerce")
    years = source_years.copy()
    date_missing = dates.isna()
    year_mismatch = dates.notna() & years.notna() & dates.dt.year.ne(years)
    # Maps and model counts must use the admission date as the event period.
    # Preserve the source's YEAR value separately so every mismatch remains auditable.
    data["SourceYear"] = data["Year"]
    derived_year = dates.dt.year.astype("Int64").astype("string")
    data["Year"] = derived_year.fillna(data["Year"].astype("string")).fillna("")
    city_ok = data["(Current Address) City / Municipality"].map(is_iligan_city)
    barangays = data["(Current Address) Barangay"].map(canonicalize_barangay)
    normalized_key = data[SOURCE_COLUMNS].astype(str).copy()
    normalized_key["DAdmit"] = dates.dt.strftime("%Y-%m-%d").fillna("")
    normalized_key["Year"] = source_years.astype(str)
    duplicate = normalized_key.duplicated(keep="first")
    flags = []
    for idx in data.index:
        row_flags = []
        if date_missing.loc[idx]:
            row_flags.append("missing_or_invalid_admission_date")
        if year_mismatch.loc[idx]:
            row_flags.append("year_admission_date_mismatch")
        if duplicate.loc[idx]:
            row_flags.append("exact_repeat_row_review_with_CHO")
        if not city_ok.loc[idx]:
            row_flags.append("outside_iligan_city")
        if pd.isna(barangays.loc[idx]):
            row_flags.append("unmatched_official_barangay")
        flags.append(";".join(row_flags))
    data["DataQualityFlags"] = flags

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = DATASETS / "cho_source_archive"
    backup_dir = DATASETS / "source_backups"
    archive_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    archived_upload = archive_dir / f"{stamp}_{source.name}"
    shutil.copy2(source, archived_upload)
    prior_backup = None
    if ACTIVE.exists():
        prior_backup = backup_dir / f"{stamp}_{ACTIVE.name}"
        shutil.copy2(ACTIVE, prior_backup)

    # Keep the original submitted strings intact; loader parses DAdmit and
    # canonicalizes barangays at aggregation time.
    data = data[SOURCE_COLUMNS + ["SourceYear", "SourceWorkbook", "SourceExtraColumn", "DataQualityFlags"]]
    data.to_csv(ACTIVE, index=False, encoding="utf-8-sig")

    valid_dates = dates.notna()
    date_year_counts = dates[valid_dates].dt.year.value_counts().sort_index()
    year_column_counts = years.dropna().astype(int).value_counts().sort_index()
    exact_extra = int(duplicate.sum())
    audit = {
        "dataset_name": "DengueWatch consolidated CHO-verified 2018-2026 line-list source",
        "active_file": ACTIVE.name,
        "source_file": source.name,
        "source_files": [source.name],
        "source_sha256": sha256(source),
        "archived_upload": str(archived_upload.relative_to(ROOT)).replace("\\", "/"),
        "previous_active_backup": str(prior_backup.relative_to(ROOT)).replace("\\", "/") if prior_backup else None,
        "source_attribution": "CHO verification confirmed by the project team for the uploaded 2018-2026 source.",
        "source_row_count": int(len(data)),
        "all_rows_retained": True,
        "unique_rows_by_exact_eight_field_match": int(len(data) - exact_extra),
        "exact_duplicate_extra_rows": exact_extra,
        "rows_in_exact_duplicate_groups": int(normalized_key.duplicated(keep=False).sum()),
        "rows_complete_across_all_eight_requested_fields": int(data[SOURCE_COLUMNS].replace("", pd.NA).notna().all(axis=1).sum()),
        "rows_with_one_or_more_missing_requested_fields": int(data[SOURCE_COLUMNS].replace("", pd.NA).isna().any(axis=1).sum()),
        "missing_values_by_field": {column: int(data[column].astype(str).str.strip().eq("").sum()) for column in SOURCE_COLUMNS},
        "admission_date_valid_rows": int(valid_dates.sum()),
        "admission_date_missing_or_invalid_rows": int(date_missing.sum()),
        "admission_date_year_mismatch_rows": int(year_mismatch.sum()),
        "rows_without_official_iligan_barangay_match": int(barangays.isna().sum()),
        "outside_iligan_city_rows": int((~city_ok).sum()),
        "extra_source_columns_preserved_as_SourceExtraColumn": extra_columns,
        "nonempty_preserved_extra_values": int(extra_values.astype(str).str.strip().ne("").sum()),
        "admission_date_range": [dates.min().date().isoformat(), dates.max().date().isoformat()] if valid_dates.any() else None,
        "counts_by_year_column": {str(int(k)): int(v) for k, v in year_column_counts.items()},
        "counts_by_admission_date_year": {str(int(k)): int(v) for k, v in date_year_counts.items()},
        "city_value_counts": {str(k): int(v) for k, v in data["(Current Address) City / Municipality"].value_counts().items()},
        "duplicate_policy": "Retain all rows and flag exact repeats for CHO review; no stable case identifier is available.",
        "date_policy": "Retain submitted dates and Year values; flag missing/invalid dates and year mismatches.",
        "application_year_policy": "For mapping and reporting, Year is derived from valid DAdmit to keep annual case totals consistent with event date; the submitted year remains in SourceYear and mismatches are flagged.",
        "map_and_training_scope": "Only valid admission dates, official Iligan barangays, and Iligan City rows are aggregated for city modeling.",
        "total_semantics": "Source rows, not verified unique people or independently adjudicated case count.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_verification_status": "CHO-verified per project-team confirmation; the source itself does not encode case-definition version or received date.",
    }
    QUALITY.write_text(json.dumps(audit, indent=2), encoding="utf-8")

    manifest = {
        "status": "CHO_attributed_historical_source_integrated",
        "source_attribution": audit["source_attribution"],
        "active_source_file": ACTIVE.name,
        "included_in_operational_totals_maps_and_training": True,
        "historical_datasets": {},
        "previous_synthetic_submission_status": "Synthetic demo records remain excluded from the active line list.",
        "row_handling": audit["duplicate_policy"],
        "combined_case_rows": int(len(data)),
        "active_source_sha256": audit["source_sha256"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    for year in (2018, 2019):
        rowmask = dates.dt.year.eq(year)
        year_data = data.loc[rowmask]
        manifest["historical_datasets"][str(year)] = {
            "source_file": source.name,
            "rows": int(rowmask.sum()),
            "rows_by_admission_date": int(rowmask.sum()),
            "rows_by_year_column": int(source_years.eq(year).sum()),
            "exact_duplicate_extra_rows": int(duplicate.loc[rowmask].sum()),
            "rows_with_unmatched_barangay": int(barangays.loc[rowmask].isna().sum()),
            "sha256": audit["source_sha256"],
            "invalid_admission_dates_not_in_year_count": True,
        }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    result = import_source(args.source)
    print(json.dumps({
        key: result[key] for key in (
            "source_row_count", "admission_date_valid_rows", "admission_date_missing_or_invalid_rows",
            "admission_date_year_mismatch_rows", "exact_duplicate_extra_rows",
            "outside_iligan_city_rows", "rows_without_official_iligan_barangay_match",
            "nonempty_preserved_extra_values", "counts_by_admission_date_year",
            "counts_by_year_column", "source_sha256", "active_file",
        )
    }, indent=2))
