from pathlib import Path
from decimal import Decimal
import xml.etree.ElementTree as ET
import hashlib, json, shutil

ROOT=Path(__file__).parent
base=Path(r'C:\Users\ammo\Desktop\MARL项目\.work\platform_report\build_report.py').read_text(encoding='utf-8')
exec(base.split("doc.add_paragraph('四类平台公开参数")[0])
OUT=Path(r'C:\Users\ammo\Desktop\MARL项目\outputs\平台参数调研\四类平台参数指标与Gazebo实现详尽调研.docx')
doc.core_properties.title='四类平台参数指标与 Gazebo 实现详尽调研'
doc.core_properties.subject='指标定义 公开数值 SDF字段 插件机制 验证方法与官方依据'

S={
1:('ROS 2 Humble Twist 消息定义','https://github.com/ros2/common_interfaces/blob/humble/geometry_msgs/msg/Twist.msg'),
2:('ros_gz_bridge Humble 消息映射与配置','https://github.com/gazebosim/ros_gz/blob/humble/ros_gz_bridge/README.md'),
3:('ROS REP 103 单位与坐标约定','https://github.com/ros-infrastructure/rep/blob/master/rep-0103.rst'),
4:('SDF 1.9 Link 定义','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/link.sdf'),
5:('SDF 1.9 惯性与重心定义','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/inertial.sdf'),
6:('SDF 1.9 Joint 限制与阻尼定义','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/joint.sdf'),
7:('SDF 1.9 Surface 接触与摩擦定义','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/surface.sdf'),
8:('Gazebo Sim 8 DiffDrive 参数接口','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1DiffDrive.html'),
9:('gz-sim8 DiffDrive 实现源码','https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/diff_drive/DiffDrive.cc'),
10:('Gazebo Sim 8 TrackedVehicle 参数接口','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1TrackedVehicle.html'),
11:('TrackController 原理及能力边界','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1TrackController.html'),
12:('gz-sim8 履带车辆完整示例','https://github.com/gazebosim/gz-sim/blob/gz-sim8/examples/worlds/tracked_vehicle_simple.sdf'),
13:('Gazebo Sim 8 VelocityControl 参数接口','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1VelocityControl.html'),
14:('gz-sim8 VelocityControl 实现源码','https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/velocity_control/VelocityControl.cc'),
15:('Gazebo Sim 8 LiftDrag 参数接口','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1LiftDrag.html'),
16:('gz-sim8 LiftDrag 受力计算源码','https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/lift_drag/LiftDrag.cc'),
17:('PX4 rc_cessna 完整 SDF','https://github.com/PX4/PX4-gazebo-models/blob/main/models/rc_cessna/model.sdf'),
18:('PX4 新 Gazebo 支持的机型','https://docs.px4.io/main/en/sim_gazebo_gz/vehicles'),
19:('ArduPilot Zephyr 基础模型 SDF','https://github.com/ArduPilot/ardupilot_gazebo/blob/main/models/zephyr/model.sdf'),
20:('Zephyr 气动与飞控扩展 SDF','https://github.com/ArduPilot/ardupilot_gazebo/blob/main/models/zephyr_with_ardupilot/model.sdf'),
21:('ArduPilot SITL 与 Gazebo 官方接入','https://ardupilot.org/dev/docs/sitl-with-gazebo.html'),
22:('Gazebo LinearBatteryPlugin 参数接口','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1LinearBatteryPlugin.html'),
23:('gz-sim8 LinearBatteryPlugin 实现源码','https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/battery_plugin/LinearBatteryPlugin.cc'),
24:('Gazebo 电池教程与已知限制','https://gazebosim.org/api/sim/8/battery.html'),
25:('SDF 1.9 Sensor 类型 频率与话题','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/sensor.sdf'),
26:('SDF 1.9 Camera 成像参数','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/camera.sdf'),
27:('SDF 1.9 Physics 时间步定义','https://github.com/gazebosim/sdformat/blob/sdf12/sdf/1.9/physics.sdf'),
28:('Gazebo Sim 8 物理引擎支持说明','https://gazebosim.org/api/sim/8/physics.html'),
29:('Gazebo PosePublisher 位姿发布','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1PosePublisher.html'),
30:('KNDS Leopard 2 A7V 公开性能表','https://knds.com/en/products/systems/leopard/leopard-2-a7'),
31:('Milrem 2024 产品目录 印刷页7','https://d3tr2q1wj7u3d5.cloudfront.net/32284/20240611_MILREM-Product-Catalogue-EN_web.pdf'),
32:('Clearpath Husky A200 官方手册','https://docs.clearpathrobotics.com/docs_robots/outdoor_robots/husky/a200/user_manual_husky/'),
33:('Clearpath 官方 Gazebo 仿真概览','https://docs.clearpathrobotics.com/docs/ros/tutorials/simulator/overview/'),
34:('Gazebo 与 ROS 发行版配对说明','https://gazebosim.org/docs/harmonic/ros_installation/'),
35:('Gazebo 官方传感器配置教程','https://gazebosim.org/docs/harmonic/sensors/'),
}

