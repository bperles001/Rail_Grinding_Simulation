"""One-off migration: converte o plano salvo 'Plano - Nós' de action/
maintain_segments para segment_actions (Manual Route, 2026-08-07) e remove
os planos incompativeis com a rede atual ('Original', '2026-Original').

Uso: python scripts/migrate_plano_nos_segment_actions.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PLANS_PATH = Path(__file__).resolve().parents[1] / "data" / "saved_plans.json"
KEEP_PLAN_NAME = "Plano - Nós"

_ACTION_TOKEN = {"maintain": "completa", "m": "completa", "maintain_curves": "curva"}


def convert_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um passo do formato antigo (action/maintain_segments) pro
    novo (segment_actions). Passos turn/wait voltam inalterados."""
    if step.get("mode") != "move":
        return dict(step)

    segment_names = step.get("segments")
    if segment_names is None and "segment" in step:
        segment_names = [step["segment"]]
    segment_names = list(segment_names or [])

    action = step.get("action", "move")
    token = _ACTION_TOKEN.get(action, "none")
    maintain_segments = step.get("maintain_segments")

    if token == "none":
        segment_actions = {name: "none" for name in segment_names}
    elif maintain_segments is not None:
        segment_actions = {
            name: (token if name in maintain_segments else "none")
            for name in segment_names
        }
    else:
        segment_actions = {name: token for name in segment_names}

    new_step = {k: v for k, v in step.items() if k not in ("action", "maintain_segments")}
    new_step["segment_actions"] = segment_actions
    return new_step


def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica convert_step só no plano compativel com a rede atual; descarta
    os demais planos manuais. A secao 'auto' nao e tocada."""
    manual = data.get("manual", {})
    kept = manual.get(KEEP_PLAN_NAME)
    new_manual = {}
    if kept is not None:
        new_manual[KEEP_PLAN_NAME] = [convert_step(step) for step in kept]
    return {"manual": new_manual, "auto": data.get("auto", {})}


def main() -> None:
    data = json.loads(PLANS_PATH.read_text(encoding="utf-8"))
    migrated = migrate(data)
    PLANS_PATH.write_text(json.dumps(migrated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Migrado: {list(migrated['manual'].keys())}")


if __name__ == "__main__":
    main()
