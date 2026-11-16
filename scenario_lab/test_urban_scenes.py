import math
import unittest
import xml.etree.ElementTree as ET
from urban_scenes import PRESETS, make_map, make_case, intersects, graph, sdf


class UrbanScenesTests(unittest.TestCase):
    def test_maps_and_twenty_seeds(self):
        for kind in PRESETS:
            data=make_map(kind)
            self.assertGreater(len(data['buildings']),100)
            self.assertEqual(data['sha256'],make_map(kind)['sha256'])
            world=ET.fromstring(sdf(data)).find('world')
            self.assertEqual(len(world.findall('.//collision')),1+len(data['buildings'])+len(data['obstacles']))
            adjacency=graph(data);visited={0};front=[0]
            while front:
                for node,_ in adjacency[front.pop()]:
                    if node not in visited:visited.add(node);front.append(node)
            self.assertEqual(len(visited),len(data['nodes']))
            for seed in range(20):
                case=make_case(data,seed)
                self.assertEqual(case,make_case(data,seed))
                self.assertEqual(len(case['tasks']),8)
                x0,y0,x1,y1=case['zone']
                for task in case['tasks']:
                    x,y=task['position'];self.assertTrue(x0<x<x1 and y0<y<y1)
                for route in case['reference_routes']:
                    self.assertTrue(route['start_s']<=route['arrival_s']<route['end_s'])
                    window=next(task['window_s'] for task in case['tasks'] if task['id']==route['task_id'])
                    self.assertTrue(window[0]<=route['arrival_s']<route['end_s']<=window[1])
                    for a,b in zip(route['path'],route['path'][1:]):
                        for obstacle in data['buildings']+data['obstacles']:
                            self.assertFalse(intersects(a,b,obstacle['box'],1), (kind,seed,obstacle['id']))


if __name__=='__main__':unittest.main()