def refs(*ids):
    a=doc.add_paragraph(); a.paragraph_format.space_after=Pt(4)
    a.add_run('依据链接  ').font.size=Pt(8)
    for n in ids:
        hyperlink(a,f'[{n}] {S[n][0]}',S[n][1])
        a.add_run('  ')
    for r in a.runs:r.font.size=Pt(8)
    for size in a._p.iter(qn('w:sz')):size.set(qn('w:val'),'16')

def code(text):
    a=doc.add_paragraph(); a.paragraph_format.space_after=Pt(7); a.paragraph_format.line_spacing=Pt(11)
    r=a.add_run(text);r.font.name='Consolas';r.font.size=Pt(8.5)
    r._element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'微软雅黑')

def pg(title):newpage(title)

# 1
doc.add_paragraph('四类平台参数指标\n与 Gazebo 实现详尽调研','Title')
doc.add_paragraph('公开数据  实现机制  配置位置  验证方法','Subtitle')
p('资料核对日期  2026年10月24日',size=9)
p('核心结论：现有 50 路 cmd_vel 说明了如何发速度命令，尚不能证明模型具备某一真实平台的最大速度、载荷、续航或飞行能力。参数要经过模型、控制插件或能源逻辑实际执行，并用反馈数据核验。',boldlead='核心结论：')
table(['类型','数量与编号','当前控制方式'],[
['UGV 无人车','20 台  01–20','文件记载为差速驱动'],
['TANK 坦克','10 台  21–30','履带外观与差速轮驱动代理'],
['PLANE 常规固定翼','10 台  31–40','关闭重力与直接速度控制'],
['WING Zephyr 飞翼','10 台  41–50','关闭重力与直接速度控制'],
],[4.4,3.5,9.5])
p('信息范围：类别、编号和话题来自用户说明；代理控制方式来自《机器人移动话题说明.md》。本轮核对官方文档与公开源码，未运行用户工程。后文以 Gazebo Sim 8 为参数说明基准，实际版本仍需核对。',boldlead='信息范围：',size=9.5)
shots=list(Path(r'C:\Users\ammo\Downloads').glob('*6006350786847564828*.jpg'))
if shots:
    shutil.copyfile(shots[0],ROOT/'scene_reference.jpg')
    picture=doc.add_picture(str(ROOT/'scene_reference.jpg'),width=Cm(15.8))
    picture._inline.docPr.set('descr','用户提供的混合机器人场景截图，仅用于展示外观。')
    doc.paragraphs[-1].paragraph_format.line_spacing=1
    p('用户提供的场景截图。外观和阵列可用于展示；截图不提供质量、气动、接触或性能测试证据。',size=8.5)

