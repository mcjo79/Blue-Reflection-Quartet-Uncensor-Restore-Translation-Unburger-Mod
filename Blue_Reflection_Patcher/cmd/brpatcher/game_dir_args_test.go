package main

import (
	"flag"
	"testing"
)

func TestAdoptSinglePositionalGameDir(t *testing.T) {
	flags := flag.NewFlagSet("test", flag.ContinueOnError)
	var roots rootsFlag
	flags.Var(&roots, "game-dir", "")
	if err := flags.Parse([]string{`D:\Games\BLUE REFLECTION Quartet`}); err != nil {
		t.Fatal(err)
	}
	if err := adoptSinglePositionalGameDir(flags, &roots); err != nil {
		t.Fatal(err)
	}
	if len(roots) != 1 || roots[0] != `D:\Games\BLUE REFLECTION Quartet` {
		t.Fatalf("unexpected roots: %#v", roots)
	}
}

func TestAdoptSinglePositionalGameDirRejectsAmbiguousArguments(t *testing.T) {
	flags := flag.NewFlagSet("test", flag.ContinueOnError)
	var roots rootsFlag
	flags.Var(&roots, "game-dir", "")
	if err := flags.Parse([]string{"one", "two"}); err != nil {
		t.Fatal(err)
	}
	if err := adoptSinglePositionalGameDir(flags, &roots); err == nil {
		t.Fatal("expected ambiguous positional arguments to fail")
	}
}
