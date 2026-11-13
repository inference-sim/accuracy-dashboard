"""The facts the dashboard supplies to the stand-in evaluator, through the public functions."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stand_in_facts as sif  # noqa: E402


@pytest.mark.parametrize("tp,gpn,nodes", [(1, 8, 1), (8, 8, 1), (4, 8, 1), (9, 8, 2), (16, 8, 2), (16, 4, 4), (32, 8, 4), (8, 4, 2)])
def test_the_tp_group_spans_the_nodes_its_gpus_need(tp, gpn, nodes):
    assert sif.facts("x", tp=tp, gpus_per_node=gpn)["tp_group_nodes"] == nodes


@pytest.mark.parametrize("tp,gpn", [(None, 8), (8, None), (0, 8), (8, 0), (True, 8), ("8", 8)])
def test_a_group_the_dashboard_cannot_size_gives_no_fact(tp, gpn):
    assert "tp_group_nodes" not in sif.facts("x", tp=tp, gpus_per_node=gpn)


def test_the_value_is_trimmed_and_lowercased_and_a_missing_one_is_absent():
    assert sif.facts("  MNNVL ")["value"] == "mnnvl" and sif.facts(1024)["value"] == "1024"
    assert "value" not in sif.facts(None)


def test_the_capability_is_the_catalogs_and_absent_where_it_states_none(tmp_path):
    (tmp_path / "hardware").mkdir()
    (tmp_path / "hardware" / "b200.yaml").write_text('ComputeCapability: "10.0"\n')
    (tmp_path / "hardware" / "odd.yaml").write_text("Name: x\n")
    assert sif.compute_capability(tmp_path, "b200") == "10.0"
    assert sif.compute_capability(tmp_path, "odd") is None and sif.compute_capability(tmp_path, "nope") is None
    assert sif.facts("auto", capability=sif.compute_capability(tmp_path, "b200"))["compute_capability"] == "10.0"
    assert "compute_capability" not in sif.facts("auto", capability=sif.compute_capability(tmp_path, "odd"))


def test_a_part_with_no_catalog_entry_is_sized_by_its_launch_and_does_not_stop_the_run(tmp_path):
    """An AMD part has no hardware entry: the packaging read fails with the command's error, and the stand-in facts fall back
    to the launch configuration's node size (the point is refused for its part elsewhere); the run goes on."""
    import types
    import blis_commands as bc
    import score

    class NoEntry:
        root = tmp_path
        def packaging(self, chip):
            raise bc.CommandError(f"blis catalog resolve --chip {chip} reports no packaging")
    facts_of = score._facts_of(types.SimpleNamespace(catalog_obj=NoEntry()), "mi355x", 8)
    assert facts_of("auto", {"tensor_parallel_size": types.SimpleNamespace(value=16)})["tp_group_nodes"] == 2
