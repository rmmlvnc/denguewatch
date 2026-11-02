"""Generate next-month barangay forecasts from a trained DengueWatch model."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:
    from .train_model import FEATURES
    from .definition import RISK_LEVEL_MODERATE_THRESHOLD
except ImportError:  # Direct script execution
    from train_model import FEATURES
    from definition import RISK_LEVEL_MODERATE_THRESHOLD


def risk_level(predicted_cases: float) -> str:
    if predicted_cases >= 101:
        return 'Critical'
    if predicted_cases >= 51:
        return 'High'
    if predicted_cases >= RISK_LEVEL_MODERATE_THRESHOLD:
        return 'Moderate'
    return 'Low'


def predict(model_path: Path, input_path: Path) -> list[dict]:
    artifact = joblib.load(model_path)
    data = pd.read_csv(input_path)
    missing = [column for column in FEATURES if column not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    values = np.maximum(0, artifact['pipeline'].predict(data[FEATURES]))
    results = []
    for barangay, value in zip(data['barangay'], values):
        rounded = round(float(value), 2)
        results.append({
            'barangay': str(barangay),
            'predicted_next_month_cases': rounded,
            'risk_level': risk_level(rounded),
        })
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input_csv', type=Path)
    parser.add_argument('--model', type=Path, default=Path(__file__).with_name('random_forest.pkl'))
    args = parser.parse_args()
    print(json.dumps(predict(args.model, args.input_csv), indent=2))
