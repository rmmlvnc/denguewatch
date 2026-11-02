# DengueWatch model training and validation report

## Current validation-selected deployment update (2026-10-25)

The active predicted-count review cutoff is **3 cases**. A barangay is flagged when the model predicts at least 3 cases for the next month. The actual-hotspot label remains **2 or more recorded cases**. Candidate Random Forest settings were compared on the chronological validation partition at this fixed cutoff, with minimum precision and recall safeguards. The final test period was not used to select settings.

The chronological outer split used **3,344 development records (75.25%)** and **1,100 final-period test records (24.75%)**, keeping all barangays from each month together. The development data was further split into training and validation data for model selection. Validation reference months were **2022-11 to 2024-05** (836 barangay-month rows; targets through 2024-06). The selected model was Random Forest with `criterion=squared_error`, 400 trees, `min_samples_leaf=5`, `max_features=0.8`, and maximum depth 12. At the 3-case cutoff, validation accuracy was **76.56%**, hotspot precision **91.94%**, recall **66.47%**, and F1 **77.16%**. Confusion counts were TN=309, FP=29, FN=167, and TP=331.

These are validation results used during model selection, not independent test results.

### Retrospective final-period result

At the 3-case predicted-count cutoff, the current model classified **860 of 1,100** records correctly on the existing later-period holdout: accuracy **78.18%**, hotspot precision **83.86%**, recall **70.66%**, and F1 **76.70%**. Confusion counts were TN=465, FP=76, FN=164, and TP=395. Case-count MAE was **1.8853**, RMSE **2.8675**, and R² **0.5929**. Test targets covered **2024-07 to 2026-07**. Actual hotspots remain defined as 2 or more recorded cases.

This holdout was inspected in earlier project iterations, so this is a retrospective score, not independent confirmation. Evaluate future performance on newer, untouched months.

> **Superseded note (2026-10-20):** The following historical analyses used older datasets and thresholds, including a six-case observed-hotspot rule and a seven-case review cutoff. They are retained as project history only. Use the 2026-10-25 update above and the active deployment metadata in `monitoring/ml/model_metrics.json` for the current model configuration.

## Study-aligned prediction definition

At a forecast issue cutoff during calendar month *t*, DengueWatch uses dengue case and weather information available by that cutoff to estimate the recorded dengue case count in month *t+1* for each of Iligan City’s 44 barangays. The prediction unit is one barangay-month and the horizon is one calendar month. The target is the observed case count in the following month, not a risk label calculated from the input month’s count. A barangay is flagged for planning review when its estimated *t+1* count is at least seven; evaluation defines an observed hotspot as six or more actual cases. These are internal project thresholds, not official DOH outbreak definitions. If month *t* is still underway, confirmed month-to-date cases are used and the estimate is provisional. Forecasts support planning and require health-personnel review before operational action.

The modeling unit is one barangay-month. Inputs are historical case counts and lags, rainfall, mean temperature, relative humidity (current issue month and the prior month), calendar seasonality, barangay identity, and boundary-derived latitude/longitude. Blood type is kept for aggregate historical descriptions and is excluded from model inputs because it is not part of the study’s prediction framework. GIS boundaries are used to map forecasts; the model uses the representative coordinates and barangay identifier as location features.

## Source data

The active consolidated line list contains **14,174 records** from 2018-01 through 2026-07. It combines the CHO-verified 2018 and 2019 datasets with the CHO-verified 2020-2026 line list, as confirmed by the project team. The 2018 and 2019 files contain 3,690 rows total: 1,792 for 2018 and 1,898 for 2019.

Every source row is retained. The combined audit flags 174 exact-repeat extra rows, 810 rows with one or more blank requested fields, 74 rows with no official Iligan barangay match, and 34 Year/admission-date mismatches. Of the new historical rows, 2 exact repeats in 2018 and 8 in 2019 are flagged; 9 and 10 rows respectively have unmatched barangay names. Unmatched records remain in line-list totals but are not assigned to official barangay map or model rows. No case identifier, report-received date, or documented case-definition version is present.

## Training and validation procedure

