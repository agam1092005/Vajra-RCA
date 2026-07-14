"""Convert pipeline objects (which may carry numpy/pandas scalars) to plain JSON."""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, np.ndarray):
        return [to_jsonable(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(x) for x in obj]
    # pandas NA / NaT and other scalars
    try:
        import pandas as pd
        if obj is pd.NaT or (not isinstance(obj, (list, dict)) and pd.isna(obj)):
            return None
    except (ImportError, ValueError, TypeError):
        pass
    return obj
