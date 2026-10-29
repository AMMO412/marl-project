from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT

OUT = Path(r'C:\Users\ammo\Desktop\MARL项目\outputs\平台参数调研\四类平台公开参数与Gazebo衔接调研.docx')
doc = Document()
s = doc.sections[0]
s.page_width, s.page_height = Cm(21), Cm(29.7)
s.top_margin, s.bottom_margin = Cm(1.7), Cm(1.6)
s.left_margin = s.right_margin = Cm(1.8)
s.footer_distance = Cm(0.8)

for name in ['Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2']:
    st = doc.styles[name]
    st.font.name = 'Calibri'
    st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), '微软雅黑')
    st.font.color.rgb = RGBColor(0, 0, 0)
normal = doc.styles['Normal']
normal.font.size = Pt(10.5)
normal.paragraph_format.line_spacing = Pt(15)
normal.paragraph_format.space_after = Pt(6)
for name, size in [('Title', 25), ('Subtitle', 12), ('Heading 1', 18), ('Heading 2', 12)]:
    st = doc.styles[name]
    st.font.size = Pt(size)
    st.font.bold = name != 'Subtitle'
    st.font.italic = False
    st.paragraph_format.space_before = Pt(12 if name == 'Heading 2' else 4)
    st.paragraph_format.space_after = Pt(8)

def p(text, boldlead=None, size=None):
    a = doc.add_paragraph()
    if boldlead and text.startswith(boldlead):
        a.add_run(boldlead).bold = True
        a.add_run(text[len(boldlead):])
    else:
        a.add_run(text)
    if size:
        for r in a.runs: r.font.size = Pt(size)
    return a

def h(text, level=2):
    doc.add_heading(text, level)

