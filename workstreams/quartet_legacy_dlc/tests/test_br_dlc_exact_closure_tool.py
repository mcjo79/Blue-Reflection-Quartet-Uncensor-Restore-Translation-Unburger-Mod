from __future__ import annotations
import importlib.util, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
WS=ROOT/'workstreams/quartet_legacy_dlc'
sys.path.insert(0,str(WS))
spec=importlib.util.spec_from_file_location('br_dlc_exact_closure_tool',WS/'br_dlc_exact_closure_tool.py')
assert spec and spec.loader
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class ExactClosureHelpersTest(unittest.TestCase):
    def test_costume_owner_tokens_include_wet(self):
        self.assertEqual(mod.explicit_owner_tokens('costume_pc02_bkn'), ['PC02_DLC_BKN','PC02_DLC_BKN_W'])
    def test_item_owner_tokens(self):
        self.assertEqual(mod.explicit_owner_tokens('dlc_item_3'), ['ITEM_DLC_ITEM_03','STR_ITEM_NAME_DLC_ITEM_03'])
    def test_contextual_channel_skin_is_quarantined(self):
        scope,_=mod.scope_classification('identifier_str_channel_skin_color01',[{'technical_type':'theme_or_ui_content'}],[])
        self.assertEqual(scope,'quarantined_contextual_false_positive')
    def test_character_effect_is_companion(self):
        scope,_=mod.scope_classification('costume_character_ako_bkn',[{'technical_type':'costume_or_outfit'}],[])
        self.assertEqual(scope,'companion_record')
    def test_direct_member_is_owner(self):
        scope,_=mod.scope_classification('costume_pc00_bkn',[{'technical_type':'costume_or_outfit'}],[{'normalized_path':'x'}])
        self.assertEqual(scope,'canonical_owner')
    def test_shared_dependency_not_owner(self):
        scope,_=mod.scope_classification('shared_asset_abcd',[{'technical_type':'shared_asset_dependency'}],[{'normalized_path':'x'}])
        self.assertEqual(scope,'shared_dependency_pool')
    def test_nested_closure_remains_blocked(self):
        status,evidence,_=mod.role_evidence('nested_model_material_inventory','costume_pc00_bkn',[],[{'normalized_path':'x.elixir.gz','variant_state':'dry','member_role':'model_material_or_container'}],[])
        self.assertEqual(status,'container_present_nested_inventory_required')
        self.assertEqual(evidence,['x.elixir.gz'])
    def test_unlock_semantics_not_claimed(self):
        status,evidence,_=mod.role_evidence('unlock_or_availability_chain','dlc_item_00',[],[],[{'flag_or_condition_id':'FLAG'}])
        self.assertEqual(status,'metadata_resolved_semantics_unproven')
        self.assertEqual(evidence,['FLAG'])

if __name__=='__main__': unittest.main()
