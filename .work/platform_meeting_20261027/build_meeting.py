from pathlib import Path
from copy import deepcopy
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
base_code = (PROJECT / '.work/platform_brief_20261027/build_brief.py').read_text(encoding='utf-8')
exec(base_code.split("doc.add_paragraph('四类平台常用参数指标'")[0])
SOURCE_BRIEF = PROJECT / '四类平台参数指标与对接要点_简明展示版.docx'
doc = Document(SOURCE_BRIEF)
OUT = PROJECT / '四类平台参数与对接说明_会议展示版.docx'
original = Document(PROJECT / '四类平台参数指标与Gazebo实现详尽调研_更新版20261027.docx')
anchor = next(p for p in doc.paragraphs if p.text == '下层对接与验证要点')._p.getprevious()
assert anchor.xpath('.//w:br[@w:type="page"]')

for para in doc.paragraphs:
    if para.text.startswith('公开参考值：') or para.text.startswith('先看尺寸、'):
        para.text = '以下为特定公开产品或仿真模型的参考值，不代表当前工程已采用。'
    if para.text.startswith('我方负责约定输入的对接消费'):
        para.text = '下层仿真、桥接、采集、显示和部署按外协清单对接；M3（含M8）与M4由我方交付，M2归属待核对。具体导航和动作执行承接人由平台明确。'
        for r in para.runs:
            r.font.size = Pt(10.5)
    elif para.text.startswith('新增目标与分工依据：'):
        para.text = '目标依据：两份新增Word。分工按最新项目记录；旧18页版只用于查阅原参数及来源，其M3/M4责任表述已过时。'
        for r in para.runs:
            r.font.size = Pt(9.5)

before = set(doc.element.body)
doc.add_page_break()
doc.add_paragraph('模型参数的位置与含义', 'Title')
p('下表保留原报告的参数定位方式，供阅读和对接使用；实际字段、模型版本及生效情况由下层确认。')
doc.add_heading('四类共通的模型参数', level=2)
table(['参数', '原报告中的位置', '需要理解的含义'], [
    ['尺寸', 'visual / collision 的geometry', '外观尺寸与碰撞形状分开，不能只看画面'],
    ['质量', 'link/inertial/mass', '单个部件质量；整机需要汇总'],
    ['重心', 'link/inertial/pose', '质心位置及其坐标解释'],
    ['惯量', 'link/inertial/inertia', '描述转动惯性，不是另一种质量'],
    ['载荷', '能力配置与实际加载的模型', '允许装多少与实际装多少分别记录'],
], [2.7, 6.0, 8.7])
doc.add_heading('无人车 UGV 的参数位置', level=2)
table(['参数', '原报告示例字段', '含义'], [
    ['轮半径与轮距', 'wheel_radius / wheel_separation', '差速运动的几何参数'],
    ['线速度与转速', 'max_linear_velocity / max_angular_velocity', '两类速度限制分别表达'],
    ['反馈频率', 'odom_publish_frequency', '里程计发布频率，不等于物理更新频率'],
], [2.7, 7.2, 7.5])
doc.add_heading('TANK 外观与运动机制分开看', level=2)
table(['参数或状态', '原报告记载', '含义'], [
    ['旧场景运动方式', '履带外观＋差速轮驱动代理', '外观不证明已实现履带动力学'],
    ['履带模型参数', 'tracks_separation / track_height', '履带插件示例，不能认定旧轮驱代理已采用'],
    ['命令有效期', 'TrackController / max_command_age', '履带插件的过期处理；整条执行链仍须验证'],
], [2.7, 7.2, 7.5])
p('会上重点问清采用什么模型、开放什么控制和反馈、参数是否已生效；不需要由你调试这些插件字段。', 10)

