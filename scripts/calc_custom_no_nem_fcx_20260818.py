from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scripts" / "calc_custom_no_nem_fcx_20260819.py"
spec = importlib.util.spec_from_file_location("custom_no_nem_fcx_base", BASE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.TARGET_DATE = pd.Timestamp("2026-08-18")
mod.OUT = ROOT / "analysis" / "custom_no_nem_fcx_20260818.json"
mod.main()
