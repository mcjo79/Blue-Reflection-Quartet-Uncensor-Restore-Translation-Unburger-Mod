package payloadpreview

func quartetModulesNeedComposition(selected map[string]bool) bool {
	if selected["quartet_restoration"] {
		return true
	}
	return selected["blue_reflection_translation"] && selected["quartet_legacy_dlc"]
}
