"""Tests for RollingHorizonILPStrategy, including its Greedy fallback."""
import json
from pathlib import Path
from unittest.mock import patch

from railroad_backend.services.auto_planner import AutoPlanConfig, _init_simulation
from railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp import (
    RollingHorizonILPStrategy,
)
from railroad_backend.services.auto_planner_strategies.rolling_ilp import WindowPlan, WindowStop
from src.simulator import Simulator
from src.utils.network_loader import load_network


def _config(tmp_path: Path) -> AutoPlanConfig:
    csv_path = tmp_path / "schedule.csv"
    csv_path.write_text("Segment Name,2025-01\nTRO-TMI,8.0\n")
    return AutoPlanConfig(
        csv_path=csv_path,
        start_station="TRO",
        facing_station="TMI",
        start_year=2025,
        end_year=2025,
        second_kld=False,
        steps=1,
    )


def test_rolling_ilp_falls_back_to_greedy_when_solver_infeasible(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = RollingHorizonILPStrategy()
    with patch(
        "railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp.solve_window",
        return_value=WindowPlan(stops=[], feasible=False),
    ):
        decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}  # same shape Greedy would return


def test_rolling_ilp_returns_a_decision_on_real_network(tmp_path):
    sim = _init_simulation(_config(tmp_path))
    strategy = RollingHorizonILPStrategy(time_limit_s=5.0)
    decision = strategy.decide_next_action(sim)
    assert decision.kind in {"move", "wait", "turn", "none"}


def _chain_network(tmp_path: Path) -> Simulator:
    """A-B-C corridor. A-B is already due; B-C is not."""
    network_path = tmp_path / "chain_network.json"
    network_path.write_text(
        json.dumps(
            {
                "name": "Chain",
                "stations": [
                    {"name": "A", "can_turn": False},
                    {"name": "B", "can_turn": False},
                    {"name": "C", "can_turn": False},
                ],
                "segments": [
                    {
                        "name": "A-B", "start": "A", "end": "B", "length_km": 1.0,
                        "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                    {
                        "name": "B-C", "start": "B", "end": "C", "length_km": 1.0,
                        "mtbt_threshold_curva": 5.0, "mtbt_threshold_tangente": 20.0,
                        "move_time_days": 1, "maintenance_time_days": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    sim = Simulator(load_network(network_path))
    sim.init_machine(start_station_name="A", facing_station_name="B", start_year=2025)
    a_b = next(s for s in sim.segments if s.name == "A-B")
    a_b.load_curva = 10.0  # already past mtbt_threshold_curva=5.0
    return sim


def test_rolling_ilp_maintains_a_due_segment_it_passes_through_even_when_not_the_modeled_target(tmp_path):
    """Regression test: the machine must service an already-due segment the
    instant it travels across it, even if the CP-SAT model's chosen "first
    stop" for this window happens to be a different, further-away candidate
    reached via the same physical hop. Reproduced on the real network: the
    machine crossed ZKE-ZBL-C (loaded at ~8x its threshold) with a plain
    "move" instead of maintaining it, because the modeled target for that
    replan was a segment further down the corridor (2026-08-11 diagnostic)."""
    sim = _chain_network(tmp_path)
    strategy = RollingHorizonILPStrategy(time_limit_s=5.0)

    # Force the model to target the *further* candidate (B-C) even though
    # the very next real hop (A->B) crosses the already-due A-B segment.
    with patch(
        "railroad_backend.services.auto_planner_strategies.rolling_horizon_ilp.solve_window",
        return_value=WindowPlan(
            stops=[WindowStop(station_name="C", segment_name="B-C", arrival_day=2)],
            feasible=True,
        ),
    ):
        decision = strategy.decide_next_action(sim)

    assert decision.kind == "move"
    assert any(seg.name == "A-B" for seg in decision.segments)
    assert decision.action in {"maintain", "maintain_curves"}, (
        f"expected A-B (already due) to be maintained while passing through, got action={decision.action!r}"
    )
