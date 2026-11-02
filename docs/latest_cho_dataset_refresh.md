# Latest CHO dataset refresh and model re-evaluation

**Updated 2026-10-20.** This note supersedes earlier model scores in this repository for the active CHO line list. The historical later-period evaluation was already examined in earlier project work, so the refreshed score is a re-evaluation, not a new untouched test.

## Active dataset and handling

- Main file: `datasets/WILBUR_DSO_dengue_2018_2026_authoritative.csv`.
- Submitted source: `DENGUE DATASETS 2018_2026 - CHO Dengue Records.csv`, confirmed by the project team as CHO-verified.
- Source-selection rule: this uploaded file is the only historical dengue line list used by case aggregation, hotspot maps, model-data building, and training. The other CSV/XLSX files remain archived and are not fallbacks or additional inputs. CHO-confirmed reports submitted through the live application remain a separate operational workflow.
- Source rows: 14,118, retained in the active line list. The uploaded original and previous active source are archived under `datasets/cho_source_archive/` and `datasets/source_backups/`.
- Valid admission dates: 14,116, spanning 2018-01-01 to 2026-07-31. Two dates are blank or invalid.
- Admission `YEAR` disagrees with the admission date in 36 rows. The submitted value is preserved as `SourceYear`; the application `Year` uses the valid admission date for annual map totals. Each mismatch is flagged.
- 101 extra exact-repeat rows are retained and flagged. The source has no stable case ID, so no records were automatically deleted.
- Eight records name a city/municipality outside Iligan. These remain in the source file but are excluded from Iligan maps and model aggregation. The `Tomas Cabili` alias maps to official `Tomas L. Cabili`; 31 other rows have no official Iligan barangay match and are excluded from barangay aggregation.
- One non-empty otherwise-unlabelled source column is preserved as `SourceExtraColumn`.
- The source provides no received/entered date or case-definition version. CHO review is still needed to resolve record-level duplicate concerns and confirm governance details.

## Monthly model rows and split

The project keeps its monthly design: 44 official barangays, one row per barangay-month, 2018-01 to 2026-07 (4,532 rows). After lag and target requirements, 4,444 rows are usable. The chronological outer split is approximately 80/20 by whole reference month: **3,564 outer-training rows (80.2%)** from 2018-02 to 2024-10 and **880 test rows (19.8%)** from 2024-11 to 2026-06 (target months 2024-12 to 2026-07). Within the earlier outer-training period, 2,640 rows (2018-02 to 2023-01) fit candidate models and preprocessing; 924 rows (2023-02 to 2024-10) are used for validation and model selection. All barangays from a month stay together, and the test period is not used for tuning. Because 44 barangay rows are grouped by month, the closest whole-month split is 80.2%/19.8%, rather than exactly 80.0%/20.0%.

The trained estimator is a `RandomForestRegressor` with 500 trees, `min_samples_leaf=5`, and `max_features=1.0`. It predicts next-month case counts. The current conservative planning-review flag is at least 7 predicted cases. Evaluation defines an observed hotspot as at least 6 actual cases. Both are internal project thresholds, not official DOH outbreak definitions.

## Refreshed historical evaluation

| Measure | Updated result |
|---|---:|
| MAE | 1.7593 cases |
| RMSE | 2.5602 cases |
| R² | 0.5434 |
| Hotspot precision (observed ≥6, predicted ≥7) | 67.41% |
| Hotspot recall | 68.94% |
| Hotspot F1 | 68.16% |

Confusion counts: TP 91, FP 44, FN 41, TN 704, over 880 barangay-month test rows. Precision is `TP / (TP + FP) = 91 / (91 + 44) = 67.41%`. At the previous predicted-count cutoff of 6, the same test period measured 63.03% precision, 78.79% recall, and 70.03% F1. The new cutoff reduced recall and did **not** reach 85% precision on the later-period test.

At the selected predicted-count cutoff of 7, validation precision was 85.93%, recall 40.28%, and F1 54.85%, with 135 flags. The later-period score above is 67.41%. Validation informed cutoff selection, and this later-period holdout was already inspected in earlier project work, so neither should be presented as independent confirmation of future performance.

### Updated feature and precision exploration (validation only)

The feature experiment was rerun using the same 924-row chronological validation partition as the current training workflow. The final-test data was not loaded or scored. With the current Random Forest settings (500 trees, `min_samples_leaf=5`, `max_features=1.0`), adding case momentum changed validation MAE from 2.4077 to 2.4063 and RMSE from 4.0806 to 4.0829; this is a very small trade-off, not a demonstrated robust gain. Excluding weather features worsened count MAE/RMSE to 2.4385/4.1118.

At the observed hotspot definition of at least 6 cases, a predicted-count review cutoff of 7 produced 85.93% validation precision, 40.28% recall, and 54.85% F1, flagging 135 of 924 barangay-month rows. The cutoff is now used for conservative planning review; it is not an independently validated operational alert rule and it misses more actual hotspots than the six-case prediction cutoff. Confirm its usefulness on a new future period before operational use.

| Baseline | MAE | RMSE |
|---|---:|---:|
| Persistence (carry forward latest month) | 1.5807 | 2.6468 |
| Same month last year | 3.2670 | 5.1974 |
| Trailing three-month mean | 1.5148 | 2.3391 |

Random Forest did not beat the trailing-three-month baseline on either MAE or RMSE, and it did not beat persistence on MAE. Keep forecasts as **planning support only**; do not use them as confirmed cases or automatic public alerts. The apparent trade-off between precision and recall must be evaluated together, and any new threshold/model choice requires validation-only selection and a genuinely new future evaluation period.

Weather for 2018-2019 is missing from the current cached weather source and is imputed by the training pipeline; 1,056 model rows have at least one missing weather value. The current build used cached per-barangay Open-Meteo values because live archive retrieval was unavailable. These data are reanalysis estimates, not direct barangay station measurements.

## Regeneration

```powershell
python monitoring/ml/import_cho_source.py "C:/path/to/DENGUE DATASETS 2018_2026 - CHO Dengue Records.csv"
python monitoring/ml/build_dataset.py
python monitoring/ml/data_feasibility.py
python monitoring/ml/train_model.py datasets/integrated_monthly.csv
```

The scripts keep synthetic demonstration records excluded from the active source and training data.
