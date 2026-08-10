package br1rebuild

import "testing"

func TestSecondLightRequiredSourceDataMembersUseStandalonePaths(t *testing.T) {
	want := []string{
		`\saves\chara\charabase.xml`,
		`\saves\costume\costume_body.xml`,
		`\saves\party\party_skill.xml`,
	}
	if len(secondLightRequiredSourceDataMembers) != len(want) {
		t.Fatalf("required Second Light source table count=%d, want %d", len(secondLightRequiredSourceDataMembers), len(want))
	}
	for _, path := range want {
		if !secondLightRequiredSourceDataMembers[path] {
			t.Errorf("required standalone Second Light table path missing: %s", path)
		}
	}
	if secondLightRequiredSourceDataMembers[`\party\party_skill.xml`] {
		t.Fatal("accepted non-existent root-level party_skill source path")
	}
}