1. Consolidate the CHO-verified case source and aggregate valid admission-date and official-barangay records into one row per barangay-month, including no-case months according to the recorded completeness confirmation.
2. Join monthly case aggregates with Open-Meteo weather data and boundary-derived GIS coordinates. Keep unavailable weather blank; do not fabricate values.
3. Create next-month count targets and lag/rolling features using only information available by each forecast issue cutoff. The next-month target and later observations are not predictors. Learned preprocessing (median imputation and barangay encoding) is fitted on training data, then applied to validation/test data without refitting on those rows.
4. Split chronologically by whole reference calendar month, keeping all barangays from one month in the same partition. Tune candidate settings using training and validation periods only.
5. The original evaluation used a later chronological holdout and compared count forecasts with persistence, seasonal-naive, and trailing-three-month baselines. The holdout scores and predictions have since been inspected in prior project iterations, so this period is not an untouched independent test for new changes.
6. Threshold and feature experiments below use the validation period only. They are exploratory because validation was previously used for model selection. A future independent performance claim requires a new later reporting period or a newly preplanned holdout.

| Partition | Reference months | Barangay-month rows | Purpose |
|---|---|---:|---|
| Training | 2018-02 to 2023-01 | 2640 | Fit candidates and preprocessing |
| Validation | 2023-02 to 2024-09 | 880 | Select settings |
| Later-period holdout (previously inspected) | 2024-10 to 2026-06 | 924 | Historical evaluation; not independent confirmation for new changes |

The previously evaluated holdout forecasts target months 2024-11 through 2026-07. Selected estimator: RandomForestRegressor with `n_estimators=300`, `min_samples_leaf=2`, and `max_features=0.8`.

## Additional rolling validation requested by the step-by-step review

The training guidance recommended checking several chronological validation periods instead of selecting settings from one window. An exploratory expanding-window comparison was added. It stops the source at October 2024, the target month needed for the last development reference month. No later-period holdout rows were used for feature engineering, fitting, tuning, or scoring. Four non-overlapping eight-month validation windows were used; each window kept all barangays for a reference month together. Each fold's imputer and barangay encoder were fitted on that fold's training rows only.

| Fold | Training reference months | Validation reference months | Rows |
|---|---|---|---:|
| 1 | 2018-02 to 2022-01 | 2022-02 to 2022-09 | 352 |
| 2 | 2018-02 to 2022-09 | 2022-10 to 2023-05 | 352 |
| 3 | 2018-02 to 2023-05 | 2023-06 to 2024-01 | 352 |
| 4 | 2018-02 to 2024-01 | 2024-02 to 2024-09 | 352 |

Among tested model candidates, the lowest pooled validation MAE was from a Random Forest with 500 trees, `max_depth=10`, `min_samples_leaf=4`, and `max_features=0.8` after excluding weather features. The shared model-pipeline builder was corrected to pass `max_depth` when a candidate specifies it; before this correction, depth candidates were silently equivalent to unrestricted trees. The weather-free option is an exploratory feature ablation, not a deployed configuration.

| Candidate or baseline | MAE | RMSE | R² | Hotspot precision | Hotspot recall | Hotspot F1 |
|---|---:|---:|---:|---:|---:|---:|
| Current Random Forest (300 trees, leaf 2, max_features 0.8) | 2.1622 | 3.6238 | 0.4912 | 68.25% | 56.67% | 61.92% |
| Conservative Random Forest (500 trees, depth 10, leaf 4, max_features 0.8) | 2.1207 | 3.5819 | 0.5029 | 69.37% | 56.97% | 62.56% |
| Persistence | 2.2351 | 3.8028 | 0.4397 | 67.08% | 66.06% | 66.56% |
| Seasonal naive, same month last year | 2.5291 | 4.3001 | 0.2836 | 58.12% | 41.21% | 48.23% |
| Trailing three-month mean | **2.0346** | **3.4704** | **0.5334** | **71.18%** | **62.12%** | **66.34%** |
| Conservative Random Forest without weather | 2.0849 | 3.5399 | 0.5145 | 71.32% | 55.76% | 62.59% |

The conservative candidate improved over the current Random Forest on the pooled rolling-validation scores. The trailing-three-month mean remained better on both count errors, recall, and F1, although the conservative Random Forest without weather had a nearly equal precision (71.32% versus 71.18%). The weather-free candidate's recall and F1 were lower. A broader-feature Random Forest had the best Random Forest hotspot F1 (62.76%) and recall (58.48%), but remained below the trailing-three-month baseline on those measures. No candidate was better overall, so do not replace the deployed model or claim a general improvement. The current model's later-period holdout results remain unchanged. This rolling analysis is exploratory because the development dates have informed prior decisions. A newly collected future period is still needed for independent confirmation.

### Poisson regression comparison

Poisson regression was added as an alternative count model and evaluated on exactly the same four expanding chronological folds and the same 1,408 validation rows. Each fold fitted its own imputer, numeric scaler, and barangay encoder on training rows only. Alpha is the regularization strength. The observed hotspot threshold remained six cases; no definition or evaluation period was changed.

