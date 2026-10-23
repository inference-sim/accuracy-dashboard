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
//	    Also every value the kernel supplied itself because the scenario stated none (its
//	    assumptions, e.g. block_size), which the extractor uses only when no source a run left
//	    records that setting.
//	    And the cache records the kernel prices, from the same graph and chip it loads (the
//	    graph as served on this GPU architecture, under the resolved cache dtype): name, kind
//	    and bytes per entry for every owned cache.
//	    Prints {"assumptions":[{"name","value","reason"}…],"cache_dtype":…,
//	    "caches":[{"name","kind","bytes_per_entry"}…],"overrides":[{"field","requested","resolved","reason"}…],
//	    "tp":…,"dp":…,"ep":…}.
//
//	blisdefaults -acceptance -registry <dir> -model <catalog model> -method <m> -k <n> -thinking <on|off> [-category <c>] [-fallback-category <c>]
//	    BLIS's own acceptance length for a drafter, when the run recorded none: blis-schemas'
//	    acceptance.Resolve over the registry's acceptance profile sets (the layer BLIS falls
//	    back to with no value stated). Refuses what it refuses: no profile, an ambiguous match.
//	    Prints {"acceptance_length":…,"fallback_from":…,"measured_on":…,"profile":…,"set":…}.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	latencykernel "github.com/inference-sim/blis-latency-kernel"
	schemamodel "github.com/inference-sim/blis-schemas/spec/model"
	"github.com/inference-sim/inference-sim/sim/kernelmodel"

	blisschemas "github.com/inference-sim/blis-schemas"
	"github.com/inference-sim/blis-schemas/spec/acceptance"
)

// Acceptance is BLIS's registry default for a drafter's acceptance.
type Acceptance struct {
	AcceptanceLength float64 `json:"acceptance_length"`
	FallbackFrom     string  `json:"fallback_from"`
	MeasuredOn       string  `json:"measured_on"`
	Profile          string  `json:"profile"`
	Set              string  `json:"set"`
}

// RegistryAcceptance resolves acceptance from the registry layer alone, as BLIS does when no
// command line, scenario or workload value states one.
func RegistryAcceptance(registry, model, method string, k int, thinking, category, fallback, hardware string) (Acceptance, error) {
	dir := filepath.Join(registry, "acceptance")
	var paths []string
	if err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.Type().IsRegular() && (strings.HasSuffix(p, ".yaml") || strings.HasSuffix(p, ".yml")) {
			paths = append(paths, p)
		}
		return nil
	}); err != nil {
		return Acceptance{}, err
	}
	sort.Strings(paths)
	var sets []*acceptance.ProfileSet
	for _, p := range paths {
		s, err := blisschemas.LoadAcceptanceProfileSet(p)
		if err != nil {
			return Acceptance{}, err
		}
		if pr := s.Validate(); !pr.OK() {
			return Acceptance{}, fmt.Errorf("%s: %s", p, pr.Error())
		}
		sets = append(sets, s)
	}
	// A workload that states no category (InferenceX's random-token single-turn benchmark, for
	// one) matches no profile. When the registry describes this drafter under exactly one
	// category, that category is substituted -- recorded as fallback_from, never silent; with
	// several, which one applies isn't knowable and the lookup is refused.
	if category == "" && fallback == "" {
		cats := map[string]bool{}
		for _, s := range sets {
			for _, p := range s.Profiles {
				if p.Model == model && p.SpeculativeMethod == method && p.NumSpecTokens == k && string(p.Thinking) == thinking {
					cats[p.Category] = true
				}
			}
		}
		if len(cats) == 1 {
			for c := range cats {
				fallback = c
			}
		}
	}
	res, err := acceptance.Resolve(acceptance.Request{Model: model, SpeculativeMethod: method, NumSpecTokens: k,
		Hardware: hardware, Registry: sets, FallbackCategory: fallback,
		Workload: acceptance.Workload{Thinking: acceptance.Thinking(thinking), Category: category}})
	if err != nil {
		return Acceptance{}, err
	}
	out := Acceptance{AcceptanceLength: res.AcceptanceLength, FallbackFrom: res.FallbackFrom,
		MeasuredOn: res.MeasuredOn, Set: res.Set}
	if res.Profile != nil {
		out.Profile = res.Profile.Key().String()
	}
	return out, nil
}

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

// Assumption is a value the kernel supplied because the scenario stated none.
type Assumption struct {
	Name   string `json:"name"`
	Reason string `json:"reason"`
	Value  string `json:"value"`
}

