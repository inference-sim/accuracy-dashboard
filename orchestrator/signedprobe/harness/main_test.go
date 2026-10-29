package harness

import (
	"testing"

	"github.com/inference-sim/accuracy-dashboard/orchestrator/signedprobe/harness/internal/artifacts"
)

func TestMain(m *testing.M) { artifacts.Main(m) }
