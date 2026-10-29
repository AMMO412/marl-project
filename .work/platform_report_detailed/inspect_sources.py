from pathlib import Path
from urllib.request import urlopen, Request
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
import json

root=Path(__file__).parent/'sources'
urls={
'rc_cessna.sdf':'https://raw.githubusercontent.com/PX4/PX4-gazebo-models/main/models/rc_cessna/model.sdf',
'zephyr.sdf':'https://raw.githubusercontent.com/ArduPilot/ardupilot_gazebo/main/models/zephyr/model.sdf',
'zephyr_with_ardupilot.sdf':'https://raw.githubusercontent.com/ArduPilot/ardupilot_gazebo/main/models/zephyr_with_ardupilot/model.sdf',
'VelocityControl.cc':'https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8/src/systems/velocity_control/VelocityControl.cc',
'LinearBatteryPlugin.cc':'https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8/src/systems/battery_plugin/LinearBatteryPlugin.cc',
'DiffDrive.cc':'https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8/src/systems/diff_drive/DiffDrive.cc',
'LiftDrag.cc':'https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8/src/systems/lift_drag/LiftDrag.cc',
}
def fetch(item):
    name,url=item
    try:
        data=urlopen(Request(url,headers={'User-Agent':'Codex research'}),timeout=40).read()
        (root/name).write_bytes(data)
        return name,len(data)
    except Exception as e: return name,str(e)
print(list(ThreadPoolExecutor(7).map(fetch,urls.items())))
for name in ['rc_cessna.sdf','zephyr.sdf','zephyr_with_ardupilot.sdf']:
    model=ET.parse(root/name).getroot().find('model')
    print('\nMODEL',name)
    print('LINK MASSES',[(x.attrib['name'],x.findtext('inertial/mass')) for x in model.findall('link')])
    print('PLUGINS',[(x.attrib.get('name'),x.findtext('area'),x.findtext('cla'),x.findtext('alpha_stall')) for x in model.findall('plugin')])
for name, terms in [('LinearBatteryPlugin.cc',['start_drain','BatterySoC','JointVelocityCmd','SetData','power_load','BatteryPowerLoad']),('DiffDrive.cc',['BatterySoC','min_linear_velocity','JointVelocityCmd']),('LiftDrag.cc',['cl =','cd =','alphaStall','control_joint_rad_to_cl'])]:
    print('\nSOURCE',name)
    lines=(root/name).read_text().splitlines()
    for i,line in enumerate(lines):
        if any(t in line for t in terms): print(i+1,line.strip())
(root/'sources.json').write_text(json.dumps(urls,indent=2),encoding='utf-8')
