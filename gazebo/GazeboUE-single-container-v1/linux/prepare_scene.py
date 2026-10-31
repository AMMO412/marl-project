"""Generate the 50-robot physics scene from a portable or legacy base scene."""
from pathlib import Path
import xml.etree.ElementTree as ET
import copy
import hashlib
import json
import math
import os
import random
import re
import time

from combined_environment import apply_combined_environment

destination = Path(__file__).parent / 'rover_ue.sdf'
legacy_source = Path('/home/ubuntu/ros2_ws/src/simple_camera_rover/worlds/rover.sdf')
configured_source = os.environ.get('GAZEBO_UE_BASE_SCENE')
source = Path(configured_source) if configured_source else (legacy_source if legacy_source.is_file() else destination)
plugin_path = os.environ.get(
    'GAZEBO_UE_PLUGIN_PATH',
    '/home/ubuntu/ros2_ws/build/stamped_pose/libStampedPosePublisher.so',
)
root = ET.parse(source).getroot()
world = root.find('world')
instance_id = os.environ.get('GAZEBO_INSTANCE_ID', 'container_00')
if not re.fullmatch(r'container_\d{2}', instance_id):
    raise ValueError(f'GAZEBO_INSTANCE_ID must match container_NN, got {instance_id!r}')
world.set('name', instance_id)


