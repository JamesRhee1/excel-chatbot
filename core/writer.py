"""Excel writing utilities with automatic backup."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


def save_excel(df: pd.DataFrame, path: str, backup: bool = True) -> str:
    """Save a DataFrame to an Excel file, optionally backing up an existing file.

    Args:
        df: DataFrame to save.
        path: Destination file path.
        backup: If True and the file exists, copy it to path.bak_YYYYMMDD_HHMMSS first.

    Returns:
        The path where the file was saved.
    """
    dest = Path(path)

    if backup and dest.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = dest.with_name(f"{dest.name}.bak_{timestamp}")
        shutil.copy2(dest, backup_path)

    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(dest, index=False)
    return str(dest)
