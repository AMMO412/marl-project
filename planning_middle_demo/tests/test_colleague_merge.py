"""Static editor templates retain their execution semantics after integration."""
from copy import deepcopy
import unittest
import workbench_server as backend
from workbench_task_editor import editor_task_types
from interop.message import parse_message
from interop.runtime import to_v2_dict
from interop.templates import decompose

class ColleagueMergeTests(unittest.TestCase):
    def draft(self, kind):
        message, formation = backend.interop_inputs_for('interop_recon')
        message['tasks'] = [deepcopy(editor_task_types()[kind]['demo'])]
        return message, formation

    def test_unbound_recon_seats_reach_execution_as_role_points(self):
        message, formation = self.draft('T-RCN')
        scene = parse_message(message, formation)
        job = to_v2_dict(scene)['jobs'][0]
        roles = {slot.role for slot in decompose(scene)}
        self.assertEqual(set(job['_behavior']['search_points_by_role']), roles)
        self.assertTrue(job['_behavior']['tracking_target']['move_after_contact'])

    def test_containment_editor_target_clock_reaches_runtime(self):
        message, formation = self.draft('T-SEC')
        behavior = to_v2_dict(parse_message(message, formation))['jobs'][0]['_behavior']
        self.assertEqual(behavior['target_start_mode'], 'after_control')

    def test_category_and_platform_locks_survive_decomposition(self):
        from interop.templates import slot_keys
        message, formation = self.draft('T-RCN')
        initial = decompose(parse_message(message, formation))
        key = slot_keys(initial)[0]
        message['tasks'][0]['params']['_slot_units'] = {key: {'platform_class': 'WING'}}
        slots = decompose(parse_message(message, formation))
        self.assertEqual(slots[0].pinned_class, 'WING')
        message['tasks'][0]['params']['_slot_units'] = {key: 'rover_41'}
        self.assertEqual(decompose(parse_message(message, formation))[0].pinned_unit, 'rover_41')
