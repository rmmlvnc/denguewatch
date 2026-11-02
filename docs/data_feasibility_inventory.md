# DengueWatch data feasibility inventory

Generated: 2026-10-22T14:44:08.709023+00:00

This inventory contains aggregate quality counts only. It does not contain patient-level data.

## Case data

- Active source: `WILBUR_DSO_dengue_2018_2026_authoritative.csv`.
- Source verification: The project team confirms all active 2018-2026 dengue case datasets were verified by CHO. Earlier files explicitly marked synthetic remain excluded.
- Consolidated source lineage: 14071 active rows versus 14071 in the quality audit (match: True).
- Import policy: The active consolidated line list contains the 2018-2019 and 2020-2026 dengue datasets, confirmed by the project team as CHO-verified. Earlier explicitly synthetic 2018-2019 demo copies remain separately archived and excluded.
- CHO-verified 2018 records: 1781 rows by admission date; 0 exact-repeat rows retained; 1 rows have an unmatched official barangay; source SHA-256 `e6d874eceaa29518e8a86d9fee9e034b42e4f2d387d4ee891e0477275e71d8f4`.
- CHO-verified 2019 records: 1888 rows by admission date; 0 exact-repeat rows retained; 0 rows have an unmatched official barangay; source SHA-256 `e6d874eceaa29518e8a86d9fee9e034b42e4f2d387d4ee891e0477275e71d8f4`.
- Original source files: WILBUR_DSO_dengue_2018_2026_authoritative.csv.
- Record type: Individual case line list; rows with valid DAdmit and official barangay are aggregated for model input.
- Source rows: 14071; usable rows with valid admission date and official barangay: 14068.
- Admission-date range: 2018-01-01 to 2026-11-23; official barangays present: 44.
- Missing/unmatched barangay: 1; invalid/missing admission date: 2.
- Potential duplicate matches: 0. No stable case ID is present, so matches are retained for CHO review rather than automatically deleted.
- Exact duplicate extra rows flagged by the source quality audit: 0; these are retained. Potential demographic/location matches are a separate, broader review category.
- Case definition: DAdmit and current-address barangay are present; confirmation criteria and case-definition version are not represented in the source workbook.
- Reporting delay: Cannot be calculated; source has admission date but no received/entered date.

- Completeness confirmation: Project team confirmation in this conversation on 2026-10-19.
## Existing monthly model input

- `integrated_monthly.csv` has 4532 rows for 44 barangays and 103 months (2018-01 through 2026-07); duplicate barangay-month rows: 0.
- Empty line-list cells: 1368; zero cells under the project-team CHO completeness confirmation: 1368.
- Zero interpretation: Based on the project-team confirmation of CHO data completeness for the CHO-sourced dataset, covered barangay-months with no line-list rows are treated as zero cases.
- Retraining gate: Zero-versus-missing ambiguity cleared by the recorded completeness confirmation; retraining is permitted, with remaining case-definition, duplicate, and reporting-delay limitations disclosed.

## Archived synthetic demonstration files

- 3720 rows are archived separately across 2 synthetic files; they are excluded from official case totals, maps, alerts, model training, and validation. The filenames and manifest identify them as synthetic; the eight-column CSVs do not have an extra per-row flag.
- These earlier synthetic files remain excluded from totals, maps, alerts, model training, and validation. The latest CHO-verified rows are described above and are part of the active consolidated source.
## Weekly feasibility candidate

- `weekly_feasibility_candidate.csv` creates 20460 barangay-week rows for 465 weeks (2018-01-01 through 2026-11-23).
- Barangay-weeks with cases present: 7650; no-record barangay-weeks: 0.
- Zero policy: No-case weeks within the CHO-sourced dataset are treated as zero based on the project-team confirmation of CHO data completeness; a separate CHO zero-report register was not supplied.
- No-case weeks are treated as zero under the same project-team confirmation of CHO data completeness; the project does not yet have a separate CHO completeness register to independently verify that assertion.

## Weather

- Source: Open-Meteo Historical Weather API ERA5 for gap-filled rows; existing per-barangay archive values retained for other periods.
- Retrieval status: archive_fetched_per_barangay.
- Variables: temperature_c (monthly mean temperature, degrees Celsius), rainfall_mm (monthly precipitation sum, millimeters), humidity_pct (monthly mean of daily mean relative humidity, percent).
- Matching: One boundary-derived representative point per official barangay; modeled grid-cell estimates, and adjacent barangays may share grid cells.
- Spatial resolution: ERA5 reanalysis (approximately 0.25 degrees / 25 km) was requested explicitly for missing historical values because it provides all three required variables, including precipitation. ERA5-Land does not provide precipitation in this archive. Requested coordinates and API-returned grid coordinates are saved to audit shared grid cells.
- Limitation: Open-Meteo archive values are reanalysis/model estimates and are not direct barangay station observations. Validate against PAGASA or other authorized station records before treating them as locally verified. If live retrieval fails, legacy city-point cache is retained and labeled as non-local fallback.

- Location points requested: 44; distinct returned grid cells: 10. Missing barangay-month weather rows: 0.
## Existing model compatibility

- Compatible with updated weather history: True
- Training weather scope: One boundary-derived representative point per official barangay; modeled grid-cell estimates, and adjacent barangays may share grid cells.
- Current weather scope: One boundary-derived representative point per official barangay; modeled grid-cell estimates, and adjacent barangays may share grid cells.
- The saved model was retrained using the current Open-Meteo historical monthly weather at one representative point per barangay.

## Feasibility actions

- Document CHO authorization, access roles, retention, and approved transfer/storage method for source records.
- Obtain the CHO case definition/version and identify which records are confirmed versus suspected.
- Capture report-received dates and maintain the completeness confirmation for future data updates.
- Obtain a stable de-identified case key so true duplicate records can be resolved safely.
- Validate barangay representative-point reanalysis estimates against PAGASA or another authorized station source before operational use.

**Current modeling decision:** Monthly forecasting is enabled using the recorded completeness confirmation and the updated per-barangay weather inputs. Scores remain provisional because the source does not document the CHO case definition, report-received dates, or stable identifiers for resolving duplicate records; final test performance must beat simple baselines.

Refresh this inventory after source data or weather inputs change with `python monitoring/ml/data_feasibility.py`.
