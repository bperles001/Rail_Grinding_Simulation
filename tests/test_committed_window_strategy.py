"""Tests for CommittedWindowStrategy: the shared hysteresis/commitment layer
that fixes rolling-horizon "nervousness" (oscillation between near-tied
replans)."""
import json
from pathlib import Path
from typing import List

from railroad_backend.services.auto_planner_strategies.committed_window import (
    CommittedWindowStrategy,
)
from railroad_backend.services.auto_planner_strategies.horizon import DueCandidate
from railroad_backend.services.auto_planner_strategies.rolling_ilp import WindowPlan, WindowStop
from src.simulator import Simulator
from src.utils.network_loader import load_network


def _write_chain_network(path: Path) -> None:
    """A-B-C corridor, both segments start already due."""
    path.write_text(
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


def _chain_sim(tmp_path: Path, *, both_due: bool = True) -> Simulator:
    network_path = tmp_path / "chain.json"
    _write_chain_network(network_path)
    sim = Simulator(load_network(network_path))
    sim.init_machine(start_station_name="A", facing_station_name="B", start_year=2025)
    a_b = next(s for s in sim.segments if s.name == "A-B")
    a_b.load_curva = 10.0  # already past mtbt_threshold_curva=5.0
    if both_due:
        b_c = next(s for s in sim.segments if s.name == "B-C")
        b_c.load_curva = 10.0
    return sim


class _RecordingStrategy(CommittedWindowStrategy):
    """Test double: returns pre-scripted plans in order, records every call."""

    def __init__(self, scripted_plans: List[WindowPlan], **kwargs) -> None:
        super().__init__(**kwargs)
        self._scripted_plans = list(scripted_plans)
        self.solve_calls = 0

    def _solve_window(self, candidates, graph, start_station):
        self.solve_calls += 1
        return self._scripted_plans[self.solve_calls - 1]


def test_cached_plan_is_reused_without_replanning_while_still_valid(tmp_path):
    sim = _chain_sim(tmp_path, both_due=True)
    plan = WindowPlan(
        stops=[
            WindowStop(station_name="B", segment_name="A-B", arrival_day=1),
            WindowStop(station_name="C", segment_name="B-C", arrival_day=2),
        ],
        feasible=True,
    )
    strategy = _RecordingStrategy([plan])

    strategy.decide_next_action(sim)  # first call: solves, executes the A-B hop, pops it
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)  # second call: B-C still cached and still due -- no new solve
    assert strategy.solve_calls == 1


def test_replans_once_the_cached_plan_is_exhausted(tmp_path):
    sim = _chain_sim(tmp_path, both_due=False)
    first_plan = WindowPlan(stops=[WindowStop(station_name="B", segment_name="A-B", arrival_day=1)], feasible=True)
    second_plan = WindowPlan(stops=[], feasible=True)
    strategy = _RecordingStrategy([first_plan, second_plan])

    strategy.decide_next_action(sim)  # pops the only stop -- cache now empty
    assert strategy.solve_calls == 1

    strategy.decide_next_action(sim)  # cache empty -- must replan
    assert strategy.solve_calls == 2


def test_replans_when_a_new_already_due_candidate_appears_outside_the_cached_plan(tmp_path):
    sim = _chain_sim(tmp_path, both_due=False)  # only A-B due at first
    # Plan with 2 stops so it is not exhausted by the first real hop.
    first_plan = WindowPlan(
        stops=[
            WindowStop(station_name="B", segment_name="A-B", arrival_day=1),
            WindowStop(station_name="C", segment_name="Z-not-really-due-yet", arrival_day=5),
        ],
        feasible=True,
    )
    second_plan = WindowPlan(stops=[], feasible=True)
    strategy = _RecordingStrategy([first_plan, second_plan])

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 1

    # B-C becomes due *now*, but it was never part of the cached plan's candidate set.
    b_c = next(s for s in sim.segments if s.name == "B-C")
    b_c.load_curva = 10.0

    strategy.decide_next_action(sim)
    assert strategy.solve_calls == 2, "a newly-due candidate outside the cached plan must force a replan"
