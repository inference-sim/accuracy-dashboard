// Validate every PointRecord of a JSON-lines file with the substrate's own loader and validator
// (strict decoding: an unknown key is an error; then Record.Validate).
package main

import (
	"bufio"
	"fmt"
	"os"

	"github.com/inference-sim/blis-substrate/contracts/spec/pointrecord"
	"github.com/inference-sim/blis-substrate/contracts/spec/result"
)

func main() {
	bad, n := 0, 0
	for _, path := range os.Args[1:] {
		f, err := os.Open(path)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<26)
		line := 0
		for sc.Scan() {
			line++
			if len(sc.Bytes()) == 0 {
				continue
			}
			n++
			var r pointrecord.Record
			if err := result.UnmarshalStrict(append([]byte{}, sc.Bytes()...), &r); err != nil {
				fmt.Fprintf(os.Stderr, "%s:%d: load: %v\n", path, line, err)
				bad++
				continue
			}
			if p := r.Validate(); !p.OK() {
				fmt.Fprintf(os.Stderr, "%s:%d: %s: %v\n", path, line, r.PointID, p.Error())
				bad++
			}
		}
		f.Close()
	}
	fmt.Printf("%d records, %d refused\n", n, bad)
	if bad > 0 {
		os.Exit(1)
	}
}