# 2
pg('1 从 cmd_vel 到运动的完整链路')
p('控制链路为 ROS 2 发布器 → ros_gz_bridge 消息转换 → Gazebo Transport 话题 → 运动插件 → 物理或速度更新 → 位姿反馈 → UE 显示。桥接负责传递消息，具体运动行为由下游插件决定。[1–2]')
table(['字段','单位','当前约定与边界'],[
['linear.x','m/s','地面前后移动；飞机代理简化前后移动'],
['angular.z','rad/s','地面转向；飞机代理简化偏航'],
['linear.z','m/s','仅飞机代理的简化升降'],
['其他三个分量','m/s 或 rad/s','当前说明未开放使用，不能据消息结构推断已实现'],
['消息未携带的内容','—','目标点、持续时间、时间戳、坐标系、载荷、续航、平台型号'],
],[3.2,2.4,11.8])
p('Twist 只有 linear 和 angular 两个三维向量，没有 Header。坐标系与命令是否超时必须由接口约定和接收端实现。ROS 常用 SI 单位及机体 X 前、Y 左、Z 上约定，但不能据此跳过模型自身坐标变换检查。[1,3]')
h('话题与模型的绑定')
p('四类均使用 /rover_XX/cmd_vel。XX 为补零编号；这个名称不会让 Gazebo 自动识别机器人类型。DiffDrive 与 VelocityControl 的默认话题是 /model/模型名/cmd_vel，因此当前工程必须通过插件 topic 配置或桥接重映射实现现有名称。[8,13]')
h('桥接配置应检查什么')
code('# 说明性 YAML 片段  字段支持以所用 ros_gz 版本为准\n- ros_topic_name: /rover_01/cmd_vel\n  gz_topic_name: /rover_01/cmd_vel\n  ros_type_name: geometry_msgs/msg/Twist\n  gz_type_name: ignition.msgs.Twist\n  direction: ROS_TO_GZ')
p('Humble 分支明确支持 Twist 与 ignition::msgs::Twist 的转换。新版本常见 gz.msgs.Twist，不能仅凭名称直接替换运行配置。桥接有订阅者只证明通信连接，还须观察实际位姿变化。[2]')
refs(1,2,3,8,13)

# 3
pg('2 尺寸 质量 惯量与载荷怎样生效')
p('Gazebo 通用物理描述以 SDF 为基础。一个 model 可以有多个 link；每个 link 分别具有惯性、视觉、碰撞及传感器属性。展示外形、接触形状和运动控制相互关联，但需要分别配置。[4–7]')
table(['指标','配置位置','实现含义与核对方式'],[
['长宽高\nm','visual/geometry\ncollision/geometry','视觉影响外观，碰撞体影响接触；两者尺寸都要检查'],
['质量\nkg','link/inertial/mass','每个 link 的质量；整机应统计全部 link 及 include 模型'],
['重心\nm','link/inertial/pose','质心位置及惯性坐标朝向；改变载荷位置会改变重心'],
['惯量\nkg·m²','link/inertial/inertia','ixx、iyy、izz 与交叉项；控制转动响应，不是质量的替代值'],
['重力','link/gravity\n世界重力','false 会移除该 link 的重力影响；不能再据静止判断升力平衡'],
['接触摩擦','collision/surface','摩擦方向与滑移受物理后端支持影响，不能只检查数值存在'],
['实际载荷\nkg','新增 payload link\n固定 joint 或合并惯性','物理质量、碰撞与重心共同变化；额定载荷上限另由逻辑校验'],
],[2.5,5.2,9.7])
h('载荷需要同时表达两个含义')
p('能力上限表示允许装多少，可在配置中记录 payload_capacity_kg，并在装载时检查。实际装载量表示当前装了多少，应改变物理质量与惯量；只在 JSON 中增加一个“载荷”数字不会自动改变 Gazebo 受力。')
p('用独立载荷 link 加 fixed joint 可以保留安装位置；也可在生成 SDF 时重算合并惯性。改变质量后不能沿用不匹配的惯量。均匀盒体可用 Ixx=m(b²+c²)/12 等公式估算，但必须标为几何近似，并注意坐标轴和重心位置。')
h('缩放模型时需要一起核对')
p('只放大 mesh 不能获得同尺度物理模型。相同密度、均匀缩放 k 时，质量按 k³、惯量按 k⁵变化；这是几何推导，只有相同密度假设成立时适用。飞机气动参考面积与力作用点也要同步核对。')
refs(4,5,6,7)

