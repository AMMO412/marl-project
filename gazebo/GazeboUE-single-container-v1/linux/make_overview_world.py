"""Add a temporary top-down RGB camera to a generated Gazebo world."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--exclude-include",
        action="append",
        default=[],
        help="Remove includes whose name or URI contains this text.",
    )
    parser.add_argument(
        "--camera-pose",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        default=(0.0, 0.0, 1400.0),
    )
    parser.add_argument(
        "--camera-rpy",
        nargs=3,
        type=float,
        metavar=("ROLL", "PITCH", "YAW"),
        default=(0.0, 1.57079632679, 0.0),
    )
    parser.add_argument("--fov", type=float, default=1.8)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    tree = ET.parse(args.source)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise RuntimeError("SDF contains no world")

    for include in list(world.findall("include")):
        identity = f"{include.findtext('name', '')} {include.findtext('uri', '')}"
        if any(token in identity for token in args.exclude_include):
            world.remove(include)

    for plugin in list(world.findall("plugin")):
        if plugin.get("name") == "ignition::gazebo::systems::Sensors":
            world.remove(plugin)
    sensors = ET.Element(
        "plugin",
        filename="ignition-gazebo-sensors-system",
        name="ignition::gazebo::systems::Sensors",
    )
    ET.SubElement(sensors, "render_engine").text = "ogre2"
    world.insert(0, sensors)

    for model in list(world.findall("model")):
        if model.get("name") == "overview_capture_camera":
            world.remove(model)

    model = ET.SubElement(world, "model", name="overview_capture_camera")
    ET.SubElement(model, "static").text = "true"
    x, y, z = args.camera_pose
    roll, pitch, yaw = args.camera_rpy
    ET.SubElement(model, "pose").text = f"{x} {y} {z} {roll} {pitch} {yaw}"
    link = ET.SubElement(model, "link", name="camera_link")
    sensor = ET.SubElement(link, "sensor", name="overview", type="camera")
    ET.SubElement(sensor, "topic").text = "/overview/image"
    ET.SubElement(sensor, "always_on").text = "true"
    ET.SubElement(sensor, "update_rate").text = "1"
    camera = ET.SubElement(sensor, "camera")
    ET.SubElement(camera, "horizontal_fov").text = str(args.fov)
    image = ET.SubElement(camera, "image")
    ET.SubElement(image, "width").text = str(args.width)
    ET.SubElement(image, "height").text = str(args.height)
    ET.SubElement(image, "format").text = "R8G8B8"
    clip = ET.SubElement(camera, "clip")
    ET.SubElement(clip, "near").text = "1"
    ET.SubElement(clip, "far").text = "4000"
    save = ET.SubElement(camera, "save", enabled="true")
    ET.SubElement(save, "path").text = "/tmp/overview_frames"

    if hasattr(ET, "indent"):
        ET.indent(root)
    tree.write(args.destination, encoding="utf-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