doc.add_page_break()
doc.add_paragraph('两类飞行模型的公开参数', 'Title')
p('以下数值摘自原调研的公开模型，只用于解释参数。它们不是当前场景已经采用的数值，也不是实装平台性能承诺。', 10.5)
doc.add_heading('常规固定翼 PX4 rc_cessna', level=2)
table(['参数', '原调研数值', '所在位置或含义'], [
    ['主机体质量', '1.5 kg', 'base_link，不是整机'],
    ['整机质量合计', '约1.67 kg', '原调研直接link质量求和'],
    ['主机体惯量', '0.197563 / 0.1458929 / 0.1477 kg·m²', '依次为Ixx、Iyy、Izz'],
    ['参考面积示例', '0.6 m²', '模型中一组气动面的参考面积'],
], [3.1, 6.3, 8.0])
doc.add_heading('飞翼 ArduPilot Zephyr', level=2)
rows = []
for index in range(1, 9):
    cells = original.tables[7].rows[index].cells
    rows.append([c.text for c in cells])
table(['参数', '上游数值', '所在位置或含义'], rows, [3.1, 6.3, 8.0])
p('会上能说明“是什么、来自哪里、是否已采用”即可。升力斜率、惯量、失速迎角的公式与调参由下层建模方解释；我方只消费约定的能力和状态。', 10)
p('来源仍为第4页的公开模型链接；Zephyr气动项见原调研所引zephyr_with_ardupilot扩展模型。', 9.5)
new_blocks = [el for el in doc.element.body if el not in before]
for el in new_blocks:
    anchor.addprevious(el)

extra = p('新增要求属于平台目标；实际版本、正式接口与运行证据由相应交付方提供。', 10)
a = p('Zephyr气动参数来源  ', 9.5)
link = OxmlElement('w:hyperlink')
link.set(qn('r:id'), a.part.relate_to('https://github.com/ArduPilot/ardupilot_gazebo/blob/main/models/zephyr_with_ardupilot/model.sdf', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink', is_external=True))
run = OxmlElement('w:r')
text = OxmlElement('w:t'); text.text = 'zephyr_with_ardupilot扩展模型'; run.append(text)
link.append(run); a._p.append(link)
doc.add_page_break()
doc.add_paragraph('开会时怎么说明', 'Title')
p('你需要掌握到“能解释含义、能确认接口、能核对证据”的程度。下层实现细节请交付方说明。')
table(['内容', '应掌握到什么程度'], [
    ['参数', '知道含义、单位、来源与工况；区分参考值、配置值、实测值'],
    ['接口', '知道输入输出、坐标系、时间基准、实例身份和错误反馈'],
    ['运动机制', '能区分外观、速度代理与物理模型，不把能动等同能力达标'],
    ['验证', '能提出样例、配置和运行反馈要求，明确双方各测什么'],
], [3.1, 14.3], 10.5)
doc.add_heading('可以直接这样说', level=2)
p('“我们先把四类平台的常用指标统一成参数表，公开数据作为参考。具体模型、插件和运行反馈由下层提供，我们按约定接口使用。')
p('需要确认下层接收任务目标还是速度命令、能返回哪些状态、采用什么坐标系和时间基准，以及参数是否经过验证。我们负责自身模块与接口适配，下层负责其交付范围内的仿真执行，双方联合验证。”')
doc.add_heading('这次会议确认五件事', level=2)
for text in [
    '1  四类平台实际采用什么模型和版本？属于运动代理还是物理模型？',
    '2  下层接收什么命令？导航和具体动作执行由谁提供？',
    '3  返回哪些状态？消息格式、单位、坐标系、时间戳和实例身份如何约定？',
    '4  哪些参数已有来源和实测，哪些只是配置或待确认？谁提供样例与验证记录？',
    '5  取消、失联、重启后怎样回报？双方怎样做最小闭环联调？',
]:
    p(text)
doc.add_heading('责任表达要准确', level=2)
p('“下层由外协交付”仅针对相应模块。按最新项目记录，M3（含M8）和M4由我方建设与自测；M1、Bridge、M5、M6、M7由外协交付，我方对接；M2归属待核对。')
p('先确认单实例、单机器人的命令与真实反馈闭环，再按双方约定扩大联调范围。此处是沟通建议，不代表当前已接通。', 10)

doc.core_properties.title = '四类平台参数与对接说明'
doc.core_properties.subject = '常用指标 参数含义 下层对接 会议说明'
doc.save(OUT)
check = Document(OUT)
assert len(check.tables) == 9
print(str(OUT))