# 4
pg('3 无人车 UGV 的速度与转向实现')
p('按提供文件，UGV 为差速驱动。Gazebo DiffDrive 读取线速度 v 和偏航角速度 ω，根据轮半径 r、左右轮间距 b 生成左右轮关节速度，再由接触与物理引擎更新车辆运动。[8–9]')
code('左轮角速度 = (v - ω·b/2) / r\n右轮角速度 = (v + ω·b/2) / r')
table(['指标','DiffDrive 字段','解释'],[
['轮半径 m','wheel_radius','换算线速度与轮转速，必须匹配几何'],
['轮间距 m','wheel_separation','左右轮中心距，影响转弯比例'],
['轮关节名称','left_joint / right_joint','可重复配置，分别绑定两侧车轮'],
['前后速度 m/s','min_linear_velocity\nmax_linear_velocity','显式限制前后行驶命令'],
['转向速度 rad/s','min_angular_velocity\nmax_angular_velocity','与线速度分别设置'],
['加减速度','min_linear_acceleration\nmax_linear_acceleration','线加速度单位 m/s²；角加速度另用 angular 字段'],
['速度变化平滑度','min_linear_jerk\nmax_linear_jerk','加加速度限制；不是电机力矩模型'],
['里程计频率 Hz','odom_publish_frequency','控制发布频率，不等于物理更新频率'],
],[3.0,6.5,7.9])
h('限速与驱动力并不等价')
p('DiffDrive 源码对指令限幅后写入 JointVelocityCmd。max_linear_acceleration 可以让命令逐步增加，但不会自动辨识车辆电机功率、传动效率或满载加速性能。要研究这些物理限制，须核对关节 effort、velocity、驱动控制方式与物理后端。[6,9]')
p('避免只用 max_velocity：此通用字段同时影响线速度和角速度，单位语义不同。优先使用明确的 linear 与 angular 字段，并分别设置负向速度及减速度。[8]')
h('建议如何验证')
p('在无接触干扰的平地上比较阶跃命令与模型真实速度；再做定速圆周和停止测试。用 Gazebo 真实位姿计算轨迹，并与轮式里程计分别记录。滑移时两者可能不同，不能只读 cmd_vel 就宣布达到速度。')
refs(8,9,6)

# 5
pg('4 坦克与履带平台的指标实现')
p('当前 TANK 使用履带外观加差速轮代理，其速度边界可先用差速插件管理。若需要体现履带接地，应采用 TrackedVehicle 配合每侧 TrackController；仅替换 mesh 不改变驱动原理。[10–12]')
table(['参数','配置位置','含义'],[
['履带绑定','TrackedVehicle\nleft_track / right_track','填写各侧 link 及可选速度话题'],
['履带中心距 m','tracks_separation','车辆转向几何尺度'],
['履带高度 m','track_height','用于里程计计算，不代表全部履带几何'],
['转向效率','steering_efficiency','模型转向近似参数，需通过转弯试验校准'],
['车体线速度限制','linear_velocity 子块','min/max_velocity、acceleration、jerk'],
['车体角速度限制','angular_velocity 子块','字段层级不同于 DiffDrive，不能混抄'],
['单履带速度限制','TrackController\nmin/max_velocity 等','车体和单侧限制需共同检查'],
['命令超时 s','TrackController\nmax_command_age','过期后停该履带；与重复发出的旧车体指令联动仍需测试'],
],[3.4,6.0,8.0])
h('履带插件怎样产生运动')
p('TrackController 在履带与地面接触点设置期望接触面运动，通过摩擦约束近似履带推进。它不是把履带分解成全部链节逐个传动。官方说明其仅支持速度控制，没有 effort 控制，也不模拟履齿效应。[11]')
h('爬坡 越障与最小转弯半径')
p('最大爬坡角、侧坡、越障高度和跨沟宽度通常是测试结果，并不存在一个填写“max_slope”就自动实现能力的通用 SDF 字段。要在已定义地形、摩擦、载荷与驱动条件下测试。厂家坡度 60% 等于 tan(坡角)=0.60，约为 31°，不能写为 60°。')
p('可原地转向表示几何上允许小半径运动，不代表在任意地面、任意载荷下都能无滑移转向。若仍使用轮驱代理，应在报告中保留这一近似条件。')
refs(10,11,12,7,31)

