"""Each side of a whole-run gate evaluation is bound to its own simulator pin, and the gate job checks it."""
import hashlib
import subprocess
from pathlib import Path

import pytest

import binding
import gate

HERE = Path(__file__).resolve().parent
SIM_A, SIM_B = "a" * 40, "b" * 40
DATA_A, DATA_B = "c" * 40, "d" * 40


def make_data(root: Path, name: str, ledger_text="units v1") -> Path:
    d = root / name
    (d / "catalog" / "ledger" / "published").mkdir(parents=True)
    (d / "catalog" / "ledger" / "ledger.yaml").write_text("kind: Ledger\n")
    (d / "catalog" / "ledger" / "published" / "fit.yaml").write_text(ledger_text)
    return d


def resolved_file(path: Path, sim, data_commit, data_dir) -> Path:
    path.write_text(f"SIM_COMMIT={sim}\nDATA_DIR={data_dir}\nDATA_COMMIT={data_commit}\nDATA_PIN={data_commit}\n"
                    f"FIELDS={data_dir}/fields.json\nVLLM_REF=v0.33.0\n")
    return path


def artifact(path: Path, sim, data_commit, ledger) -> Path:
    path.mkdir()
    (path / "sim.txt").write_text(sim + "\n")
    (path / "substrate.txt").write_text(data_commit + "\n")
    (path / "ledger.sha256").write_text(binding.ledger_digest(ledger / "catalog" / "ledger") + "\n")
    return path


def run_check(tmp, base, cand):
    return gate.main(["check-binding", "--base-resolved", str(base[0]), "--base-artifact", str(base[1]),
                      "--cand-resolved", str(cand[0]), "--cand-artifact", str(cand[1])])


@pytest.fixture
def world(tmp_path):
    base_data, cand_data = make_data(tmp_path, "base-data"), make_data(tmp_path, "cand-data")
    base = (resolved_file(tmp_path / "base.env", SIM_A, DATA_A, base_data), artifact(tmp_path / "base", SIM_A, DATA_A, base_data))
    cand = (resolved_file(tmp_path / "cand.env", SIM_B, DATA_B, cand_data), artifact(tmp_path / "cand", SIM_B, DATA_B, cand_data))
    return tmp_path, base_data, cand_data, base, cand


def test_two_different_simulators_over_one_ledger_are_accepted(world, capsys):
    tmp, _, _, base, cand = world
    assert run_check(tmp, base, cand) == 0
    capsys.readouterr()


def test_a_side_that_scored_another_simulator_than_its_commit_pins_is_refused(world, capsys):
    tmp, bd, _, base, cand = world
    (cand[1] / "sim.txt").write_text(SIM_A + "\n")                       # the candidate ran the base's simulator
    assert run_check(tmp, base, cand) == 1
    assert "candidate run scored simulator" in capsys.readouterr().out


def test_a_side_that_read_other_data_than_its_simulator_pins_is_refused(world, capsys):
    tmp, _, _, base, cand = world
    (base[1] / "substrate.txt").write_text(DATA_B + "\n")
    assert run_check(tmp, base, cand) == 1
    assert "base run read data" in capsys.readouterr().out


def test_a_side_whose_ledger_is_not_the_one_its_data_carries_is_refused(world, capsys):
    tmp, _, cand_data, base, cand = world
    (cand_data / "catalog" / "ledger" / "published" / "fit.yaml").write_text("edited after the run")
    assert run_check(tmp, base, cand) == 1
    assert "ledger is not the ledger" in capsys.readouterr().out


def test_two_sides_over_different_ledgers_are_refused_even_when_each_is_bound(tmp_path, capsys):
    bd, cd = make_data(tmp_path, "b"), make_data(tmp_path, "c", ledger_text="units v2")
    base = (resolved_file(tmp_path / "b.env", SIM_A, DATA_A, bd), artifact(tmp_path / "b-art", SIM_A, DATA_A, bd))
    cand = (resolved_file(tmp_path / "c.env", SIM_B, DATA_B, cd), artifact(tmp_path / "c-art", SIM_B, DATA_B, cd))
    assert run_check(tmp_path, base, cand) == 1
    assert "different ledgers" in capsys.readouterr().out


def test_an_artifact_without_the_records_is_refused(world, capsys):
    tmp, _, _, base, cand = world
    (cand[1] / "ledger.sha256").unlink()
    assert run_check(tmp, base, cand) == 1
    assert "ledger.sha256" in capsys.readouterr().out


def test_the_ledger_digest_covers_names_and_bytes(tmp_path):
    d = make_data(tmp_path, "x")
    led = d / "catalog" / "ledger"
    first = binding.ledger_digest(led)
    (led / "published" / "fit.yaml").rename(led / "published" / "fit2.yaml")
    assert binding.ledger_digest(led) != first
    (led / "published" / "fit2.yaml").rename(led / "published" / "fit.yaml")
    assert binding.ledger_digest(led) == first
    (led / "ledger.yaml").write_text("kind: Ledger\n#")
    assert binding.ledger_digest(led) != first
    with pytest.raises(binding.BindingError):
        binding.ledger_digest(tmp_path / "empty")


@pytest.mark.parametrize("text,ok", [
    ("SIM_REF=" + "a" * 40 + "\n", True),
    ("# c\nSIM_REF=v0.18.1\nROUTER_REF=" + "b" * 40 + "\n", True),
    ("SIM_REF='v0.18.1-rc.1'\n", True),
    ("", False),
    ("SIM_REF=main\n", False),
    ("SIM_REF=" + "a" * 40 + "\nSIM_REF=" + "b" * 40 + "\n", False),
    ("SIM_REF=" + "A" * 40 + "\n", False),
])
def test_the_pin_is_one_tag_or_full_commit(text, ok):
    if ok:
        assert binding.read_sim_pin(text)
    else:
        with pytest.raises(binding.BindingError):
            binding.read_sim_pin(text)


def test_the_pin_file_of_this_repository_is_readable():
    assert binding.read_sim_pin((HERE.parents[1] / ".github" / "stack-pins.env").read_text())


def test_resolve_data_refuses_a_ref_that_is_neither_a_tag_nor_a_commit(tmp_path):
    for bad in ("main", "HEAD", "0fb85a7", "v1"):
        r = subprocess.run(["bash", str(HERE / "resolve_data.sh"), bad, str(tmp_path / "w")], capture_output=True, text=True)
        assert r.returncode == 2 and "neither a release tag nor a 40-hex commit" in r.stderr, bad
