import unittest

from workbench_scene import scene_map
from sdf_state import DEFAULT_SDF


class SceneMapTests(unittest.TestCase):
    def test_complete_sdf_backdrop_and_missing_terrain(self):
        result = scene_map({'_meta': {'sdf': str(DEFAULT_SDF)}})
        self.assertEqual(len(result['obstacles']), 39)
        self.assertEqual(len(result['roads']), 5)
        self.assertEqual(len(result['surfaces']), 1)
        self.assertEqual(len(result['landmarks']), 14)
        self.assertEqual(sum(x['missing_geometry'] for x in result['landmarks']), 3)
        self.assertEqual(sum(x['source'] == 'mesh_aabb' for x in result['obstacles']), 6)

    def test_scaled_scene_keeps_backdrop_in_same_coordinates(self):
        plain = scene_map({'_meta': {'sdf': str(DEFAULT_SDF)}})
        moved = scene_map({'_meta': {'sdf': str(DEFAULT_SDF), 'scale': 2,
                                    'offset_x': 10, 'offset_y': -20}})
        for collection in ('obstacles', 'roads', 'surfaces'):
            x, y = plain[collection][0]['polygon'][0]
            self.assertEqual(moved[collection][0]['polygon'][0], [2*x+10, 2*y-20])
        x, y = plain['landmarks'][0]['pose'][:2]
        self.assertEqual(moved['landmarks'][0]['pose'][:2], [2*x+10, 2*y-20])

    def test_unrelated_scene_does_not_receive_container_map(self):
        self.assertIsNone(scene_map({'_meta': {'sdf': 'other.sdf'}}))
        self.assertIsNone(scene_map({'_meta': {'interop': {'formation': {
            'meta': {'scene': 'other', 'source_sdf': DEFAULT_SDF.name}}}}}))

    def test_interop_input_not_changed(self):
        scenario = {'_meta': {'interop': {'formation': {'meta': {
            'scene': 'container_00', 'source_sdf': DEFAULT_SDF.name},
            'constraints': []}}}}
        self.assertEqual(len(scene_map(scenario)['obstacles']), 39)
        self.assertEqual(scenario['_meta']['interop']['formation']['constraints'], [])
