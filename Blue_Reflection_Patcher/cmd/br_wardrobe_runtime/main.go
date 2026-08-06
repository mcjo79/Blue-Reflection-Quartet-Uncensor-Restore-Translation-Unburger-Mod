package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"local/blue-reflection-patcher/internal/runtime/wardrobe"
	"os"
	"strconv"
)

func fatalf(f string, a ...any) { fmt.Fprintf(os.Stderr, "ERROR: "+f+"\n", a...); os.Exit(2) }
func emit(v any) {
	e := json.NewEncoder(os.Stdout)
	e.SetIndent("", "  ")
	if err := e.Encode(v); err != nil {
		fatalf("encode JSON: %v", err)
	}
}
func parseAddress(s string) uint64 {
	if s == "" {
		return 0
	}
	v, err := strconv.ParseUint(s, 0, 64)
	if err != nil {
		fatalf("invalid address %q: %v", s, err)
	}
	return v
}
func loadInputs(pp, rp string) (wardrobe.TargetProfile, wardrobe.RecordSet) {
	p, err := wardrobe.LoadProfile(pp)
	if err != nil {
		fatalf("load profile: %v", err)
	}
	r, err := wardrobe.LoadRecords(rp)
	if err != nil {
		fatalf("load records: %v", err)
	}
	if err := r.Validate(p); err != nil {
		fatalf("validate records: %v", err)
	}
	return p, r
}
func usage() {
	fmt.Fprintln(os.Stderr, "br_wardrobe_runtime - generic bounded runtime wardrobe registry + cache virtualization")
	fmt.Fprintln(os.Stderr, "commands: capabilities | validate-module | plan | attach")
}
func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "capabilities":
		emit(map[string]any{"type": "br_runtime_capabilities", "format_version": 1, "capabilities": []string{wardrobe.CapabilityIDV1, wardrobe.CapabilityID}, "wardrobe_registry_append_v1": map[string]any{"memory_only": true, "global_show_all": false, "max_append_records": 8, "on_disk_game_binary_patch": false, "save_mutation": false, "superseded_by": wardrobe.CapabilityID}, "wardrobe_registry_append_v2": map[string]any{"memory_only": true, "global_show_all": false, "max_append_records": 8, "on_disk_game_binary_patch": false, "save_mutation": false, "registry_virtualization": true, "external_shadow_cache": true, "preserve_embedded_cache_0_55": true, "embedded_cache_in_place_extension": false, "object_writes_past_original_cache": false, "record_input_v1_compatible": true}})
	case "validate-module":
		fs := flag.NewFlagSet("validate-module", flag.ExitOnError)
		module := fs.String("module", "", "path to B1.dll")
		profile := fs.String("profile", "", "target profile JSON")
		_ = fs.Parse(os.Args[2:])
		if *module == "" || *profile == "" {
			fatalf("--module and --profile required")
		}
		p, err := wardrobe.LoadProfile(*profile)
		if err != nil {
			fatalf("load profile: %v", err)
		}
		r, err := wardrobe.ValidateModule(*module, p)
		if err != nil {
			fatalf("validate module: %v", err)
		}
		emit(r)
		if r.Status != "pass" {
			os.Exit(1)
		}
	case "plan":
		fs := flag.NewFlagSet("plan", flag.ExitOnError)
		module := fs.String("module", "", "path")
		profile := fs.String("profile", "", "profile")
		records := fs.String("records", "", "records")
		table := fs.String("new-table-address", "", "hypothetical table")
		cache := fs.String("shadow-cache-address", "", "hypothetical cache")
		stub := fs.String("hook-stub-address", "", "hypothetical stub")
		_ = fs.Parse(os.Args[2:])
		if *module == "" || *profile == "" || *records == "" {
			fatalf("--module --profile --records required")
		}
		p, r := loadInputs(*profile, *records)
		v, err := wardrobe.ValidateModule(*module, p)
		if err != nil {
			fatalf("validate module: %v", err)
		}
		if v.Status != "pass" {
			emit(map[string]any{"status": "failed", "module_validation": v})
			os.Exit(1)
		}
		base := validationImageBase(v)
		t := parseAddress(*table)
		if t == 0 {
			t = base + 0x40000000
		}
		c := parseAddress(*cache)
		if c == 0 {
			c = t + 0x10000
		}
		s := parseAddress(*stub)
		if s == 0 {
			s = base + 0x50000000
		}
		pl, err := wardrobe.BuildPlan(p, r, base, t, c, s)
		if err != nil {
			fatalf("build plan: %v", err)
		}
		emit(map[string]any{"status": pl.Status, "module_validation": v, "plan": pl})
		if pl.Status != "pass" {
			os.Exit(1)
		}
	case "attach":
		fs := flag.NewFlagSet("attach", flag.ExitOnError)
		pid := fs.Uint("pid", 0, "PID")
		name := fs.String("process-name", "", "process name")
		profile := fs.String("profile", "", "profile")
		records := fs.String("records", "", "records")
		_ = fs.Parse(os.Args[2:])
		if *profile == "" || *records == "" {
			fatalf("--profile and --records required")
		}
		if (*pid == 0) == (*name == "") {
			fatalf("specify exactly one of --pid or --process-name")
		}
		p, r := loadInputs(*profile, *records)
		target := uint32(*pid)
		if target == 0 {
			f, err := wardrobe.FindProcessByName(*name)
			if err != nil {
				fatalf("find process: %v", err)
			}
			target = f
		}
		rep, err := wardrobe.ApplyToProcess(target, p, r)
		if err != nil {
			fatalf("runtime apply: %v", err)
		}
		emit(rep)
		if rep.Status != "applied" {
			os.Exit(1)
		}
	default:
		usage()
		os.Exit(2)
	}
}
func validationImageBase(r wardrobe.ModuleValidationReport) uint64 {
	v, err := strconv.ParseUint(r.ImageBase, 0, 64)
	if err != nil {
		fatalf("invalid image base %q", r.ImageBase)
	}
	return v
}