# 6
pg('5 当前飞机速度代理怎样实现指标')
p('按提供文件，两类飞机均关闭重力并使用 VelocityControl。该插件接收 Twist 后持续设置模型的线速度和角速度组件；源码未提供与 DiffDrive 相同的速度、加速度限制读取逻辑。[13–14]')
code('<!-- Gazebo Sim 8 的说明性片段  不是完整飞机模型 -->\n<plugin filename="gz-sim-velocity-control-system"\n        name="gz::sim::systems::VelocityControl">\n  <topic>/rover_31/cmd_vel</topic>\n</plugin>\n<!-- gravity 位于相应 link 中 -->\n<gravity>false</gravity>')
table(['希望表达的指标','现有代理的实现办法','能证明到哪里'],[
['最大前进与倒退速度','在统一接收/控制端校验并限幅','速度命令边界'],
['最大爬升与下降率','限制约定坐标中的 linear.z','简化运动边界，非剩余功率性能'],
['最大偏航角速度','限制 angular.z','偏航速度边界，非真实协调转弯'],
['加减速度','按仿真 dt 限制相邻速度增量','规定的速度过渡，非推力辨识'],
['最小转弯半径','在平面近似下联合限制 v 与 ω','R=|v/ω|，仅适用非零 ω 的相应运动假设'],
['高度与区域范围','读取带时间戳位姿后检查','外部约束，需要控制端实际执行'],
['巡航与失速','可记录参考范围；真实失速需气动','速度代理不能证明升力或失速'],
],[3.6,6.8,7.0])
p('工程建议：若希望所有发送方都受约束，应在统一入口集中处理，避免只修改某一个发送脚本。不能在原始 Twist 中“加上”质量或续航；这些属于独立配置与状态。以上为设计建议，未在现有工程实施。',boldlead='工程建议：')
p('VelocityControl 的 OnCmdVel 保存最新命令，更新循环持续使用该命令。发布器退出不等于接收端自动清零；失联停车、指令有效期和能源耗尽后的禁用都应明确实现并测试。物理固定翼飞行则不能把零速度当作正常停车操作。[14]')
refs(13,14,1)

# 7
pg('6 常规固定翼的公开物理模型')
p('PX4 的 rc_cessna 是常规布局固定翼参考，官方提供新 Gazebo 的运行入口。它的模型中同时存在刚体惯性、多个 LiftDrag、舵面位置控制器和推进模型，运动由受力与控制共同产生。[17–18]')
table(['参数','公开配置或计算值','口径'],[
['base_link 质量','1.5 kg','主机体 link，不是整机'],
['整机 link 质量合计','约 1.67 kg','本轮对该 SDF 直接 link/mass 求和，含轮和传感器'],
['主机体惯量','Ixx 0.197563\nIyy 0.1458929\nIzz 0.1477 kg·m²','对应 base_link 惯性坐标'],
['机体碰撞盒','0.65×0.08×0.10 m','碰撞近似，不直接等于整机外形'],
['翼部碰撞盒','0.1×1.0×0.01 m','碰撞尺寸，不是气动参考翼面积'],
['气动参数示例','某组 area=0.6 m²\ncla≈4.7528\nalpha_stall≈0.33914 rad','同模型有多组气动面，须逐组解释'],
['舵角示例','rudder_joint\n约 -0.78 至 +0.78 rad','关节行程，不是偏航速度上限'],
],[3.6,6.3,7.5])
h('空气动力怎样进入 Gazebo')
p('LiftDrag 根据 link 相对空气的运动计算迎角和动压，再计算升力与阻力并作用到指定 cp。其基本关系为 q=ρV²/2、L=qSCL、D=qSCD；迎角跨过 alpha_stall 后使用另一段系数斜率。[15–16]')
p('质量决定重量和惯性；翼面积、气动系数、推力及舵面影响飞行响应。巡航空速、爬升率与转弯半径一般要在给定载荷和环境下通过配平或飞行测试得到，不能从 Twist 字段直接读出。')
h('如何与现有接口衔接')
p('物理飞行需要控制器把期望运动转成油门与舵面指令。保留 cmd_vel 作为上层接口是可选设计，但需要新定义控制语义、坐标系和可实现范围；不能把原速度代理与气动插件同时当作同一刚体的独立运动主控。')
refs(17,18,15,16)

