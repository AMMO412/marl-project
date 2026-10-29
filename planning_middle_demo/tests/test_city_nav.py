# -*- coding: utf-8 -*-
"""城市场景避障层测试：真实几何解析、A* 绕行、路径跟随、点位吸附。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from city_nav import NavError, build_nav, follow_path, distance, mesh_aabb


def scenario():
    return json.loads((ROOT / 'scenarios/simple_city.json')
                      .read_text(encoding='utf-8'))


class ContainerSdfTests(unittest.TestCase):
    """新 SDF（container_00_combined_scene）的 include 建筑占地与城市绕行。"""

    @classmethod
    def setUpClass(cls):
        cls.scene = json.loads((ROOT / 'scenarios/asl_city.json')
                               .read_text(encoding='utf-8'))
        cls.nav, cls.loaded = build_nav(cls.scene)

    def test_include_models_contribute_real_footprints(self):
        sources = {o['source_model'] for o in self.nav.obstacles}
        for uri in ('model://House 1', 'model://House 2', 'model://House 3',
                    'model://Office Building'):
            self.assertIn(uri, sources)
        mesh = [o for o in self.nav.obstacles if o['footprint'] == 'mesh_aabb']
        self.assertEqual(len(mesh), 6)        # 4 栋 House + 2 栋 Office
        office = [o for o in mesh if o['origin_m'][0] == -25.0][0]
        self.assertAlmostEqual(office['size_m'][0], 17.6, places=0)
        self.assertGreater(office['size_m'][2], 15.0)

    def test_mesh_aabb_uses_collada_unit_and_scale(self):
        box = mesh_aabb(ROOT.parent / '资料/接口说明/models/Office Building'
                        '/meshes/office_building.dae')
        self.assertIsNotNone(box)
        self.assertAlmostEqual(box['max'][0] - box['min'][0], 17.6, places=0)
        house = mesh_aabb(ROOT.parent / '资料/接口说明/models/House 1'
                          '/meshes/house_1.dae')
        self.assertAlmostEqual(house['max'][0] - house['min'][0], 11.0, places=0)

    def test_assault_route_must_go_around_office(self):
        # 集结区在东侧、目标在广场；直线必经 (-25,-145) 的办公楼。
        start, _ = self.nav.nearest_free([-5.0, -145.0])
        goal, _ = self.nav.nearest_free([-95.0, -145.0])
        plan = self.nav.plan(start, goal)
        self.assertFalse(plan['straight_line_ok'])
        self.assertGreater(plan['length'], plan['straight_length'] * 1.03)
        self.assertGreaterEqual(plan['min_clearance'], self.nav.radius - 1e-6)
        office = [o for o in self.nav.obstacles
                  if o['source_model'] == 'model://Office Building'
                  and o['origin_m'][0] == -25.0][0]
        xs = [p[0] for p in office['polygon']]
        ys = [p[1] for p in office['polygon']]
        for point in plan['path']:
            inside = (min(xs) < point[0] < max(xs)
                      and min(ys) < point[1] < max(ys))
            self.assertFalse(inside, '路径点落在办公楼占地内：%r' % (point,))


class ObstacleMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = scenario()
        cls.nav, cls.loaded = build_nav(cls.scene)

    def test_obstacles_come_from_sdf_boxes(self):
        ids = {o['source_model'] for o in self.nav.obstacles}
        self.assertIn('salon', ids)
        self.assertIn('law_office', ids)
        self.assertIn('thrift_shop', ids)
        self.assertIn('police_station', ids)
        for obstacle in self.nav.obstacles:
            self.assertEqual(len(obstacle['polygon']), 4)
            self.assertTrue(all(abs(v) < 1e4 for p in obstacle['polygon'] for v in p))
        self.assertEqual(self.loaded['provenance']['transform']['scale'], 0.35)

    def test_straight_line_blocked_but_path_goes_around(self):
        # rover_01 出发位到 J6 沿街点直线只有 4.1，但正穿过 salon/law_office
        # 那排商铺；绕行路径应显著变长，且全程保持膨胀半径。
        start, _ = self.nav.nearest_free([43.99, 51.22])
        goal, _ = self.nav.nearest_free([41.46, 51.22])
        plan = self.nav.plan(start, goal)
        self.assertFalse(plan['straight_line_ok'])
        self.assertGreater(plan['length'], plan['straight_length'] * 1.5)
        self.assertGreaterEqual(plan['min_clearance'], self.nav.radius - 1e-6)

    def test_every_path_segment_is_collision_free(self):
        start, _ = self.nav.nearest_free([43.99, 51.22])
        goal, _ = self.nav.nearest_free([27.36, 27.06])
        plan = self.nav.plan(start, goal)
        for a, b in zip(plan['path'], plan['path'][1:]):
            self.assertTrue(self.nav.segment_free(a, b),
                            '路径段穿过障碍：%r -> %r' % (a, b))

    def test_site_inside_building_is_snapped_out(self):
        raw = [27.36, 27.06]          # 警察局中心
        self.assertFalse(self.nav.free(raw))
        point, offset = self.nav.nearest_free(raw)
        self.assertGreater(offset, 0)
        self.assertTrue(self.nav.free(point))

    def test_unreachable_goal_is_reported(self):
        with self.assertRaises(NavError):
            self.nav.plan([29.16, 51.84], [27.36, 27.06])   # 目标在楼里

    def test_follower_reaches_goal_and_keeps_clearance(self):
        start, _ = self.nav.nearest_free([43.99, 51.22])
        goal, _ = self.nav.nearest_free([27.36, 27.06])
        plan = self.nav.plan(start, goal)
        result = follow_path(self.nav, (*start, 0.0), plan['path'], speed=0.8)
        self.assertTrue(result['arrived'])
        last = (result['trace'][-1]['x'], result['trace'][-1]['y'])
        self.assertLessEqual(distance(last, goal), 0.3)
        self.assertGreater(result['min_clearance'], 0.35)


if __name__ == '__main__':
    unittest.main()
