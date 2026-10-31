"""Build the shared outdoor environment used by the mixed robot fleet.

The source worlds are treated as reusable models inside one master world.  This
avoids duplicated physics, lighting and system plugins from stacking complete
world files on top of one another.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


ENV_PREFIX = "env_"


def _material(parent: ET.Element, rgba: str) -> None:
    material = ET.SubElement(parent, "material")
    ET.SubElement(material, "ambient").text = rgba
    ET.SubElement(material, "diffuse").text = rgba


def _static_box(
    world: ET.Element,
    name: str,
    pose: tuple[float, float, float, float, float, float],
    size: tuple[float, float, float],
    rgba: str,
    *,
    collide: bool = True,
) -> ET.Element:
    model = ET.SubElement(world, "model", name=f"{ENV_PREFIX}{name}")
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = " ".join(str(value) for value in pose)
    link = ET.SubElement(model, "link", name="link")
    if collide:
        collision = ET.SubElement(link, "collision", name="collision")
        geometry = ET.SubElement(collision, "geometry")
        box = ET.SubElement(geometry, "box")
        ET.SubElement(box, "size").text = " ".join(str(value) for value in size)
    visual = ET.SubElement(link, "visual", name="visual")
    geometry = ET.SubElement(visual, "geometry")
    box = ET.SubElement(geometry, "box")
    ET.SubElement(box, "size").text = " ".join(str(value) for value in size)
    _material(visual, rgba)
    return model


def _include(
    world: ET.Element,
    name: str,
    uri: str,
    pose: tuple[float, float, float, float, float, float],
    scale: tuple[float, float, float] | None = None,
) -> None:
    include = ET.SubElement(world, "include")
    ET.SubElement(include, "name").text = f"{ENV_PREFIX}{name}"
    ET.SubElement(include, "uri").text = uri
    ET.SubElement(include, "pose").text = " ".join(str(value) for value in pose)
    if scale is not None:
        ET.SubElement(include, "scale").text = " ".join(str(value) for value in scale)


def _heightmap_collision(
    world: ET.Element,
    name: str,
    uri: str,
    pose: tuple[float, float, float, float, float, float],
    size: tuple[float, float, float],
    pos: tuple[float, float, float],
) -> None:
    """Add a physics-only heightmap for the headless Gazebo authority."""
    model = ET.SubElement(world, "model", name=f"{ENV_PREFIX}{name}")
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = " ".join(str(value) for value in pose)
    link = ET.SubElement(model, "link", name="link")
    collision = ET.SubElement(link, "collision", name="collision")
    geometry = ET.SubElement(collision, "geometry")
    heightmap = ET.SubElement(geometry, "heightmap")
    ET.SubElement(heightmap, "uri").text = uri
    ET.SubElement(heightmap, "size").text = " ".join(str(value) for value in size)
    ET.SubElement(heightmap, "pos").text = " ".join(str(value) for value in pos)


def _clear_previous_environment(world: ET.Element) -> None:
    for model in list(world.findall("model")):
        name = model.get("name", "")
        if name == "ground_plane" or name.startswith("marker_") or name.startswith(ENV_PREFIX):
            world.remove(model)
    for include in list(world.findall("include")):
        name = include.findtext("name", "")
        if name.startswith(ENV_PREFIX):
            world.remove(include)


def _add_walls_zone(world: ET.Element) -> None:
    """Recreate the PX4 walls test geometry in a dedicated outdoor zone."""
    origin_x, origin_y = 105.0, -82.0
    official_walls = (
        ("walls_north", (5, 0, 7.5), (1, 20, 15)),
        ("walls_west", (-3, 5, 7.5), (10, 1, 15)),
        ("walls_south", (13, -10, 7.5), (17, 1, 15)),
        ("walls_east", (12, 0, 7.5), (1, 20, 15)),
    )
    for name, pose, size in official_walls:
        _static_box(
            world,
            name,
            (origin_x + pose[0], origin_y + pose[1], pose[2], 0, 0, 0),
            size,
            "0.38 0.40 0.43 1",
        )
    # Low obstacles make the same zone useful to ground vehicles, not only UAVs.
    for index, (x, y, sx, sy) in enumerate(
        ((80, -106, 8, 2), (90, -60, 2, 10), (120, -57, 12, 2), (135, -100, 2, 14)),
        start=1,
    ):
        _static_box(
            world,
            f"walls_low_{index}",
            (x, y, 1.0, 0, 0, 0),
            (sx, sy, 2),
            "0.55 0.32 0.16 1",
        )


def _add_city_zone(world: ET.Element) -> None:
    """Lay out pinned Gazebo Fuel buildings around a simple road grid."""
    # Asphalt roads and a central square are local primitives so navigation does
    # not depend on visual-only collision geometry inside downloaded buildings.
    for name, pose, size in (
        ("city_road_ns", (-95, -145, 0.03, 0, 0, 0), (14, 110, 0.06)),
        ("city_road_ew", (-95, -145, 0.04, 0, 0, 0), (140, 14, 0.08)),
        ("city_square", (-95, -145, 0.05, 0, 0, 0), (34, 34, 0.1)),
    ):
        _static_box(world, name, pose, size, "0.12 0.13 0.14 1")

    buildings = (
        ("city_house_01", "model://House 1", (-137, -185, 0, 0, 0, 0)),
        ("city_house_02", "model://House 2", (-53, -185, 0, 0, 0, 3.14159)),
        ("city_house_03", "model://House 3", (-137, -105, 0, 0, 0, 0)),
        ("city_house_04", "model://House 1", (-53, -105, 0, 0, 0, 3.14159)),
        ("city_office_01", "model://Office Building", (-165, -145, 0, 0, 0, 1.5708)),
        ("city_office_02", "model://Office Building", (-25, -145, 0, 0, 0, -1.5708)),
    )
    for name, uri, pose in buildings:
        _include(world, name, uri, pose)


def apply_combined_environment(world: ET.Element) -> None:
    """Replace the flat test world with five connected outdoor zones."""
    _clear_previous_environment(world)

    # The shared collision floor also acts as the PX4 lawn test zone around the
    # fleet spawn point.  Imported terrain models add their own local collision.
    _static_box(
        world,
        "lawn_ground",
        (0, 0, -0.25, 0, 0, 0),
        (580, 460, 0.5),
        "0.28 0.48 0.18 1",
    )

    # Main connectors between the fleet lawn, walls, city, valley and wetlands.
    for name, pose, size in (
        ("road_east_west", (0, 0, 0.03, 0, 0, 0), (330, 8, 0.06)),
        ("road_north_south", (0, 0, 0.03, 0, 0, 0), (8, 250, 0.06)),
    ):
        _static_box(world, name, pose, size, "0.16 0.17 0.18 1")

    # Fill the road edges while preserving a 70 x 70 m obstacle-free fleet
    # staging area around the origin. These low markers are useful obstacles for
    # ground robots and visually match the UE roadside planting.
    roadside_points = (
        (55, 14), (55, -14), (80, 14), (80, -14),
        (105, 14), (105, -14), (130, 14), (130, -14),
        (14, 55), (-14, 55), (14, 80), (-14, 80),
        (14, 105), (-14, 105), (14, -55), (-14, -55),
        (14, -80), (-14, -80), (14, -105), (-14, -105),
    )
    for index, (x, y) in enumerate(roadside_points, start=1):
        _static_box(
            world,
            f"roadside_planter_{index:02d}",
            (x, y, 0.6, 0, 0, 0),
            (2.4, 2.4, 1.2),
            "0.10 0.30 0.06 1",
        )

    _add_walls_zone(world)
    _add_city_zone(world)

    # Official Open Robotics Fuel terrain models, downloaded and pinned by
    # fetch_environment_assets.py.  Offsets follow the PX4 Baylands world and
    # leave the central lawn clear for the 50-robot spawn grid.
    # Two compressed Baylands copies hug the west road from both sides while
    # leaving the road itself and the fleet staging square unobstructed.
    _include(world, "wetlands_north", "model://baylands", (-150, 50, -0.5, 0, 0, 0), (0.76, 0.46, 0.65))
    _include(world, "wetlands_south", "model://baylands", (-150, -50, -0.5, 0, 0, 3.14159), (0.76, 0.46, 0.65))
    # The legacy Yosemite visual has no normal map and resolves its SDF default
    # marker as a URI in Harmonic. Gazebo is headless here, so keep the terrain
    # collision while UE remains the visual authority.
    _heightmap_collision(
        world,
        "yosemite",
        "model://yosemite/media/yosemite_elevation.png",
        (145, 90, 0, 0, 0, 0),
        (280, 280, 90),
        (0, 0, -10),
    )

    # Colored beacons make zone boundaries easy to identify in Gazebo and UE.
    for name, pose, color in (
        ("beacon_lawn", (0, 35, 3, 0, 0, 0), "0.2 1 0.2 1"),
        ("beacon_walls", (80, -45, 3, 0, 0, 0), "1 0.55 0.1 1"),
        ("beacon_city", (-70, -45, 3, 0, 0, 0), "0.2 0.5 1 1"),
        ("beacon_wetlands", (-70, 40, 3, 0, 0, 0), "0.1 0.9 0.9 1"),
        ("beacon_yosemite", (70, 40, 3, 0, 0, 0), "0.8 0.3 1 1"),
    ):
        _static_box(world, name, pose, (1.5, 1.5, 6), color)