// CacheRecord is one owned cache the kernel prices, as served on the scenario's chip.
// HeadDim is the head dimension of the node that owns it (0 when the node states none), so a
// caller can name the record's format by vLLM's own layout rules.
type CacheRecord struct {
	BytesPerEntry int    `json:"bytes_per_entry"`
	HeadDim       int    `json:"head_dim"`
	Kind          string `json:"kind"`
	Name          string `json:"name"`
}

// Resolution is what BLIS resolved for a scenario.
type Resolution struct {
	Assumptions []Assumption  `json:"assumptions"`
	CacheDType  string        `json:"cache_dtype"`
	Caches      []CacheRecord `json:"caches"`
	DP          int           `json:"dp"`
	EP          int           `json:"ep"`
	Overrides   []Override    `json:"overrides"`
	TP          int           `json:"tp"`
}

// ResolveScenario opens a scenario with inference-sim's kernel and reports its resolution.
func ResolveScenario(r kernelmodel.Repos, scenario string) (Resolution, error) {
	m, err := kernelmodel.Open(scenario, r)
	if err != nil {
		return Resolution{}, err
	}
	// The same documents the kernel was built from (OpenInputs is its loading half), so the
	// records below are the ones it priced, not a second reading of the catalog.
	in, err := latencykernel.OpenInputs(scenario, latencykernel.Repos{Scenarios: r.Scenarios,
		Catalog: r.Catalog, Registry: r.Registry}, 0)
	if err != nil {
		return Resolution{}, err
	}
	family, _ := in.Chip.CapabilityMajor()
	g, err := in.Model.ForCapability(family)
	if err != nil {
		return Resolution{}, err
	}
	k := m.Kernel()
	res := k.Resolved()
	out := Resolution{TP: res.TensorParallel(), DP: res.DataParallel(), EP: res.ExpertParallel(),
		Overrides: []Override{}, Assumptions: []Assumption{}}
	for _, o := range k.Provenance() {
		// The kernel's own assumptions carry "<value>: <reason>" as their scope.
		if o.Set != latencykernel.KernelAssumptionSet {
			continue
		}
		value, reason, _ := strings.Cut(o.Scope, ": ")
		out.Assumptions = append(out.Assumptions, Assumption{Name: o.Name, Value: value, Reason: reason})
	}
	out.CacheDType = k.Deployment().Engine.CacheDType
	for _, o := range res.Overrides {
		if o.Field == "cache_dtype" {
			out.CacheDType = fmt.Sprint(o.Resolved)
		}
	}
	out.Caches = []CacheRecord{}
	seen := map[string]bool{}
	g.EachNode(func(_ string, n schemamodel.Node) {
		for _, c := range n.Caches {
			if !c.Owned || seen[c.Name] {
				continue
			}
			seen[c.Name] = true
			out.Caches = append(out.Caches, CacheRecord{Name: c.Name, Kind: string(c.Kind),
				BytesPerEntry: c.EntryBytes(out.CacheDType), HeadDim: n.HeadDim})
		}
	})
	sort.Slice(out.Caches, func(i, j int) bool { return out.Caches[i].Name < out.Caches[j].Name })
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
	accept := fs.Bool("acceptance", false, "report BLIS's registry acceptance length instead")
	model := fs.String("model", "", "with -acceptance: the catalog model")
	method := fs.String("method", "", "with -acceptance: the speculative method")
	k := fs.Int("k", 0, "with -acceptance: num_spec_tokens")
	thinking := fs.String("thinking", "", "with -acceptance: on or off")
	category := fs.String("category", "", "with -acceptance: the workload category")
	fallback := fs.String("fallback-category", "", "with -acceptance: a category to substitute, recorded")
	scenarios := fs.String("scenarios", "", "with -resolve: the scenario directory")
	scenario := fs.String("scenario", "", "with -resolve: the scenario file name")
	catalog := fs.String("catalog", "", "with -resolve: the blis-catalog root")
	registry := fs.String("registry", "", "with -resolve: the blis-registry root")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *accept {
		if *registry == "" || *model == "" || *method == "" || *k < 1 || *thinking == "" {
			return fmt.Errorf("-acceptance needs -registry, -model, -method, -k >= 1 and -thinking")
		}
		a, err := RegistryAcceptance(*registry, *model, *method, *k, *thinking, *category, *fallback, *dev)
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(a)
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