# 8
pg('7 Zephyr 飞翼的公开参数与实现')
p('ArduPilot 的 zephyr 基础模型包含机翼、推进器、两片舵面与 IMU link；zephyr_with_ardupilot 通过 include 引入它，再增加气动、关节施力与飞控连接。只有外观基础模型不足以构成可控飞行示例。[19–21]')
table(['参数','上游数值','所在位置或含义'],[
['主翼质量','1.5 kg','zephyr 的 wing link'],
['整机 link 质量合计','1.90 kg','1.5+0.05+0.10+0.10+0.15，本轮求和'],
['主翼重心 pose','0 -0.12 0 0 0 0','wing 的 inertial/pose，按该 link 坐标解释'],
['主翼惯量','0.083137104 /\n0.387382402 /\n0.469845106 kg·m²','依次为 Ixx、Iyy、Izz'],
['主翼气动参考面积','0.50 m²','扩展模型中的主翼一组插件'],
['主翼升力斜率','cla=3.7','失速前模型系数，不是固定升力'],
['主翼失速迎角','0.3391428111 rad\n约 19.43°','不是失速空速'],
['空气密度','1.2041 kg/m³','该气动插件的 air_density'],
['主翼压力中心','0 -0.1 0 m','cp；受力位置与质心不同'],
['前向与升力方向','forward: 0 -1 0\nupward: 0 0 1','方向定义在模型 link 坐标中'],
],[3.6,5.9,7.9],size=9)
h('飞翼和常规布局的差别怎样体现')
p('区别应通过几何、质量分布、气动面位置、控制舵面及混控关系体现。Zephyr 左右舵面分别绑定控制关节，并影响局部气动；相同或差动舵面输入产生的响应应由模型与飞控闭环验证，不能仅靠类型标签区分。')
p('当前文件用 linear.x 表示前进，而上游 Zephyr 的气动前向为 -Y，必须核对 include 的姿态变换与 link 坐标。这里名称一致仅说明有合适候选来源，不能证明现有 WING 已采用这些数值。')
p('参数读取边界：多个气动插件的 area 对应不同面和力模型，不能机械相加后宣称获得真实翼面积；修改几何或载荷后，也不能继续默认原气动与控制参数有效。',boldlead='参数读取边界：',size=9.5)
refs(19,20,21)

# 9
pg('8 续航 能耗与能源耗尽的实现')
p('续航是能源容量、功率消耗和工况共同作用的结果。Gazebo 的 LinearBatteryPlugin 可跟踪电荷、端电压和荷电状态；仅填写“续航 3 小时”不会自动生成电机消耗规律。[22–24]')
table(['字段','单位','用途'],[
['battery_name','字符串','电池标识，供消费者关联'],
['voltage','V','初始电压'],
['capacity / initial_charge','Ah','容量及初始电荷；Ah 不是 Wh'],
['power_load','W','基础功率负载，不自动等于车辆机械功率'],
['resistance','Ω','内阻与端电压变化'],
['open_circuit_voltage 系数','V 等','按插件模型描述开路电压变化'],
['start_draining','布尔','源码支持的启动耗电参数'],
['BatteryPowerLoad','运行时组件','其他消费者把附加功率汇入同一电池'],
],[6.0,2.1,9.3])
h('恒功率近似与工况')
p('理想恒电压、恒功率条件下，E≈U×C，单位 Wh；T≈E/P，单位 h。Husky A200 手册列 24 V、20 Ah、平均运行 3 h，可算出名义 480 Wh；480/3≈160 W 只是理想平均值推算，不能写成厂家实测恒定功率或实际可用能量。[24,32]')
p('若要体现速度、坡度、载荷和传感器对能耗的影响，需要建立相应功率函数或消费者。把所有平台设为同一个固定 power_load，只能验证固定功耗下的耗电行为，不能据此比较不同平台真实能效。')
h('当前速度代理有两个特殊问题')
p('第一，所查电池源码会从关节速度或力命令检测运动并启动耗电；当前飞机用模型速度组件，可能绕过这条触发路径。应显式配置耗电启动并检查 SOC 确实下降。[23]')
p('第二，官方教程的耗尽后停机描述针对关节驱动。模型级 VelocityControl 不会因为存在电池就自动获得禁飞或停止逻辑，需要单独验证能源状态是否真正影响该控制链路。[14,24]')
p('版本核对：API 页存在 start_drainign 拼写，实际所查源码读取 start_draining；教程还记录 fix_issue_225 的历史耗电倍率问题。应以安装版本源码、示例和测试结果交叉核对，不能机械复制网页字段。[22–24]',boldlead='版本核对：',size=9.5)
refs(22,23,24,32)