| Model | MAE (cases) | RMSE (cases) | Hotspot precision | Hotspot recall | Hotspot F1 |
|---|---:|---:|---:|---:|---:|
| Poisson regression, alpha 0.1 | 2.6884 | 8.2632 | 75.00% | 50.00% | 60.00% |
| Poisson regression, alpha 1.0 | 2.8113 | 9.4964 | 73.04% | 45.15% | 55.81% |
| Poisson regression, alpha 10.0 | 2.6211 | 6.0185 | 74.07% | 36.36% | 48.78% |
| Trailing three-month mean baseline | **2.0346** | **3.4704** | 71.18% | **62.12%** | **66.34%** |

Poisson regression did not outperform the trailing-three-month baseline on count errors or hotspot F1/recall. Its higher precision at these settings came with lower recall and substantially larger RMSE. The results do not support replacing Random Forest with Poisson regression. They also do not support claiming an 85% precision/recall/F1 target has been reached. The 85% values are development aspirations only; any future threshold must be selected using validation data and then assessed on a newly collected, untouched future period.

The procedure's sample periods (for example, training through 2023, validation in 2024, and testing in 2025) are examples, not the dates used by this project. The project's actual dates are shown in the split table above. The current target remains next-month counts; weekly rows would require a newly defined weekly horizon and separate completeness checks.

Candidate preprocessing and estimators are fitted without later-period rows. The selected pipeline used for the historical holdout scoring is fitted on earlier training and validation months. All barangays from a given reference month are kept together in every split. Because this holdout has been inspected in prior iterations, do not describe new threshold or feature results on this period as blind or untouched.

## Updated results

### Next-month case-count forecast

| Previously evaluated holdout metric | Random Forest | Persistence |
|---|---:|---:|
| MAE (lower is better) | 1.8483 | 1.7078 |
| RMSE (lower is better) | 2.7051 | 2.8634 |

Random Forest has lower RMSE but higher MAE than persistence, so it does not consistently beat the simple count baseline.

### Six-case hotspot classification

Classification precision is **60.34%**, recall is **79.41%**, and F1 is **68.57%** on 924 previously evaluated holdout barangay-months. These labels are derived by applying the six-case threshold to the model’s next-month count estimates.

| Actual / predicted | Not hotspot | Hotspot |
|---|---:|---:|
| Not hotspot | 717 true negatives | 71 false alarms |
| Hotspot | 28 missed hotspots | 108 detected hotspots |

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| Not hotspot (<6 cases) | 96.24% | 90.99% | 93.54% | 788 |
| Hotspot (≥6 cases) | 60.34% | 79.41% | 68.57% | 136 |

Precision formula: TP / (TP + FP) = 108 / (108 + 71) = 60.34%.

| Method | Precision | Recall | F1 |
|---|---:|---:|---:|
| Random Forest | 60.34% | 79.41% | 68.57% |
| Persistence | 58.22% | 62.50% | 60.28% |
| Seasonal Naive Same Month Last Year | 40.00% | 77.94% | 52.87% |
| Trailing 3 Month Mean | 60.00% | 70.59% | 64.86% |

The hotspot-class precision on the previously inspected holdout is below the 80% aspiration and must be reported as measured. The model’s hotspot F1 is slightly higher than the trailing-three-month baseline overall, but it does not beat all baselines in every holdout block, and its count MAE is worse than persistence. Do not tune the holdout to force an 80% result.

## Exploratory validation cutoff and case-momentum analysis

The current hotspot definition remains **six or more observed cases** in a barangay-month. A stricter predicted-count cutoff was compared against that fixed observed definition on the validation partition (2023-02 to 2024-09 reference months; target months 2023-03 to 2024-10). The model is a Random Forest regressor; cutoff values below are predicted case counts, not probabilities. This analysis does not change the deployed six-case rule.

