import math

import numpy as np


def _clean(x):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), 4)


def regression_metrics(y, yhat, mape_min: float = 10.0) -> dict:
    """MAE, RMSE, R2 and MAPE. MAPE is only computed on targets >= mape_min (percentages explode near zero)."""
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    m = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[m], yhat[m]
    if len(y) == 0:
        return {"n": 0, "mae": None, "rmse": None, "r2": None, "mape_pct": None}
    err = yhat - y
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    big = y >= mape_min
    return {"n": int(len(y)), "mae": _clean(np.mean(np.abs(err))), "rmse": _clean(math.sqrt(np.mean(err ** 2))),
            "r2": _clean(1 - float(np.sum(err ** 2)) / ss_tot) if ss_tot > 0 else None,
            "mape_pct": _clean(np.mean(np.abs(err[big]) / y[big]) * 100) if big.sum() >= 10 else None}
