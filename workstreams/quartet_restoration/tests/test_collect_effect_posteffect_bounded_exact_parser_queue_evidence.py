from __future__ import annotations
import csv, importlib.util, subprocess, tempfile, unittest
from pathlib import Path

WORKSTREAM=Path(__file__).resolve().parents[1]
PROJECT=WORKSTREAM.parent.parent
TOOL_PATH=WORKSTREAM/'137_collect_effect_posteffect_bounded_exact_parser_queue_evidence.py'
SPEC=importlib.util.spec_from_file_location('stage137_tool',TOOL_PATH); assert SPEC and SPEC.loader
TOOL=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(TOOL)

def read_tsv(p:Path):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f,delimiter='\t'))

class EffectPosteffectBoundedExactParserQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='stage137-tests-'); cls.root=Path(cls.tmp.name)
        cls.archive,cls.summary=TOOL.build_report(PROJECT,output_report_root=cls.root,create_archive=True)
        cls.report=cls.root/TOOL.REPORT_DIR
        cls.families=read_tsv(cls.report/'G1E_RECURRENT_STRUCTURE_FAMILY_PARSER_QUEUE.tsv')
        cls.transitions=read_tsv(cls.report/'G1E_HIGH_RECURRENCE_TRANSITION_PARSER_QUEUE.tsv')
        cls.kps_paths=read_tsv(cls.report/'KPS_EXACT_PARSER_PATH_QUEUE.tsv')
        cls.kps_programs=read_tsv(cls.report/'KPS_EXACT_PARSER_PROGRAM_QUEUE.tsv')
        cls.kps_controls=read_tsv(cls.report/'KPS_METADATA_ONLY_CONTROL_PATHS.tsv')
        cls.carry=read_tsv(cls.report/'UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv')
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_exact_stage136_prerequisite(self):
        self.assertEqual(self.summary['stage136_report_sha256'],TOOL.STAGE136_SHA256)
        self.assertEqual(self.summary['stage136_summary_sha256'],TOOL.STAGE136_SUMMARY_SHA256)

    def test_all_recurrent_g1e_families_are_queued(self):
        self.assertEqual(len(self.families),83)
        self.assertEqual(self.summary['g1e_nonrecurrent_control_family_rows'],43)
        self.assertEqual(self.summary['g1e_recurrent_family_tiers'],{'broad_ge_10_members':7,'medium_5_9_members':24,'small_2_4_members':52})

    def test_g1e_family_queue_preserves_structural_partition(self):
        self.assertEqual(self.summary['g1e_recurrent_family_queue_kinds'],{
            'fixed_size_record_layout_parser_queue':11,
            'mixed_alignment_record_layout_parser_queue':72})
        self.assertTrue(all(r['write_authorized']=='False' for r in self.families))

    def test_high_recurrence_transition_queue_is_exactly_bounded(self):
        self.assertEqual(len(self.transitions),646)
        self.assertTrue(all(int(r['member_rows'])>=10 for r in self.transitions))
        self.assertTrue(all(int(r['structure_family_rows'])>=3 for r in self.transitions))
        self.assertEqual(self.summary['g1e_offset_or_length_candidate_rows'],31)
        self.assertEqual(self.summary['g1e_float_looking_candidate_rows'],24)

    def test_transition_kinds_remain_nonsemantic(self):
        kinds=set(r['parser_queue_kind'] for r in self.transitions)
        self.assertIn('offset_or_length_rebase_exact_parser_queue',kinds)
        self.assertIn('float_looking_leaf_exact_parser_queue_unresolved',kinds)
        self.assertIn('small_integer_or_flag_exact_parser_queue',kinds)
        self.assertIn('opaque_high_recurrence_exact_parser_queue',kinds)
        self.assertTrue(all(r['field_semantics_confirmed']=='False' for r in self.transitions))

    def test_kps_path_partition_is_exact(self):
        self.assertEqual(len(self.kps_paths),6)
        self.assertEqual(len(self.kps_controls),21)
        self.assertEqual(self.summary['kps_exact_parser_path_dispositions'],{
            'dxbc_program_inventory_delta':1,
            'executable_code_delta_interface_stable':3,
            'executable_code_delta_with_interface_delta':1,
            'target_added_kps':1})

    def test_kps_program_queue_excludes_metadata_only_controls(self):
        self.assertEqual(len(self.kps_programs),43)
        self.assertNotIn('nonexecutive_metadata_or_compiler_delta',{r['classification'] for r in self.kps_programs})
        self.assertEqual(self.summary['kps_exact_parser_program_queue_rows'],43)

    def test_g1em_g1t_and_shaders_remain_unresolved(self):
        self.assertEqual(len(self.carry),25)
        self.assertEqual(self.summary['unresolved_g1em_g1t_shader_rows'],25)
        self.assertTrue(all(r['write_authorized']=='False' for r in self.carry))

    def test_no_semantics_runtime_or_write(self):
        self.assertEqual(self.summary['field_semantics_confirmed_rows'],0)
        self.assertEqual(self.summary['visual_or_censorship_semantics_confirmed_rows'],0)
        self.assertEqual(self.summary['runtime_confirmed_rows'],0)
        self.assertEqual(self.summary['write_authorized_rows'],0)

    def test_metadata_only_policy(self):
        p=self.summary['policy']
        self.assertTrue(p['existing_evidence_only'])
        self.assertFalse(p['local_proprietary_payloads_read'])
        self.assertFalse(p['runtime_or_save_required'])
        self.assertFalse(p['installed_game_modified'])
        self.assertFalse(p['git_modified'])

    def test_archive_contains_no_payload_extensions(self):
        names=subprocess.run(['tar','--zstd','-tf',str(self.archive)],text=True,capture_output=True,check=True).stdout.splitlines()
        self.assertFalse(any(n.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for n in names))

    def test_next_action_is_exact_parser_work_not_runtime(self):
        self.assertIn('seven broad recurrent G1E families',self.summary['next_action'])
        self.assertIn('six non-metadata KPS paths',self.summary['next_action'])
        self.assertIn('do not require saves',self.summary['next_action'])

if __name__=='__main__': unittest.main()
