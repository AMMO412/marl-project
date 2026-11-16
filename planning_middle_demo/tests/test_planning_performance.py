"""Performance changes must retain exact collision and cache semantics."""
import math
import random
import unittest
from unittest.mock import patch
from city_nav import NavMap, NavError, inside, point_segment, EPS
from interop.message import parse_message
from interop.templates import decompose
from interop.routing import Router, _polygon_distance
from tests.test_interop import message, formation

class NavigationPerformanceTests(unittest.TestCase):
    def test_unreachable_static_leg_is_cached_without_poisoning_air_route(self):
        from interop.routing import NoRouteError
        boxes=[[[10,10],[11,10],[11,30],[10,30]],
               [[29,10],[30,10],[30,30],[29,30]],
               [[10,10],[30,10],[30,11],[10,11]],
               [[10,29],[30,29],[30,30],[10,30]]]
        form=formation(constraints=[dict(constraint_id='BOX%d'%i,type='no_go',applies_to='ground',area={'polygon':p}) for i,p in enumerate(boxes)])
        scene=parse_message(message(),form);router=Router(scene,decompose(scene),cell_m=1)
        with patch.object(router,'_astar',wraps=router._astar) as astar:
            with self.assertRaises(NoRouteError) as first:router.route((0,0),(20,20))
            with self.assertRaises(NoRouteError) as second:router.route((0,0),(20,20))
            self.assertEqual(str(first.exception),str(second.exception))
            self.assertEqual(astar.call_count,1)
        self.assertEqual(len(router.route((0,0),(20,20),is_air=True,altitude_m=60).path),2)

    def test_spatial_query_matches_linear_geometry_reference(self):
        obstacles=[{'polygon':[[x,y],[x+4,y],[x+4,y+4],[x,y+4]]}
                   for x in range(0,90,9) for y in range(0,90,9)]
        nav=NavMap([-2,-2,100,100],obstacles)
        def reference(point,r):
            x,y=point
            if min(x+2,100-x,y+2,100-y)<=r+EPS:return False
            for obj in obstacles:
                poly=obj['polygon']
                if inside(point,poly) or any(point_segment(point,a,b)<=r+EPS
                    for a,b in zip(poly,poly[1:]+poly[:1])):return False
            return True
        rng=random.Random(81)
        points=[(rng.uniform(-4,104),rng.uniform(-4,104)) for _ in range(400)]
        points += [(0,0),(4,4),(4.5,4),(9,9),(-2,0),(100,0)]
        for point in points:
            for radius in [0,.5,1.2]:self.assertEqual(nav.free(point,radius),reference(point,radius),(point,radius))

    def test_nearest_cache_does_not_alias_or_mix_radius_and_failures(self):
        nav=NavMap([0,0,15,15],[{'polygon':[[4,4],[6,4],[6,6],[4,6]]}],radius=.1)
        with patch.object(nav,'free',wraps=nav.free) as check:
            first,offset=nav.nearest_free([5,5],max_radius=3,step=.25)
            calls=check.call_count;again=nav.nearest_free([5,5],max_radius=3,step=.25)
            self.assertEqual(again,(first,offset));self.assertEqual(check.call_count,calls)
            first[0]=1000
            self.assertNotEqual(nav.nearest_free([5,5],max_radius=3,step=.25)[0][0],1000)
            nav.nearest_free([5,5],max_radius=3,step=.25,radius=.8)
            self.assertGreater(check.call_count,calls)
            with self.assertRaises(NavError):nav.nearest_free([5,5],max_radius=.25,step=.25)
            calls=check.call_count
            with self.assertRaises(NavError):nav.nearest_free([5,5],max_radius=.25,step=.25)
            self.assertEqual(check.call_count,calls)

    def test_raster_grid_equals_exhaustive_distance_reference(self):
        data=formation();data['constraints'].append(dict(constraint_id='TH',type='threat',
            applies_to='all',intensity=.7,area={'polygon':[[22,0],[27,0],[27,10],[22,10]]}))
        scene=parse_message(message(),data);router=Router(scene,decompose(scene),risk_weight=1)
        for air,alt in [(False,None),(True,None),(True,60)]:
            polygons=router._obstacles_for(air,alt);grid,ground,sky=router._ensure_grid(polygons)
            for j in range(router.ny):
                for i in range(router.nx):
                    point=router._center(i,j);index=j*router.nx+i
                    self.assertEqual(bool(grid[index]),any(_polygon_distance(point,poly)<router.margin_m+1e-9 for poly in polygons))
                    for threats,values in [(router.ground_threats,ground),(router.air_threats,sky)]:
                        value=max([0]+[intensity for poly,intensity in threats
                            if _polygon_distance(point,poly)<=router.threat_clearance_m+1e-9])
                        self.assertEqual(values[index],value)
