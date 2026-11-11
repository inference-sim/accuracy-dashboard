"""A record the harness writes validates against the substrate's PointRecord validator (SUB-19).

The validator is Go (blis-substrate contracts/spec/pointrecord, `contracts.LoadPointRecord` and
`Record.Validate`). The PointRecord carries `harness_commit`; the substrate renames its `harness_digest`
field to that in layer 10 (blis-substrate #45), per design section 11.7 and X8. Until the layer 10 commit
is pushed there is nothing to build the validator from, so this test is skipped with that reason.

To run it: BLIS_SUBSTRATE_LAYER10=<a blis-substrate checkout at the layer 10 commit> and a Go toolchain.
It belongs in the first pull request (the one that introduced harness_commit) once the commit is known.
"""
import os
import shutil

import pytest

LAYER10 = os.environ.get("BLIS_SUBSTRATE_LAYER10")


@pytest.mark.skipif(not LAYER10 or not shutil.which("go"),
                    reason="the substrate layer 10 commit that renames harness_digest to harness_commit "
                           "(blis-substrate #45) is not pushed yet: set BLIS_SUBSTRATE_LAYER10 to a checkout "
                           "of it, with a Go toolchain")
def test_a_record_the_harness_writes_validates_against_the_substrates_point_record_validator():
    pytest.fail("write the record from a scored outcome and load it with contracts.LoadPointRecord "
                "once the layer 10 commit is named")
