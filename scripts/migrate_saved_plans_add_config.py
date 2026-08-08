"""One-off migration: envolve cada plano salvo (lista crua de passos) no
formato novo {"config": ..., "steps": [...]} (Manual Route, 2026-08-07).
Planos ja no formato novo ficam inalterados (idempotente).

Uso: python scripts/migrate_saved_plans_add_config.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PLANS_PATH = Path(__file__).resolve().parents[1] / "data" / "saved_plans.json"

DEFAULT_CONFIG = {
    "start_station": "ZTO",
    "facing_station": "ZCZ",
    "start_year": 2026,
    "end_year": 2027,
    "second_kld": True,
}


def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    manual = data.get("manual", {})
    new_manual = {}
    for name, entry in manual.items():
        if isinstance(entry, list):
            new_manual[name] = {"config": dict(DEFAULT_CONFIG), "steps": entry}
        else:
            new_manual[name] = entry
    return {"manual": new_manual, "auto": data.get("auto", {})}


def main() -> None:
    data = json.loads(PLANS_PATH.read_text(encoding="utf-8"))
    migrated = migrate(data)
    PLANS_PATH.write_text(json.dumps(migrated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Migrado: {list(migrated['manual'].keys())}")


if __name__ == "__main__":
    main()
