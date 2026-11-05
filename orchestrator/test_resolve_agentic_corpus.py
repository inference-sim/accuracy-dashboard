"""Tests for resolve_agentic_corpus.py: the corpus a run loaded picks its catalog workload, the
file is fetched at that entry's revision, and only the entry's full sha256 is accepted (X12, D3,
COV-12). No network: the download is a function the tests replace.

Run: python3 -m pytest orchestrator/test_resolve_agentic_corpus.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract_agentic_replay_args as ex  # noqa: E402
import resolve_agentic_corpus as rc  # noqa: E402

UNCAPPED = "semianalysis_cc_traces_weka_062126"
CAPPED = "semianalysis_cc_traces_weka_062126_256k"
# The two entries' pins, as blis-substrate's catalog/workloads states them.
REV = {UNCAPPED: "23f152f6f0f9399a85901b89a6458def0ef16729", CAPPED: "8fecd2fc56694469f758f0afbbb6335ad3043740"}
BODY = b'{"trace": 1}\n'
DIGEST = hashlib.sha256(BODY).hexdigest()


def entry_yaml(alias: str, sha256: str, revision: str | None = None, repo: str | None = None) -> str:
    return (f"replay:\n  scenario: inferencex-agentx-mvp\n  harness_version: 0.12.0\n  corpus:\n"
            f"    loader: {alias}\n    format: weka-trace-v7\n    encoding: jsonl\n    source:\n"
            f"      huggingface: {repo or ex.PINNED_CORPORA[alias]}\n"
            f"      revision: {revision or REV[alias]}\n      file: traces.jsonl\n      split: train\n"
            f"    sha256: {sha256}\n  random_seed: 42\n")


def catalog(tmp: Path, entries: dict[str, str]) -> Path:
    (tmp / "workloads").mkdir(parents=True, exist_ok=True)
    for name, text in entries.items():
        (tmp / "workloads" / f"{name}.yaml").write_text(text)
    return tmp


def both(tmp: Path, sha=DIGEST) -> Path:
    return catalog(tmp, {"agentx-mvp-uncapped": entry_yaml(UNCAPPED, sha), "agentx-mvp": entry_yaml(CAPPED, "e" * 64)})


def fake_download(body: bytes, seen: list):
    def dl(url: str, dest: Path) -> None:
        seen.append(url)
        dest.write_bytes(body)
    return dl


def test_both_date_pinned_aliases_are_known_and_map_to_their_entries():
    assert ex.PINNED_CORPORA == {UNCAPPED: "semianalysisai/cc-traces-weka-062126",
                                 CAPPED: "semianalysisai/cc-traces-weka-062126-256k"}
    assert ex.CATALOG_WORKLOADS == {UNCAPPED: "agentx-mvp-uncapped", CAPPED: "agentx-mvp"}


def test_a_capped_run_is_not_corpus_unknown():
    job = ex.parse_job_log(f"+ aiperf profile --scenario inferencex-agentx-mvp --public-dataset {CAPPED}\n")
    assert job["corpus_pinned"] is True
    assert (job["corpus_dataset"], job["catalog_workload"]) == ("semianalysisai/cc-traces-weka-062126-256k", "agentx-mvp")


@pytest.mark.parametrize("alias,name", [(UNCAPPED, "agentx-mvp-uncapped"), (CAPPED, "agentx-mvp")])
def test_each_alias_reads_its_own_entry(tmp_path, alias, name):
    e = rc.catalog_entry(both(tmp_path), alias)
    assert (e["workload"], e["revision"], e["repo"]) == (name, REV[alias], ex.PINNED_CORPORA[alias])
    assert e["path"] == tmp_path / "workloads" / f"{name}.yaml"


def test_the_download_url_names_the_entrys_revision_not_main(tmp_path):
    seen = []
    entry, dest = rc.resolve(UNCAPPED, both(tmp_path / "cat"), tmp_path / "out", download=fake_download(BODY, seen))
    assert seen == [f"https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126/resolve/{REV[UNCAPPED]}/traces.jsonl"]
    assert dest.read_bytes() == BODY and entry["sha256"] == DIGEST


@pytest.mark.parametrize("rev", ["main", "HEAD", "23f152f6f0f9", "local"])
def test_a_moving_or_short_revision_is_refused(tmp_path, rev):
    with pytest.raises(rc.CorpusError, match="40-hex"):
        rc.dataset_url("semianalysisai/cc-traces-weka-062126", rev, "traces.jsonl")
    cat = catalog(tmp_path, {"agentx-mvp-uncapped": entry_yaml(UNCAPPED, DIGEST, revision=rev)})
    with pytest.raises(rc.CorpusError, match="revision"):
        rc.catalog_entry(cat, UNCAPPED)


def test_a_hash_prefix_match_is_refused(tmp_path):
    # The old check accepted any download whose sha256 began with a 12-hex prefix.
    prefix = DIGEST[:12]
    with pytest.raises(rc.CorpusError, match="64-hex"):
        rc.catalog_entry(catalog(tmp_path / "a", {"agentx-mvp-uncapped": entry_yaml(UNCAPPED, prefix)}), UNCAPPED)
    f = tmp_path / "traces.jsonl"
    f.write_bytes(BODY)
    with pytest.raises(rc.CorpusError, match="mismatch"):
        rc.check(f, {"repo": "r", "revision": REV[UNCAPPED], "workload": "agentx-mvp-uncapped", "sha256": prefix})
    # The same prefix with another tail: equal for 12 characters, a different file.
    with pytest.raises(rc.CorpusError, match="mismatch"):
        rc.check(f, {"repo": "r", "revision": REV[UNCAPPED], "workload": "agentx-mvp-uncapped",
                     "sha256": prefix + ("0" if DIGEST[12] != "0" else "1") + DIGEST[13:]})


def test_a_mismatched_download_is_refused_and_removed(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(rc.CorpusError, match="mismatch"):
        rc.resolve(UNCAPPED, both(tmp_path / "cat"), out, download=fake_download(BODY + b"x", []))
    assert list(out.iterdir()) == []


def test_the_uncapped_alias_is_never_checked_against_the_capped_entry(tmp_path):
    # The capped corpus's file, fetched for the uncapped alias, fails the uncapped entry's hash.
    capped_body = b'{"trace": "capped"}\n'
    cat = catalog(tmp_path / "cat", {"agentx-mvp-uncapped": entry_yaml(UNCAPPED, DIGEST),
                                     "agentx-mvp": entry_yaml(CAPPED, hashlib.sha256(capped_body).hexdigest())})
    with pytest.raises(rc.CorpusError, match="agentx-mvp-uncapped pins"):
        rc.resolve(UNCAPPED, cat, tmp_path / "out", download=fake_download(capped_body, []))
    entry, _ = rc.resolve(CAPPED, cat, tmp_path / "out2", download=fake_download(capped_body, []))
    assert entry["workload"] == "agentx-mvp"


def test_an_entry_naming_another_corpus_is_refused(tmp_path):
    cat = catalog(tmp_path, {"agentx-mvp-uncapped": entry_yaml(CAPPED, DIGEST, revision=REV[UNCAPPED])})
    with pytest.raises(rc.CorpusError, match="loader"):
        rc.catalog_entry(cat, UNCAPPED)
    cat = catalog(tmp_path, {"agentx-mvp-uncapped": entry_yaml(UNCAPPED, DIGEST, repo="someone/else")})
    with pytest.raises(rc.CorpusError, match="huggingface"):
        rc.catalog_entry(cat, UNCAPPED)


def test_a_rolling_alias_and_a_missing_entry_are_refused(tmp_path):
    with pytest.raises(rc.CorpusError, match="date-pinned"):
        rc.catalog_entry(both(tmp_path), "semianalysis_cc_traces_weka_with_subagents")
    with pytest.raises(rc.CorpusError, match="no workload 'agentx-mvp'"):
        rc.catalog_entry(catalog(tmp_path / "only", {"agentx-mvp-uncapped": entry_yaml(UNCAPPED, DIGEST)}), CAPPED)