| Feature set | Predicted cutoff | Precision | Recall | Flagged barangay-months | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| Current features | ≥6 | 77.49% | 57.14% | 191 | 148 | 43 | 111 |
| Current features | ≥8 | 80.43% | 28.57% | 92 | 74 | 18 | 185 |
| Current features | ≥9 | 84.13% | 20.46% | 63 | 53 | 10 | 206 |
| Current features | ≥10 | **85.42%** | **15.83%** | **48** | **41** | **7** | **218** |
| Current features | ≥12 | 100.00% | 8.11% | 21 | 21 | 0 | 238 |
| Current features | ≥15 | 100.00% | 4.63% | 12 | 12 | 0 | 247 |
| With case momentum | ≥6 | 76.96% | 56.76% | 191 | 147 | 44 | 112 |
| With case momentum | ≥10 | 85.11% | 15.44% | 47 | 40 | 7 | 219 |
| With case momentum | ≥12 | 95.24% | 7.72% | 21 | 20 | 1 | 239 |
| With case momentum | ≥15 | 100.00% | 4.25% | 11 | 11 | 0 | 248 |

At predicted cutoff 10, validation precision exceeds 85%, but recall is only 15.83%: 218 of 259 observed hotspot barangay-months are missed. Thus the high precision comes with sharply reduced coverage and is not evidence of an 85% precision rate on future data. Raising the cutoff to 12 or 15 produces 100% precision on this validation set while detecting only 21 or 12 of 259 observed hotspots, respectively. Do not present those values without their recall and flag counts.

The momentum feature is `cases_lag_1 - cases_lag_2`, computed from earlier monthly counts. It did not improve validation count MAE/RMSE (2.4103 / 4.1457 with momentum versus 2.4065 / 4.1355 with current features) and did not improve threshold-10 precision/recall. It remains excluded from deployed features. Validation had already been used for model selection, so all these comparisons are exploratory; no cutoff is promoted as a validated operational setting.

## Exploratory regression-criterion comparison

The validation-only experiment compared the current squared-error Random Forest with the suggested absolute-error criterion and smaller `max_features` values. Each preprocessing pipeline was fitted on training rows only. Persistence predicts the next month using the current month's observed case count.

| Candidate | MAE (cases) | RMSE (cases) |
|---|---:|---:|
| Persistence baseline | 2.6614 | 4.4734 |
| Current Random Forest (`squared_error`, 300 trees, leaf 2, `max_features=0.8`) | **2.4065** | **4.1355** |
| Absolute error (200 trees, leaf 3, `max_features=0.8`) | 2.4174 | 4.1595 |
| Absolute error (200 trees, leaf 3, `max_features=0.6`) | 2.4240 | 4.1711 |
| Absolute error (200 trees, leaf 3, `max_features=0.5`) | 2.4070 | 4.1615 |

On this validation period, the current Random Forest's MAE was 9.58% lower and RMSE was 7.55% lower than persistence. All tested absolute-error settings also beat persistence on both validation metrics, but none beat the current Random Forest. Therefore, the experiment did not support replacing the current deployed estimator. Since this validation period was previously used for model selection and repeated experiments, these values are exploratory and do not establish improved future or holdout performance. The previously evaluated holdout metrics remain MAE 1.8483 and RMSE 2.7051 for Random Forest, versus 1.7078 and 2.8634 for persistence.

## Limitations and deployment status

Open-Meteo weather is cached for 2020 onward. All weather data for 2018-2019 are missing in the local cache and imputed by the training pipeline, so those years add case history but no observed weather variation. The cache covers eight distinct returned grid cells for 44 barangays; adjacent barangays can share grid-cell estimates. The monthly completeness assumption comes from the user and has no separate CHO zero-report register. Duplicate rows remain flagged rather than automatically deleted because there is no stable case identifier.

`deployment_status` remains **planning_support_only**. Forecasts are planning signals for CHO/health-worker review; they are not confirmed cases, outbreak declarations, or automatic public alerts. Health personnel must review forecasts and confirm cases before operational action.

## Artifacts and regeneration

- Active line list: `datasets/WILBUR_DSO_dengue_2018_2026_authoritative.csv`
- Model input: `datasets/integrated_monthly.csv`
- Metrics: `monitoring/ml/model_metrics.json`
- Exploratory validation analysis: `monitoring/ml/validation_threshold_analysis.json`
- Validation-only analysis script: `monitoring/ml/exploratory_validation.py`
- Regression-setting experiment: `monitoring/ml/exploratory_regression_tuning.py`
- Regression experiment results: `monitoring/ml/regression_tuning_validation.json`
- Trained pipeline: `monitoring/ml/random_forest.pkl`
- Aggregate data inventory: `docs/data_feasibility_inventory.md`

```powershell
python monitoring/ml/exploratory_validation.py
python monitoring/ml/exploratory_regression_tuning.py
```

These commands regenerate validation-only experiments without loading or scoring the previously evaluated holdout. Running `train_model.py` also regenerates holdout metrics and is not needed to reproduce these exploratory analyses.
