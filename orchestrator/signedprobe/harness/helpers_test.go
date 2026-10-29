package harness

import (
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"

	"github.com/inference-sim/accuracy-dashboard/orchestrator/signedprobe/harness/internal/artifacts"
	"github.com/inference-sim/blis-vllm/compat/kernelmodel"
)

// testRepos is the artifact roots the harness tests run against: the pinned kernel module's
// scenarios and the vendored catalog and registry.
func testRepos() kernelmodel.Repos {
	return kernelmodel.Repos{
		Scenarios: kernelmodel.DefaultScenarios(),
		Catalog:   kernelmodel.DefaultCatalog(),
		Registry:  kernelmodel.DefaultRegistry(),
	}
}

var (
	blisOnce sync.Once
	blisPath string
	blisErr  error
)

// testBlis is the blis binary the harness tests simulate with, built once per test process
// from the inference-sim checkout named by BLIS_SIM_DIR -- so a test exercises the `blis
// replay` of a known tree, never a stale binary on PATH. (In inference-sim this was the
// checkout under test; in the dashboard the harness is a copy, so the checkout is named.)
// Without BLIS_SIM_DIR the tests that simulate are skipped, naming what they need.
//
// It is built into the user cache directory and moved into place atomically, so concurrent
// test processes cannot observe a half-written binary and nothing accumulates in TMPDIR. The
// Go build cache makes every build after the first a link step.
func testBlis(t testing.TB) string {
	t.Helper()
	root := os.Getenv("BLIS_SIM_DIR")
	if root == "" {
		t.Skip("simulates through blis: set BLIS_SIM_DIR to an inference-sim checkout (e.g. the release being scored)")
	}
	blisOnce.Do(func() {
		cache, err := os.UserCacheDir()
		if err != nil {
			blisErr = err
			return
		}
		dir := filepath.Join(cache, "inference-sim", "harness-test")
		if blisErr = os.MkdirAll(dir, 0o755); blisErr != nil {
			return
		}
		tmp, err := os.CreateTemp(dir, "blis-*")
		if err != nil {
			blisErr = err
			return
		}
		if blisErr = tmp.Close(); blisErr != nil {
			return
		}
		cmd := exec.Command("go", "build", "-o", tmp.Name(), ".")
		cmd.Dir = root
		if out, err := cmd.CombinedOutput(); err != nil {
			_ = os.Remove(tmp.Name())
			blisErr = &buildError{err: err, out: string(out)}
			return
		}
		blisPath = filepath.Join(dir, "blis")
		blisErr = os.Rename(tmp.Name(), blisPath)
	})
	if blisErr != nil {
		t.Fatalf("building blis for the harness tests: %v", blisErr)
	}
	return blisPath
}

type buildError struct {
	err error
	out string
}

func (e *buildError) Error() string { return e.err.Error() + "\n" + e.out }

// testSweep returns a real sweep from the corpus rather than a hand-built one, so the test
// exercises the same inputs the score does.
func testSweep(t *testing.T) Sweep {
	t.Helper()
	c, err := LoadCorpus(artifacts.Measurement(t, "aisimulate_e2e.json"))
	if err != nil {
		t.Fatalf("corpus: %v", err)
	}
	for _, sw := range c.Sweeps {
		if sw.Scenario == "gpt-oss-120b-h200-fp4-vllm-tp4.yaml" && sw.Framework == "vllm" {
			return sw
		}
	}
	t.Fatal("gpt-oss-120b-h200-fp4-vllm-tp4 not in the corpus")
	return Sweep{}
}