# 10
pg('9 传感器 时间与场景规模指标')
p('“能显示模型”“有 50 路相机”“50 台都能接收命令”分别对应显示、成像和通信。它们不自动证明物理步长、传感器频率、端到端延迟或实时因子达到目标。')
table(['指标','Gazebo 配置或测量位置','验证口径'],[
['相机视场与分辨率','sensor/camera\nhorizontal_fov、image/width、height','视场用 rad；渲染结果受安装位姿影响'],
['相机与传感器频率','sensor/update_rate','配置值与实际收到消息的频率分别记录'],
['相机可见距离','camera/clip/near、far','裁剪距离不等于识别距离或目标可探测距离'],
['IMU 定位与激光','sensor 类型及相应噪声块','需要对应系统加载、话题输出和噪声验证'],
['位姿反馈','PosePublisher 或已配置输出','区分世界真值、里程计及 UE 显示位姿'],
['物理步长','physics/max_step_size','数值积分步长，不等于控制命令周期'],
['实时因子 RTF','Δ仿真时间 / Δ墙钟时间','测实际值，real_time_factor 配置是目标值'],
['通信与同步误差','发送 接收 引擎应用时间戳','无 Header 的 Twist 不能独自提供消息时间戳'],
],[4.1,6.8,6.5],size=9)
h('截图和当前说明能确认到哪里')
p('截图展示了模型阵列及相机界面提示。提供文件进一步说明图像由 UE 相机输出，尚未发布为 ROS 2 Image；因此不能把 UE 相机画面自动认定为 Gazebo 传感器输出，也不能由界面提示推断 50 路实际帧率。')
h('时间与性能的测试方法')
p('位移应按仿真时间计算。恒速段可用 v≈Δs/Δt_sim，角速度可用连续解包后的 Δyaw/Δt_sim；RTF 低于 1 时，墙钟 5 秒并不等于仿真 5 秒。动态轨迹需逐段或积分统计。')
p('建议分别测试 1、10、50 台，以及开启和关闭图像的工况，记录 RTF、物理步长、消息实收频率、延迟分布、CPU/GPU 与丢消息情况。若双引擎没有共同时间基准，不直接相减两台时钟就宣称同步误差。以上为测量建议，尚无本项目实测结果。')
refs(25,26,27,29,35)

# 11
pg('10 公开数值如何选取与统一登记')
p('参数参考应围绕完整型号及版本。地面平台可以选择真实厂家性能表，飞机可以先选公开仿真模型。两者证据等级不同，不能合并成“已验证的平台能力”。')
table(['参考对象','公开数据示例','使用限制'],[
['Leopard 2 A7V [30]','质量 <69 t；速度 ≤70 km/h；\n行驶里程 450 km；宽 3.77–4.00 m','厂家性能边界，不等于已有配套 Gazebo 模型'],
['THeMIS 2024 [31]','1650 kg；2.47×2.04×1.17 m；\n额定载荷 750 kg；20 km/h；\n混动最长 15 h，满载静音最长 1.5 h','特定履带 UGV 的公开例子，不代表全部无人战车'],
['Husky A200 [32]','50 kg；0.99×0.67×0.39 m；\n最大载荷 75 kg，全地形 20 kg；\n最大速度 1 m/s，平均运行 3 h','通用科研地面平台，具有官方仿真路线 [33]'],
['PX4 rc_cessna [17]','直接 link 质量合计约 1.67 kg；\n有惯性、气动、舵面与推进配置','仿真模型配置，不是实装性能承诺'],
['ArduPilot Zephyr [19–20]','直接 link 质量合计 1.90 kg；\n主翼气动组 area=0.50 m²','和当前场景是否同源待核对'],
],[4.0,7.3,6.1],size=9)
h('建议的一条参数记录')
code('platform_type: UGV\nparameter: max_forward_speed\nvalue: null\nunit: m/s\nstatus: unknown\nsource_url: null\nmodel_version: unknown\nimplementation: DiffDrive/max_linear_velocity\nverification: pending')
p('null 表示未知，不表示 0。每条参数应另附工况和来源版本；例如空载还是满载、道路还是越野、空速还是地速、额定还是最大。公开资料没有给出的加速度、惯量、续航函数，不应拿任意数值补成“真实参数”。')
p('当前能够登记的事实是四类、编号、话题和说明中的控制方式。各类实际模型质量、尺寸、最大速度、限幅、能源及插件加载情况，仍全部需要工程配置或运行证据。')
refs(30,31,32,33,17,19)

