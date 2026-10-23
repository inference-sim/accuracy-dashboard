// Command blisdefaults asks the BLIS release this module is built against what it assumes,
// so the extractor never encodes BLIS's rules itself.
//
//	blisdefaults -memory-gib <GiB> -device <catalog hardware name>
//	    The batch settings BLIS assumes for a vLLM deployment that states neither, for one
//	    part (sim/kernelmodel.ResolveVLLMBatchDefaults). The extractor uses them only when no
//	    source a run left records max_num_seqs or max_num_batched_tokens.
//	    Prints {"device":…,"max_num_batched_tokens":…,"max_num_seqs":…,"memory_gib":…}.
//
//	blisdefaults -resolve -scenarios <dir> -scenario <file> -catalog <dir> -registry <dir>
//	    What BLIS resolves for one scenario as written: the kernel's own resolution
//	    (kernel.Resolution), including every override of a requested value with BLIS's reason.
//	    The extractor records these as what BLIS used for a setting the run stated but BLIS
//	    can't (e.g. the cache record its attention backend serves).
//	    Prints {"overrides":[{"field","requested","resolved","reason"}…],"tp":…,"dp":…,"ep":…}.
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

// Override is one value BLIS resolved differently from what the scenario requested.
type Override struct {
	Field     string `json:"field"`
	Reason    string `json:"reason"`
	Requested string `json:"requested"`
	Resolved  string `json:"resolved"`
}

// Resolution is what BLIS resolved for a scenario.
type Resolution struct {
	DP        int        `json:"dp"`
	EP        int        `json:"ep"`
	Overrides []Override `json:"overrides"`
	TP        int        `json:"tp"`
}

// ResolveScenario opens a scenario with inference-sim's kernel and reports its resolution.
func ResolveScenario(r kernelmodel.Repos, scenario string) (Resolution, error) {
	m, err := kernelmodel.Open(scenario, r)
	if err != nil {
		return Resolution{}, err
	}
	res := m.Kernel().Resolved()
	out := Resolution{TP: res.TensorParallel(), DP: res.DataParallel(), EP: res.ExpertParallel(), Overrides: []Override{}}
	for _, o := range res.Overrides {
		out.Overrides = append(out.Overrides, Override{Field: o.Field, Requested: fmt.Sprint(o.Requested),
			Resolved: fmt.Sprint(o.Resolved), Reason: o.Reason})
	}
	return out, nil
}

func run(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("blisdefaults", flag.ContinueOnError)
	mem := fs.Float64("memory-gib", 0, "the part's total device memory in GiB (catalog hardware MemoryGiB)")
	dev := fs.String("device", "", "the part's catalog hardware name")
	resolve := fs.Bool("resolve", false, "report BLIS's resolution of one scenario instead")
	scenarios := fs.String("scenarios", "", "with -resolve: the scenario directory")
	scenario := fs.String("scenario", "", "with -resolve: the scenario file name")
	catalog := fs.String("catalog", "", "with -resolve: the blis-catalog root")
	registry := fs.String("registry", "", "with -resolve: the blis-registry root")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *resolve {
		if *scenarios == "" || *scenario == "" || *catalog == "" || *registry == "" {
			return fmt.Errorf("-resolve needs -scenarios, -scenario, -catalog and -registry")
		}
		res, err := ResolveScenario(kernelmodel.Repos{Scenarios: *scenarios, Catalog: *catalog, Registry: *registry}, *scenario)
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(res)
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