def env_enabled(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


randomization_enabled = env_enabled('GAZEBO_UE_DOMAIN_RANDOMIZATION')
randomization_seed = os.environ.get('GAZEBO_UE_RANDOM_SEED', '118')
episode_id = os.environ.get('GAZEBO_UE_EPISODE_ID', '').strip()
if randomization_enabled and not episode_id:
    episode_id = str(time.time_ns())
randomization_manifest = {
    'enabled': randomization_enabled,
    'instance_id': instance_id,
    'episode_id': episode_id or None,
    'base_seed': randomization_seed,
    'models': [],
}


def set_child_text(parent, tag, value):
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = f'{value:.9g}'


def apply_domain_randomization(model_element, model_name):
    if not randomization_enabled:
        return
    seed_material = f'{randomization_seed}|{episode_id}|{instance_id}|{model_name}'
    derived_seed = int.from_bytes(
        hashlib.sha256(seed_material.encode('utf-8')).digest()[:8], 'big'
    )
    generator = random.Random(derived_seed)
    mass_scale = generator.uniform(0.85, 1.15)
    friction = generator.uniform(0.6, 1.4)
    restitution = generator.uniform(0.0, 0.15)
    total_mass = 0.0
    for inertial in model_element.findall('.//inertial'):
        mass = inertial.find('mass')
        if mass is not None and mass.text:
            scaled_mass = float(mass.text) * mass_scale
            mass.text = f'{scaled_mass:.9g}'
            total_mass += scaled_mass
        inertia = inertial.find('inertia')
        if inertia is not None:
            for tag in ('ixx', 'ixy', 'ixz', 'iyy', 'iyz', 'izz'):
                element = inertia.find(tag)
                if element is not None and element.text:
                    element.text = f'{float(element.text) * mass_scale:.9g}'
    for collision in model_element.findall('.//collision'):
        surface = collision.find('surface')
        if surface is None:
            surface = ET.SubElement(collision, 'surface')
        friction_element = surface.find('friction')
        if friction_element is None:
            friction_element = ET.SubElement(surface, 'friction')
        ode = friction_element.find('ode')
        if ode is None:
            ode = ET.SubElement(friction_element, 'ode')
        set_child_text(ode, 'mu', friction)
        set_child_text(ode, 'mu2', friction)
        bounce = surface.find('bounce')
        if bounce is None:
            bounce = ET.SubElement(surface, 'bounce')
        set_child_text(bounce, 'restitution_coefficient', restitution)
    randomization_manifest['models'].append({
        'name': model_name,
        'seed': derived_seed,
        'mass_scale': mass_scale,
        'total_mass': total_mass,
        'friction_mu': friction,
        'restitution_coefficient': restitution,
    })

# Fortress uses the historical Ignition API names while Harmonic uses gz-sim.
# Select the installed generation without duplicating the scene generator.
gazebo_generation = os.environ.get('GAZEBO_UE_GZ_GENERATION', 'fortress').lower()
if gazebo_generation not in ('fortress', 'harmonic'):
    raise ValueError(f'Unsupported GAZEBO_UE_GZ_GENERATION={gazebo_generation!r}')
if gazebo_generation == 'harmonic':
    for existing_plugin in root.iter('plugin'):
        filename = existing_plugin.get('filename', '')
        name = existing_plugin.get('name', '')
        existing_plugin.set('filename', filename.replace('ignition-gazebo-', 'gz-sim-'))
        existing_plugin.set('name', name.replace('ignition::gazebo::', 'gz::sim::'))

sensor_plugin_filename = 'gz-sim-sensors-system' if gazebo_generation == 'harmonic' else 'ignition-gazebo-sensors-system'
sensor_plugin_name = 'gz::sim::systems::Sensors' if gazebo_generation == 'harmonic' else 'ignition::gazebo::systems::Sensors'
velocity_plugin_filename = 'gz-sim-velocity-control-system' if gazebo_generation == 'harmonic' else 'ignition-gazebo-velocity-control-system'
velocity_plugin_name = 'gz::sim::systems::VelocityControl' if gazebo_generation == 'harmonic' else 'ignition::gazebo::systems::VelocityControl'

# Run faster than wall time when the host has enough CPU capacity.  Keep these
# values configurable so performance and fidelity can be swept without editing
# the generated SDF.  A 5 ms step is the first acceptance-performance profile;
# use a smaller step for scenarios whose contact dynamics need more accuracy.
max_step_size = float(os.environ.get('GAZEBO_UE_MAX_STEP_SIZE', '0.005'))
real_time_factor = float(os.environ.get('GAZEBO_UE_REAL_TIME_FACTOR', '2.0'))
if not math.isfinite(max_step_size) or max_step_size <= 0:
    raise ValueError(f'GAZEBO_UE_MAX_STEP_SIZE must be positive, got {max_step_size!r}')
if not math.isfinite(real_time_factor) or real_time_factor <= 0:
    raise ValueError(f'GAZEBO_UE_REAL_TIME_FACTOR must be positive, got {real_time_factor!r}')
physics = world.find('physics')
if physics is None:
    physics = ET.Element('physics', name='fast_physics', type='ignored')
    world.insert(0, physics)
else:
    physics.set('name', physics.get('name', 'fast_physics'))
    physics.set('type', 'ignored')
for tag, value in (
    ('max_step_size', f'{max_step_size:.9g}'),
    ('real_time_factor', f'{real_time_factor:.9g}'),
):
    element = physics.find(tag)
    if element is None:
        element = ET.SubElement(physics, tag)
    element.text = value
# An inherited update-rate cap can override the requested speed profile.
for element in list(physics.findall('real_time_update_rate')):
    physics.remove(element)

if os.environ.get('GAZEBO_UE_ENVIRONMENT', 'flat') == 'combined':
    apply_combined_environment(world)

# Gazebo is the physics authority. Rendering belongs to UE by default, so the
# generated server world contains no rendering sensors or Sensors system. A
# comma-separated allowlist can opt individual Gazebo sensors back in when a
# task genuinely needs their data (for example, a depth or segmentation feed).
sensor_allowlist = {
    name.strip()
    for name in os.environ.get('GAZEBO_UE_SENSOR_ALLOWLIST', '').split(',')
    if name.strip()
}
for link in world.findall('.//link'):
    for sensor in list(link.findall('sensor')):
        if sensor.get('name', '') not in sensor_allowlist:
            link.remove(sensor)
remaining_sensors = world.findall('.//sensor')
sensor_plugins = [
    plugin for plugin in world.findall('plugin')
    if plugin.get('name') == sensor_plugin_name
]
if not remaining_sensors:
    for plugin in sensor_plugins:
        world.remove(plugin)
elif not sensor_plugins:
    plugin = ET.Element(
        'plugin',
        filename=sensor_plugin_filename,
        name=sensor_plugin_name,
    )
    ET.SubElement(plugin, 'render_engine').text = os.environ.get(
        'GAZEBO_UE_SENSOR_RENDER_ENGINE', 'ogre2'
    )
    world.insert(0, plugin)
model = world.find("model[@name='rover']")
if model is None:
    # A checked-in generated scene is also a valid portable seed.
    # as the base model and discard all previously generated fleet members.
    model = world.find("model[@name='robot_001']")
    if model is None:
        model = world.find("model[@name='rover_01']")
    if model is None:
        raise RuntimeError(f'No rover, robot_001 or rover_01 model found in {source}')
    model = copy.deepcopy(model)
    model.set('name', 'rover')
    for element in model.iter():
        if element.text:
            element.text = element.text.replace('/robot_001/', '/rover/').replace('robot_001/odom', 'rover/odom')
            element.text = element.text.replace('/rover_01/', '/rover/').replace('rover_01/odom', 'rover/odom')
    for fleet_model in list(world.findall('model')):
        if fleet_model.get('name', '').startswith(('rover_', 'robot_')):
            world.remove(fleet_model)
else:
    world.remove(model)
for plugin in list(model.findall('plugin')):
    if plugin.get('name') in ('StampedPosePublisher', 'ignition::gazebo::systems::PosePublisher', 'gz::sim::systems::PosePublisher'):
        model.remove(plugin)
for i in range(50):
    clone = copy.deepcopy(model)
    name = f'robot_{i+1:03d}'
    clone.set('name', name)
    kind='ugv' if i<20 else 'tank' if i<30 else 'plane' if i<40 else 'flying_wing'
    height=.35 if i<30 else 6 if i<40 else 10
    if i>=30:
        clone=ET.fromstring(f'''<model name="{name}"><pose/>
          <link name="body"><gravity>false</gravity><inertial><mass>2</mass>
          <inertia><ixx>0.5</ixx><iyy>0.5</iyy><izz>0.8</izz></inertia></inertial>
          <collision name="body"><geometry><box><size>1 2 0.2</size></box></geometry></collision>
          </link><plugin filename="{velocity_plugin_filename}" name="{velocity_plugin_name}">
          <topic>/{name}/cmd_vel</topic></plugin></model>''')
    clone.find('pose').text = f'{-5*(i//10)} {5*(i%10)-22.5} {height} 0 0 0'
    if i>=20:
        for link in clone.findall('link'):
            for visual in list(link.findall('visual')):link.remove(visual)
        parent=clone.find("link[@name='chassis']") if i<30 else clone.find('link')
        mesh_path=(Path(__file__).resolve().parent.parent/'assets/converted'/f'{kind}.obj')
        if not mesh_path.is_file():raise FileNotFoundError(mesh_path)
        visual=ET.SubElement(parent,'visual',name='downloaded_model')
        ET.SubElement(visual,'pose').text='0.151427 0 -0.175 0 0 0' if i<30 else '0 0 0 0 0 0'
        geom=ET.SubElement(visual,'geometry');mesh=ET.SubElement(geom,'mesh')
        ET.SubElement(mesh,'uri').text=str(mesh_path)
    for plugin in list(clone.findall('plugin')):
        if plugin.get('name') in ('ignition::gazebo::systems::PosePublisher', 'gz::sim::systems::PosePublisher'):
            clone.remove(plugin)
    ET.SubElement(clone, 'plugin', filename=plugin_path, name='StampedPosePublisher')
    for element in clone.iter():
        if element.text:
            element.text = element.text.replace('/rover/', f'/{name}/').replace('rover/odom', f'{name}/odom')
    apply_domain_randomization(clone, name)
    world.append(clone)
ET.indent(root)
ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)
print(destination)
runtime_dir = Path(os.environ.get('GAZEBO_UE_RUNTIME_DIR', Path(__file__).parent))
runtime_dir.mkdir(parents=True, exist_ok=True)
(runtime_dir / 'domain_randomization.json').write_text(
    json.dumps(randomization_manifest, indent=2), encoding='utf-8'
)
roster=[dict(number=i+1,instance_id=instance_id,name=f'robot_{i+1:03d}',
             id=f'{instance_id}/robot_{i+1:03d}',
             type='ugv' if i<20 else 'tank' if i<30 else 'plane' if i<40 else 'flying_wing',
             cmd_vel=f'/robot_{i+1:03d}/cmd_vel') for i in range(50)]
(Path(__file__).parent.parent/'fleet-roster.json').write_text(json.dumps(roster,indent=2),encoding='utf-8')