# 12
pg('11 只读核对与验证清单')
p('目前不需要先补齐全部真实参数。可从现有工程提取可观察信息，明确每项指标已配置、已生效还是仅有参考。下面命令用于已启动且环境一致的 WSL/ROS 2 终端，不修改依赖或发移动命令。')
code('# 环境与话题  若某条命令不存在则记录实际版本\nprintenv ROS_DISTRO\nros2 pkg prefix ros_gz_bridge\nros2 topic list -t\nros2 topic info /rover_31/cmd_vel -v\nros2 topic echo /rover_31/cmd_vel\nros2 topic echo /model/rover_31/pose\n# Gazebo 新旧命名各查适用的一组\ngz sim --versions\nign gazebo --versions\ngz topic -l\nign topic -l')
p('ros2 topic echo 会持续监听，按 Ctrl+C 退出。cmd_vel 没有发布者时无消息是正常情况；位姿话题名称依据提供文件，实际存在性须以 topic list 为准。只读输出可能无法呈现插件全部内部配置，最终仍需生成的 SDF 和启动日志。',size=9.5)
table(['验证对象','需要保留的证据','避免误判'],[
['配置是否生效','生成 SDF、插件加载日志、版本号','源模板存在不等于运行场景已使用'],
['速度与加速度','命令序列、真值位姿、仿真时间','命令值不等于实际速度'],
['转向与制动','轨迹半径、角速度、停止距离与时间','无视滑移和命令延迟'],
['载荷影响','装载量、位置、质量与响应对照','仅改标签或容量上限'],
['续航与停机','SOC、功率、起止仿真时间、耗尽行为','只显示电量但驱动继续运行'],
['固定翼真实性','气动与推进配置、飞控日志、受力响应','把关闭重力的升降当作真实爬升'],
['50 台规模','RTF、频率、延迟、资源与丢消息','只凭截图或发布器数量判断达标'],
],[3.4,7.0,7.0],size=9)
p('建议交付物：一份按型号版本组织的参数表、一份 SDF 与插件字段映射、一份带工况和仿真时间的验证记录。当前研究给出候选机制与来源，尚未替代这三项工程证据。',boldlead='建议交付物：')
refs(2,8,14,29,34)

# 13-14 Reference directory
for title, numbers in [('参考资料一 消息 物理与运动模型',range(1,18)),('参考资料二 飞行 能源与公开平台',range(18,36))]:
    pg(title)
    p('点击条目打开原始依据。API 以 Gazebo Sim 8 为说明基准；SDF 引用为 1.9 规范文件，均不代表当前工程已使用这些版本。main 与版本分支可能继续更新，复现时应固定具体提交。',size=9.5)
    for n in numbers:
        a=doc.add_paragraph();a.paragraph_format.space_after=Pt(8);a.paragraph_format.line_spacing=Pt(13)
        hyperlink(a,f'[{n}] {S[n][0]}',S[n][1])
    if numbers.start==18:
        h('项目资料与核对状态')
        p('《机器人移动话题说明.md》与用户提供场景截图用于界定当前平台和接口。本轮未获得并运行完整场景工程，未确认模型实际参数与上述上游示例一致。',size=9.5)
        p('本轮下载并解析 3 份公开模型 SDF，阅读相关插件源码。整机质量合计为对下载文件的直接 link/mass 求和，未加入额外载荷或其他场景模型。',size=9.5)

for st in doc.styles:
    for border in list(st.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    if st.type==1:
        pr=st.element.get_or_add_pPr(); e=OxmlElement('w:snapToGrid');e.set(qn('w:val'),'0');pr.append(e)
for border in list(doc.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
doc.save(OUT)

# Evidence inventory and deterministic model sums for internal QA.
inventory={}
for name in ['rc_cessna.sdf','zephyr.sdf','zephyr_with_ardupilot.sdf']:
    f=ROOT/'sources'/name
    tree=ET.parse(f).getroot()
    masses=[Decimal(e.text) for e in tree.findall('./model/link/inertial/mass')]
    inventory[name]={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'direct_link_mass_sum_kg':str(sum(masses))}
(ROOT/'model_evidence.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
print('Created detailed DOCX; tables:',len(doc.tables),'hyperlinks:',len(list(doc.element.iter(qn('w:hyperlink')))))
print(json.dumps(inventory,indent=2))
