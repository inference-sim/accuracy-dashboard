package main

import (
	"bytes"
	"testing"
)

// The expectations are vLLM v0.31.0's served-deployment tiers as inference-sim encodes them
// (sim/kernelmodel/vllm_defaults.go): >=160 GiB 1024/16384; >=70 GiB and not an A100
// 1024/8192; otherwise 256/2048. Worked from the catalog's MemoryGiB per part.
func TestResolveMatchesTheServedTiers(t *testing.T) {
	for _, c := range []struct {
		dev          string
		mem          float64
		seqs, tokens int
	}{
		{"b200", 178.35, 1024, 16384},
		{"h200", 139.80072021, 1024, 8192},
		{"h100", 79.18, 1024, 8192},
		{"a100-80", 79.18, 256, 2048}, // excluded by name, not by memory
		{"l40s", 44.4, 256, 2048},
	} {
		got := Resolve(c.mem, c.dev)
		if got.MaxNumSeqs != c.seqs || got.MaxNumBatchedTokens != c.tokens {
			t.Errorf("%s %.2f GiB: got %d/%d, want %d/%d", c.dev, c.mem,
				got.MaxNumSeqs, got.MaxNumBatchedTokens, c.seqs, c.tokens)
		}
	}
}

func TestRunPrintsOneSortedJSONLine(t *testing.T) {
	var b bytes.Buffer
	if err := run([]string{"-memory-gib", "139.80072021", "-device", "h200"}, &b); err != nil {
		t.Fatal(err)
	}
	want := `{"device":"h200","max_num_batched_tokens":8192,"max_num_seqs":1024,"memory_gib":139.80072021}` + "\n"
	if b.String() != want {
		t.Fatalf("got %q want %q", b.String(), want)
	}
}

func TestRunRefusesMissingInputs(t *testing.T) {
	for _, args := range [][]string{{"-device", "h200"}, {"-memory-gib", "80"}} {
		if err := run(args, &bytes.Buffer{}); err == nil {
			t.Errorf("accepted %v", args)
		}
	}
}
