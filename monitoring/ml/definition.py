"""Shared, user-facing definition of DengueWatch's hotspot forecast."""

FORECAST_HORIZON = "one calendar month ahead"
FORECAST_GEOGRAPHIC_UNIT = "each of Iligan City's 44 barangays"
FORECAST_TARGET = "recorded dengue case count in the next calendar month"

# Observed hotspot label used for evaluation: at least two actual cases in a month.
OBSERVED_HOTSPOT_THRESHOLD = 2

# Review flag for predicted counts. Selected against chronological validation
# data while retaining minimum precision/recall safeguards; not an official
# DOH outbreak definition. Keep the observed evaluation threshold separate.
PREDICTED_HOTSPOT_THRESHOLD = 3.0

# Historical dashboard risk bands keep their existing monthly case-volume boundary.
RISK_LEVEL_MODERATE_THRESHOLD = 6

# Exploratory review-only cutoff. It produced high precision but very low
# recall on a previously inspected validation period; it is not operational.
EXPLORATORY_REVIEW_THRESHOLD = 10

PREDICTION_DEFINITION = (
    "At a forecast issue cutoff in calendar month t, DengueWatch uses the dengue "
    "case and weather information available by that cutoff, including the "
    "two latest complete monthly case counts, to estimate the "
    "recorded dengue case count in calendar month t+1 for each of "
    "Iligan City's 44 barangays (one barangay-month prediction, one calendar "
    "month ahead). The target is the observed case-record count in the following "
    "month, not a risk label calculated from the input month's count. A barangay "
    "is flagged for planning review if its estimated t+1 count is at least 3; "
    "evaluation labels an observed hotspot at 2 or more actual cases. These are "
    "internal project thresholds, not official DOH outbreak definitions. If month "
    "t is still underway, confirmed month-to-date cases are used and the estimate "
    "is provisional. Forecasts support planning and "
    "require health-personnel review before operational action."
)
