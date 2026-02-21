"""Select tradable symbols (USDT-M) and save report.

Usage:
  python tools/select_universe.py

Env:
  EXCHANGE=binance|bybit|mexc
  (API keys optional for public endpoints)

Outputs:
  data/runtime/universe_selection.json
"""

from __future__ import annotations

import json
from pathlib import Path

from trade_ai.infrastructure.market.exchange_factory import make_exchange_from_env
from trade_ai.infrastructure.market.universe_selector_v1 import UniverseSelectorV1, universe_config_from_env
from trade_ai.infrastructure.market.universe_selector_v2 import UniverseSelectorV2, universe_config_v2_from_env
from trade_ai.infrastructure.market.universe_selector_v3 import UniverseSelectorV3, universe_config_v3_from_env


def main() -> None:
    ex = make_exchange_from_env()
    os_env = __import__("os").environ
    ver = str(os_env.get("UNIVERSE_SELECTOR_VERSION", "2") or "2").strip().lower()
    if ver in ("1", "v1"):
        cfg = universe_config_from_env(os_env)
        report = UniverseSelectorV1(cfg).select(ex)
    elif ver in ("2", "v2"):
        cfg2 = universe_config_v2_from_env(os_env)
        report = UniverseSelectorV2(cfg2).select(ex)
    else:
        cfg3 = universe_config_v3_from_env(os_env)
        report = UniverseSelectorV3(cfg3).select(ex)

    Path("data/runtime").mkdir(parents=True, exist_ok=True)
    out_path = Path("data/runtime/universe_selection.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    sel = [x.get("symbol") for x in (report.get("selected") or []) if isinstance(x, dict)]
    print("Selected symbols:")
    for s in sel:
        print(" -", s)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
