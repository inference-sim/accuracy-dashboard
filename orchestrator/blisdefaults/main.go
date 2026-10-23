// Command blisdefaults prints the batch settings BLIS assumes for a vLLM deployment that
// states neither, for one part: inference-sim's own resolver
// (sim/kernelmodel.ResolveVLLMBatchDefaults) at the BLIS release this module is built
// against. The extractor (orchestrator/ingest/settings.py) calls it only when no source a
// run left records max_num_seqs or max_num_batched_tokens; nothing here re-encodes the
// resolver's tiers.
//
// Usage: blisdefaults -memory-gib <GiB> -device <catalog hardware name>
// Prints one canonical JSON object: {"device":…,"max_num_batched_tokens":…,"max_num_seqs":…,"memory_gib":…}.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/inference-sim/inference-sim/sim/kernelmodel"
)

// Defaults is the helper's output.
type Defaults struct {
	Device              string  `json:"device"`
	MaxNumBatchedTokens int     `json:"max_num_batched_tokens"`
	MaxNumSeqs          int     `json:"max_num_seqs"`
	MemoryGiB           float64 `json:"memory_gib"`
}

// Resolve calls inference-sim's resolver.
func Resolve(memoryGiB float64, device string) Defaults {
	d := kernelmodel.ResolveVLLMBatchDefaults(memoryGiB, device)
	return Defaults{Device: device, MaxNumBatchedTokens: d.MaxNumBatchedTokens,
		MaxNumSeqs: d.MaxNumSeqs, MemoryGiB: memoryGiB}
}

func run(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("blisdefaults", flag.ContinueOnError)
	mem := fs.Float64("memory-gib", 0, "the part's total device memory in GiB (catalog hardware MemoryGiB)")
	dev := fs.String("device", "", "the part's catalog hardware name")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *mem <= 0 || *dev == "" {
		return fmt.Errorf("-memory-gib > 0 and -device are required")
	}
	// encoding/json sorts struct fields in declaration order, which is alphabetical here.
	return json.NewEncoder(out).Encode(Resolve(*mem, *dev))
}

func main() {
	if err := run(os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "blisdefaults:", err)
		os.Exit(2)
	}
}