def table(headers, rows, widths, size=9.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for col, width in zip(t.columns, widths): col.width = Cm(width)
    pr = t._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        e=OxmlElement('w:'+edge)
        for k,v in [('val','single'),('sz','5'),('color','D9D9D9')]: e.set(qn('w:'+k),v)
        borders.append(e)
    pr.append(borders)
    for idx, data in enumerate([headers]+rows):
        row = t.rows[0] if idx == 0 else t.add_row()
        no_split = OxmlElement('w:cantSplit'); row._tr.get_or_add_trPr().append(no_split)
        if idx == 0:
            repeat=OxmlElement('w:tblHeader'); row._tr.get_or_add_trPr().append(repeat)
        for j, text in enumerate(data):
            c=row.cells[j]; c.width=Cm(widths[j]); c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp=c._tc.get_or_add_tcPr()
            margins=OxmlElement('w:tcMar')
            for edge,val in [('top','75'),('bottom','75'),('left','110'),('right','110')]:
                e=OxmlElement('w:'+edge); e.set(qn('w:w'),val); e.set(qn('w:type'),'dxa'); margins.append(e)
            cp.append(margins)
            shade=OxmlElement('w:shd'); shade.set(qn('w:fill'),'244761' if idx==0 else ('F1F5F8' if idx%2==0 else 'FFFFFF')); cp.append(shade)
            a=c.paragraphs[0]; a.paragraph_format.space_after=Pt(0); a.paragraph_format.line_spacing=Pt(13)
            a.alignment=WD_ALIGN_PARAGRAPH.CENTER if j==0 else WD_ALIGN_PARAGRAPH.LEFT
            r=a.add_run(text); r.font.size=Pt(size)
            r.font.bold=idx==0
            r.font.color.rgb=RGBColor.from_string('FFFFFF' if idx==0 else '000000')
    doc.add_paragraph().paragraph_format.space_after=Pt(0)
    return t

def newpage(title):
    doc.add_page_break(); h(title,1)

def hyperlink(par, label, url):
    rel=par.part.relate_to(url,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',is_external=True)
    link=OxmlElement('w:hyperlink'); link.set(qn('r:id'),rel)
    run=OxmlElement('w:r'); rp=OxmlElement('w:rPr')
    color=OxmlElement('w:color'); color.set(qn('w:val'),'24577A'); rp.append(color)
    sz=OxmlElement('w:sz'); sz.set(qn('w:val'),'19'); rp.append(sz)
    run.append(rp); txt=OxmlElement('w:t'); txt.text=label; run.append(txt); link.append(run); par._p.append(link)

footer=s.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
rr=footer.add_run('第 '); rr.font.size=Pt(9)
field=OxmlElement('w:fldSimple'); field.set(qn('w:instr'),'PAGE'); footer._p.append(field)
footer.add_run(' 页').font.size=Pt(9)
doc.core_properties.title='四类平台公开参数与 Gazebo 衔接调研'
doc.core_properties.subject='公开参考参数 仿真模型来源 当前接口与适用边界'
doc.core_properties.author=''

doc.add_paragraph('四类平台公开参数\n与 Gazebo 衔接调研', 'Title')
doc.add_paragraph('坦克  无人地面平台  常规固定翼  Zephyr 飞翼', 'Subtitle')
p('资料核对日期  2026年10月24日', size=9)
h('1 主要结论',1)
p('四类平台均有可参考的公开资料。地面平台可获得厂家性能指标，固定翼可获得包含物理与气动配置的公开模型。建议将这些资料整理为带来源的可配置参数表，并根据仿真目标选择运动代理或物理模型。')
p('适用边界：厂家性能指标、Gazebo 模型参数、ROS 2 控制接口属于不同层次。具备速度控制和三维外观，不能据此认定已实现真实履带运动或固定翼飞行。', boldlead='适用边界：')
h('现有场景中的四类平台')
table(['平台类别','数量与编号','当前移动方式','依据'],[
 ['无人车 UGV','20 台\n01–20','差速驱动','用户提供的\n移动话题说明'],
 ['坦克 TANK','10 台\n21–30','履带外观\n差速轮驱动代理','同上'],
 ['常规固定翼 PLANE','10 台\n31–40','关闭重力\n直接速度控制','同上'],
 ['Zephyr 飞翼 WING','10 台\n41–50','关闭重力\n直接速度控制','同上'],
], [3.6,2.4,5.0,6.4])
p('分类已明确：两类飞机为常规布局固定翼与 Zephyr 飞翼。本文不采用“常规固定翼与垂直起降固定翼”的分类。',boldlead='分类已明确：')
h('展示时需要回答的两个问题')
p('公开参数从哪里来？地面平台优先查型号对应的厂家手册；飞机物理参数优先查上游 SDF 和配套气动配置。具体来源见第 5 页。')
p('能否直接接到现有工程？部分几何和物理参数有 SDF 对应项；速度边界、能源消耗和真实飞行仍需相应控制或模型支持。当前工程状态依据提供文件，尚未核对源码及运行结果。')

newpage('2 地面平台公开参数与模型选择')
p('以下为特定型号的公开参考，不能当作整个平台类别的统一标准。各型号应独立成套使用，避免混用不同版本或工况的数据。')
table(['指标','Leopard 2 A7V [1]','THeMIS [2]','Husky A200 [3]'],[
 ['参考用途','坦克性能边界','履带 UGV 性能边界','通用地面联调'],
 ['质量','<69 t','1650 kg','50 kg'],
 ['外形尺寸','宽 3.77–4.00 m\n高 2.64 m','长宽高\n2.47×2.04×1.17 m','长宽高\n0.99×0.67×0.39 m'],
 ['最大速度','≤70 km/h','20 km/h','1 m/s'],
 ['载荷','本表未采用','额定 750 kg\n最大 1200 kg','最大 75 kg\n全地形 20 kg'],
 ['续航相关','行驶里程 450 km','混合动力最长 15 h\n满载静音最长 1.5 h','平均运行 3 h'],
 ['资料性质','厂家公开性能表','2024 厂家目录','官方用户手册'],
], [2.5,4.7,5.1,5.1])
p('口径说明：行驶里程与运行时间分别保留；最大载荷与最长续航不代表可以同时实现。Husky 是小型科研平台，性能不能代表重型无人战车。',boldlead='口径说明：',size=9.5)
h('坦克与履带 UGV 的 Gazebo 衔接')
p('Gazebo 提供 TrackedVehicle 与 TrackController，并有 tracked_vehicle_simple.sdf 示例 [4]。它们可作为履带接地运动近似的起点；软土沉陷、悬挂及具体车辆的动力性能仍需另行建模和验证。')
p('当前文件说明坦克仍使用差速轮代理。因此，公开速度和尺寸可以作为配置参考，但要体现履带接地行为，需要调整模型与控制插件。')
h('优先联调时的替代选择')
p('Clearpath 为 Husky 提供官方 Gazebo 仿真与 ROS 2 桥接路线 [3]。若当前目标是验证消息收发、位姿反馈和通用地面运动，可以先使用这类资料完整的平台；选型仍应核对 ROS 2 与 Gazebo 版本。')
p('数据状态：本页数值为厂家公布值，本轮未做实车测量，也未验证现有场景达到这些性能。',boldlead='数据状态：',size=9.5)

newpage('3 两类固定翼的公开模型与参数')
p('常规布局固定翼可参考 PX4 rc_cessna；Zephyr 飞翼可参考 ArduPilot 的同名模型及配套扩展模型。这两条路线均有公开 Gazebo 资料 [5–7]。')
table(['对比项','常规固定翼','Zephyr 飞翼'],[
 ['公开模型','PX4 rc_cessna','ArduPilot zephyr\n及 zephyr_with_ardupilot'],
 ['质量配置示例','base_link 为 1.5 kg','主翼 link 为 1.5 kg'],
 ['已公开内容','惯量、碰撞体、气动配置、\n舵面及关节','惯量、碰撞体、主翼与舵面\n气动、推进和飞控连接'],
 ['Gazebo 路线','PX4 SITL 与 Gazebo','ArduPilot SITL 与 Gazebo'],
 ['与现有模型的关系','布局相近的通用参考','名称一致的候选来源\n仍需核对实际版本'],
], [3.0,7.2,7.2])
p('质量口径：上述 1.5 kg 均为指定 link 的配置值，不能直接写成整机质量；这些模型参数也不能冒充实装无人机的实测性能。',boldlead='质量口径：',size=9.5)
h('Zephyr 气动参数示例')
table(['字段','上游配置值','含义'],[
 ['area','0.50 m²','主翼一组气动插件的参考面积'],
 ['cla','3.7','升力系数随迎角变化的斜率'],
 ['alpha_stall','约 0.339 rad','该气动模型的失速迎角'],
 ['forward','0 -1 0','该 link 中的气动前向轴'],
], [3.0,3.3,11.1])
p('以上来自 zephyr_with_ardupilot 的主翼气动插件 [6]。参考面积不等同于整机所有翼面的总面积；失速迎角也不能直接替代失速空速。',size=9.5)
h('从现有速度代理升级时需要改变什么')
p('当前飞机由 VelocityControl 直接设定速度，未计算升力、阻力或失速。真实飞行需要重力、气动、推进、舵面控制及闭环控制器共同工作；仅替换外观或填写质量无法完成升级 [8]。')
p('坐标与接口：当前说明用 linear.x 表示前进，上游 Zephyr 气动前向为 -Y。接入时须核对模型变换和坐标轴；物理飞行中的固定翼也不能沿用全零速度作为“空中停车”。',boldlead='坐标与接口：')

newpage('4 参数组织与现有接口的衔接')
p('建议按下表建立统一字段字典。字段名可以统一，各平台的取值、适用范围和生效位置应分别记录。此表为工程整理建议。')
table(['参数组','建议记录内容','生效位置'],[
 ['基础参数','型号与版本、尺寸 m、质量 kg、\n载荷 kg','配置文件；SDF 几何与质量'],
 ['运动边界','常用与最大速度 m/s、加减速度 m/s²、\n转向角速度 rad/s','控制器或指令约束'],
 ['能源与续航','时间 s、行驶里程 m、能源容量、\n载荷与路况等测量条件','能源消耗模型'],
 ['地面专用','轮距或履带间距 m、轮径 m、\n离地间隙 m、坡度 deg、限矩 N·m','驱动插件、关节与接触模型'],
 ['固定翼专用','翼展 m、翼面积 m²、空速 m/s、\n爬升率 m/s、重心、惯量、气动系数','SDF、气动插件及飞控'],
 ['来源与状态','来源链接、型号版本、工况、\n厂家公布／示例／估算／实测','参数元数据'],
], [2.7,8.6,6.1])
h('现有接口可以保留哪些约定')
p('用户文件记载，每台机器人均订阅 /rover_XX/cmd_vel，消息类型为 geometry_msgs/msg/Twist。地面平台使用 linear.x 与 angular.z；飞机速度代理额外使用 linear.z。话题命名可以保留，但控制语义须与实际控制器对应。')
p('Gazebo 的 SDF 可描述质量、重心、惯量、碰撞体及关节 [9]。续航、载荷约束和速度上限则要由相应模型或控制逻辑实际执行；消息中出现一个数值不等于模型具备该能力。')
h('建议的核对顺序')
p('第一步，核对 Gazebo 版本、模型来源和生成后的 SDF。ROS 2 Humble 与 ignition.msgs.Twist 字样不足以确定实际 Gazebo 发行版。')
p('第二步，整理同一型号版本的公开参数，缺失值标为待确认。先确定目标是运动演示还是物理验证，再选择驱动与气动模型。')
p('第三步，单机检查速度、转向、爬升及反馈，记录仿真时间和位姿。文件中的发令时长按墙钟计算，实时因子低于 1 时不能用墙钟时间直接推算位移。')
p('后续核对材料：fleet-roster.json、linux/prepare_scene.py、MIXED-FLEET.md、生成 SDF 及 Gazebo 版本。',boldlead='后续核对材料：',size=9.5)

newpage('5 参考资料与证据范围')
p('下列链接对应正文编号，可在 Word 中点击打开。产品指标对应所列型号与资料版本；代码链接使用上游 main 或指定版本分支，后续复现应固定提交号。',size=10)
sources=[
 ('[1] KNDS Leopard 2 A7 页面中的 A7V 性能表','质量、速度、宽度、高度及行驶里程。','https://knds.com/en/products/systems/leopard/leopard-2-a7'),
 ('[2] Milrem Robotics 2024 产品目录','印刷页 7 的 THeMIS 规格，含尺寸、质量、载荷及运行工况。','https://d3tr2q1wj7u3d5.cloudfront.net/32284/20240611_MILREM-Product-Catalogue-EN_web.pdf'),
 ('[3] Clearpath Husky A200 官方手册与仿真说明','A200 的尺寸、质量、载荷与续航，以及官方仿真路线。','https://docs.clearpathrobotics.com/docs_robots/outdoor_robots/husky/a200/user_manual_husky/'),
 ('[4] Gazebo 履带车示例','gz-sim8 分支的 tracked_vehicle_simple.sdf。','https://github.com/gazebosim/gz-sim/blob/gz-sim8/examples/worlds/tracked_vehicle_simple.sdf'),
 ('[5] PX4 rc_cessna 模型','质量、惯量、碰撞、气动和舵面配置。','https://github.com/PX4/PX4-gazebo-models/blob/main/models/rc_cessna/model.sdf'),
 ('[6] ArduPilot Zephyr 气动与飞控扩展模型','主翼与舵面气动、推进及飞控连接；包含基础 zephyr 模型。','https://github.com/ArduPilot/ardupilot_gazebo/blob/main/models/zephyr_with_ardupilot/model.sdf'),
 ('[7] ArduPilot Gazebo 官方接入说明','Gazebo 与 ArduPilot SITL 的接入路线及 Zephyr 示例。','https://ardupilot.org/dev/docs/sitl-with-gazebo.html'),
 ('[8] Gazebo VelocityControl 插件说明','直接设置模型线速度与角速度的控制方式。','https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1VelocityControl.html'),
 ('[9] SDFormat 惯性参数定义','质量、重心与惯量结构；规范版本须与实际环境匹配。','https://github.com/gazebosim/sdformat/blob/main/sdf/1.12/inertial.sdf'),
]
for label,desc,url in sources:
    a=doc.add_paragraph(); a.paragraph_format.space_after=Pt(2); hyperlink(a,label,url)
    p(desc,size=9)
a=doc.add_paragraph(); a.paragraph_format.space_after=Pt(5)
hyperlink(a,'补充链接  Clearpath 仿真概览','https://docs.clearpathrobotics.com/docs/ros/tutorials/simulator/overview/')
a=doc.add_paragraph(); a.paragraph_format.space_after=Pt(5)
hyperlink(a,'补充链接  PX4 Gazebo 机型与版本说明','https://docs.px4.io/main/en/sim_gazebo_gz/vehicles')
a=doc.add_paragraph(); a.paragraph_format.space_after=Pt(5)
hyperlink(a,'补充链接  Zephyr 基础模型与质量配置','https://github.com/ArduPilot/ardupilot_gazebo/blob/main/models/zephyr/model.sdf')
h('当前工程资料')
p('《机器人移动话题说明.md》：用于确认四类平台、编号、话题语义及当前简化控制边界。文件说明不等同于工程源码检查或运行验证。',size=9.5)
p('本轮完成公开文档与源码调研，未执行 Gazebo 仿真、性能测试或规模测试。文中衔接路线属于候选方案，效果与兼容性需通过实际联调确认。',size=9.5)

for st in doc.styles:
    for border in list(st.element.iter(qn('w:pBdr'))): border.getparent().remove(border)
    if st.type == 1:
        pr = st.element.get_or_add_pPr()
        grid=OxmlElement('w:snapToGrid'); grid.set(qn('w:val'),'0'); pr.append(grid)
for border in list(doc.element.iter(qn('w:pBdr'))): border.getparent().remove(border)
doc.save(OUT)
print(OUT)
print('tables',len(doc.tables),'paragraphs',len(doc.paragraphs))
