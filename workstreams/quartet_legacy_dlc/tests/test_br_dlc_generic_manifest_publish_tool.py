import importlib.util, json, pathlib, tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("tool", ROOT/"br_dlc_generic_manifest_publish_tool.py")
TOOL=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(TOOL)

def proposal():
    return json.loads((ROOT/"BKN_DRY_PC00_PC01_ACTIVE_MANIFEST.json").read_text())

def test_canonical_proposal_semantics_pass():
    TOOL.validate_manifest_semantics(proposal())

def test_commit_enabled_true_is_rejected():
    value=proposal(); value["transaction"]["commit_enabled"]=True
    try: TOOL.validate_manifest_semantics(value)
    except TOOL.ValidationError: return
    raise AssertionError("unsafe manifest accepted")

def test_extra_target_is_rejected():
    value=proposal(); value["artifacts"].append(dict(value["artifacts"][0], target_path="Data/PACK99.PAK"))
    try: TOOL.validate_manifest_semantics(value)
    except TOOL.ValidationError: return
    raise AssertionError("extra target accepted")

def test_atomic_publish_is_idempotent_and_conflicts_fail():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td).resolve(); target=root/".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
        assert TOOL.atomic_write_bytes(root,target,b"one\n")=="published"
        assert TOOL.atomic_write_bytes(root,target,b"one\n")=="already_identical"
        try: TOOL.atomic_write_bytes(root,target,b"two\n")
        except TOOL.ValidationError: return
        raise AssertionError("different active manifest overwritten")
