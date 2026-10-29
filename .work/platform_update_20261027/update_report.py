from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from zipfile import ZipFile

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
SOURCE = PROJECT / '四类平台参数指标与Gazebo实现详尽调研.docx'
OUTPUT = PROJECT / '四类平台参数指标与Gazebo实现详尽调研_更新版20261027.docx'
BACKUP = ROOT / '四类平台参数指标与Gazebo实现详尽调研_更新前.docx'
if not BACKUP.exists():
    BACKUP.write_bytes(SOURCE.read_bytes())
doc = Document(BACKUP)
original_hyperlinks = sum(1 for p in doc.element.iter(qn('w:hyperlink')))
changes = []

def comment(p, text):
    if p.runs:
        doc.add_comment(p.runs[0], text, author='修订说明', initials='修订')

def edit(prefix, text, reason):
    matches = [p for p in doc.paragraphs if p.text.startswith(prefix)]
    assert len(matches) == 1, (prefix, len(matches))
    p = matches[0]
    before = p.text
    p.clear()
    if text.startswith('核心结论：'):
        p.add_run('核心结论：').bold = True
        p.add_run(text[len('核心结论：'):])
    else:
        p.add_run(text)
    comment(p, reason)
    changes.append({'before': before, 'after': text, 'reason': reason})
    return p

edit('核心结论：',
     '核心结论：旧演示场景的50路cmd_vel仅说明速度接口。新增方案提出多实例、采集与同步目标，尚无实际参数或达标证据。公开数值继续作为参考；新平台适用范围、交付边界及验证要求见第12至15章。',
     '2026年10月27日更新。新增材料改变平台目标和对接口径，没有提供四类平台新的实测性能参数。')

doc.tables[0].cell(0, 1).text = '旧场景数量与编号'
doc.tables[0].cell(0, 2).text = '旧说明记载的控制方式'
for cell in [doc.tables[0].cell(0, 1), doc.tables[0].cell(0, 2)]:
    for r in cell.paragraphs[0].runs:
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)
stamp = doc.paragraphs[3]
assert not stamp.text.strip()
stamp.add_run('更新日期 2026年10月27日。第1至11章中的现有场景与控制方式，均指旧移动说明所述状态，未核验新工程；20/10/10/10的组成不是新平台每实例的既定要求。').font.size = Pt(9)
stamp.paragraph_format.space_after = Pt(5)
comment(stamp, '原始四类及编号保留作历史场景参考。实施方案只规定每实例机器人数量下限，未规定各类比例。')

edit('四类均使用 /rover_XX/cmd_vel。',
     '旧场景四类均使用/rover_XX/cmd_vel，名称不表示平台类型。默认话题与该名称的映射须由插件或桥接落实。[8,13] 新方案存在多个独立实例，须由Bridge明确实例身份、机器人编号与隔离映射，不能默认原编号全局唯一。',
     '新方案第2.1及3.1节提出多实例与容器网络约定。此处只列需冻结的对接事项，不自拟正式话题协议。')
edit('Humble 分支明确支持',
     '以上为Humble历史桥接示例，不是新目标环境配置。新方案提出ROS 2 Jazzy；Gazebo、ros_gz及消息类型以供方锁定的版本和映射表为准。仅改类型名称不能证明兼容；订阅连接也不能证明运动执行。[2] 版本对照见第12章。',
     '保留旧示例和来源，明确其适用版本；本轮未核实新工程安装版本或兼容性。')
edit('截图展示了模型阵列',
     '旧截图与移动说明记载UE相机输出尚未发布为ROS 2 Image，这只是历史场景状态。新方案要求7类采集数据；来源、消息格式、频率与时间戳须由M5及Bridge逐项确认，不能将目标写成已实现。接口责任见第13章。',
     '实施方案第2.5节及外协第4节增加7类采集数据，但未证明旧场景已完成升级。')
edit('建议分别测试 1、10、50 台',
     '旧场景可保留1、10、50台及图像开关的基线测试；新平台还须验证≥20实例、每实例≥50机器人的目标负载。记录RTF、频率、延迟分布及资源占用，区分仿真时间和墙钟时间。新验收目标与证据见第15章；本轮无实测结果。',
     '扩展验证范围，保留原单实例测试作为基线，不用其代替新平台规模测试。')
edit('当前能够登记的事实是',
     '旧说明可登记四类、编号、话题及所述控制方式；实际参数仍待工程证据。新文件未给出替换公开数值的新实测参数。登记时增加配置版本、实例和轮次关联，并区分配置基准、随机化设置及当轮生效值，见第14章。',
     '新方案要求域随机化和实验管理。新增的是参数追溯信息，不补造随机范围或平台能力。')
edit('建议交付物：',
     '建议供方提供按型号版本组织的参数表、字段映射、实际生效配置与验证记录；我方核验约定数据的消费及本层输出。具体模型、能源及执行功能的承接人由平台明确，不能自动归入中间层。责任与证据清单见第13、15章。',
     '结合外协清单与既定中间层边界，区分平台交付、我方消费和双方联验。')
edit('《机器人移动话题说明.md》与用户提供场景截图',
     '旧场景依据《机器人移动话题说明.md》与场景截图。新增目标依据《智能体开发训练平台技术实施方案》《外协内容》，章节出处见第12至15章。本轮未运行完整工程，未确认实际模型参数、接口或性能达标。',
     '补充本轮资料范围；原公开模型解析结果保留为历史研究证据，不表述为新一次运行。')
edit('本轮下载并解析 3 份公开模型 SDF',
     '原调研下载并解析3份公开模型SDF，并阅读相关插件源码。整机质量合计为当时下载文件的直接link/mass求和，未加入额外载荷或其他场景模型；本次更新未重复下载或求和。',
     '将原研究中的本轮明确为原调研，避免被误读成2026年10月27日新增实验。')
for table_index in [6, 7]:
    for text_node in doc.tables[table_index]._tbl.iter(qn('w:t')):
        if text_node.text and '本轮' in text_node.text:
            text_node.text = text_node.text.replace('本轮', '原调研')

reference_heading = next(p for p in doc.paragraphs if p.text.startswith('参考资料一'))
anchor = reference_heading._p.getprevious()
assert anchor is not None and anchor.xpath('.//w:br[@w:type="page"]')
old_children = set(doc.element.body)

def p(text, size=None):
    result = doc.add_paragraph(text)
    if size:
        for r in result.runs:
            r.font.size = Pt(size)
    return result

def heading(text, level=2):
    return doc.add_heading(text, level)

def page(text):
    doc.add_page_break()
    heading(text, 1)

def table(headers, rows, widths):
    t = doc.add_table(rows=1, cols=len(headers))
    t.autofit = False
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for col, width in zip(t.columns, widths):
        col.width = Cm(width)
    borders = OxmlElement('w:tblBorders')
    for edge in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        el = OxmlElement('w:' + edge)
        for key, val in [('val', 'single'), ('sz', '5'), ('color', 'D9D9D9')]:
            el.set(qn('w:' + key), val)
        borders.append(el)
    t._tbl.tblPr.append(borders)
    for i, values in enumerate([headers] + rows):
        row = t.rows[0] if i == 0 else t.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        if i == 0:
            row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
        for j, (cell, value) in enumerate(zip(row.cells, values)):
            cell.width = Cm(widths[j])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            margins = OxmlElement('w:tcMar')
            for edge, val in [('top', '85'), ('bottom', '85'), ('left', '110'), ('right', '110')]:
                el = OxmlElement('w:' + edge)
                el.set(qn('w:w'), val)
                el.set(qn('w:type'), 'dxa')
                margins.append(el)
            cell._tc.get_or_add_tcPr().append(margins)
            shade = OxmlElement('w:shd')
            shade.set(qn('w:fill'), '244761' if i == 0 else ('F1F5F8' if i % 2 == 0 else 'FFFFFF'))
            cell._tc.get_or_add_tcPr().append(shade)
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = Pt(13)
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER if j == 0 else WD_ALIGN_PARAGRAPH.LEFT
            r = para.add_run(value)
            r.font.size = Pt(9.5)
            r.bold = i == 0
            r.font.color.rgb = RGBColor.from_string('FFFFFF' if i == 0 else '000000')
    spacer = p('')
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(3)
    return t

page('12 新平台范围 版本与依据')
p('本次更新依据两份新增材料，补充目标、接口与交付口径；原公开参数、模型原理和来源继续保留。新材料没有证明旧条款自动失效，也没有提供四类平台新的实测能力数据。')
heading('版本与规模需要分别登记')
table(['事项', '原调研基准', '新增材料要求或描述', '待供方确认'], [
    ['软件环境', 'Humble消息与桥接示例；Gazebo Sim 8 API；SDF 1.9说明', 'ROS 2 Jazzy；部署包列Ubuntu 24.04', 'Gazebo、ros_gz、物理后端与插件的实际版本及兼容清单'],
    ['机器人组成', '单个旧场景50台；20/10/10/10及01至50编号', '≥20独立实例，每实例≥50机器人', '实例内类型比例、型号版本及实例间隔离方式'],
    ['通信与控制', '旧cmd_vel和位姿话题说明', '13类接口；仿真控制、状态、传感器及双引擎连接', '正式消息、服务、Schema及实例身份映射'],
    ['性能目标', '原场景基线测量建议，未实测', '复杂场景RTF≥2；UE5同步P99≤100ms', '硬件、场景、传感器负载、并发及测量条件'],
], [2.2, 4.7, 5.1, 5.4])
heading('旧控制方式保留为历史描述')
p('第1至11章的四类和控制代理来自旧移动说明；新增方案没有逐类声明是否继续采用相同插件。型号、外观、运动控制与物理真实性应分别核对，不能把新平台目标当作旧模型已经升级的证据。')
p('新方案正文中的总体架构图位置为“该类型的内容暂不支持下载”。本次依据可读取的正文和表格审阅，未核对缺失图中的连线与拓扑。')
heading('新增材料出处')
p('[新1]《智能体开发训练平台技术实施方案》：第1章目标与模块；第2章功能；第3.1节接口；第5章验收。文件位于C:/Users/ammo/Desktop/。', 9.5)
p('[新2]《外协内容》：第2至6章模块任务与验收；第7章交付物。文件位于C:/Users/ammo/Desktop/。', 9.5)
p('本章只确定材料所述目标及待确认项，不认定供方已交付或未交付。', 9.5)

page('13 接口与交付责任')
p('中间层沿用约定边界内的对接与消费职责，对自身输入解析、状态处理和输出留痕负责。平台功能由相应交付方实现；具体承接人和正式接口仍需平台方落实。')
table(['交付或依赖项', '责任依据', '我方对接与核验'], [
    ['M1仿真', '外协清单列入实例管理、恢复与物理随机化注入', '消费实例状态、时钟和约定参数；识别重启后的轮次'],
    ['Bridge', '外协清单列入桥接包与DDS配置', '核对消息、身份、单位、坐标系及状态回传'],
    ['M2及M3/M4', '新方案列出；外协清单未列。既定边界由平台落实承接人', '消费约定场景、配置和必要输出；不默认兜底平台内部集成'],
    ['M5采集', '外协清单列入7类采集及数据管理', '消费约定数据及引用；输出本层必要事件与关联信息'],
    ['M6显示', '外协清单列入UE5同步与回放', '提供约定状态、结果和时戳；联合核对关联'],
    ['M7部署', '外协清单列入部署、资源与离线包', '提供本层依赖、启动与状态说明；配合组件复现'],
], [2.8, 6.5, 8.1])
heading('接口冻结时需要拿到的内容')
p('每条相关接口应有提供方、消费方、消息或服务定义、版本、单位、坐标系、时间基准、实例与机器人身份、有效状态及错误处理说明。新方案中的话题名称是待落实的接口约定，不能仅凭文档判定系统中已经存在。')
p('新方案要求D3前冻结13类接口，尚需确定D1起算日期。中间层只核对自身相关项；命令级还是任务级、由谁导航及控制、取消和失联如何处理，仍须平台与执行方明确。桥接连通不等于任务级执行已具备。')
p('具体模型、插件、能源逻辑和执行适配的交付归属尚未由这两份文件逐项确定。平台落实承接人后，供方自测、我方测消费，双方联合验证。以上不表示各方已经共同签字确认。')
p('依据：[新1]第1.3、2、3.1节；[新2]第2至7章；既定中间层边界。', 9.5)

page('14 参数生命周期与采集数据')
p('公开参考值继续保留型号、来源和工况。新方案增加域随机化后，还须能还原某个实例、某轮实验实际采用的配置；下表是登记建议，字段名称以正式Schema为准。')
table(['记录层次', '需要保存的信息', '用途与边界'], [
    ['公开参考', '型号、数值、单位、来源版本、工况', '说明来源；不能直接充当当前生效值或验收结果'],
    ['配置基准', '模型与配置版本、基准值、适用实例或对象', '供方生成场景和参数的依据；保留未知项'],
    ['随机化设置', '启用项、范围、分布、采样时机、种子及配置版本', '由平台定义并确认可用范围；本轮不补造取值'],
    ['当轮生效值', '实例、轮次、实际采样值、仿真起始时间及配置引用', '参数注入方提供，供采集归档与必要消费'],
    ['测量结果', '运行条件、时间窗口、观测数据与结果引用', '独立验证执行效果，不用配置值代替实测值'],
], [2.8, 7.2, 7.4])
heading('七类采集数据需要逐项落实')
p('新增材料列出可见光图像、深度图、激光点云、里程计、速度、加速度、力。它们是采集数据类别，不等于每台机器人必须安装七种独立设备；各类平台的必选项、可选项和未提供项仍待明确。')
p('M5与Bridge应逐项给出产生端、消息类型、话题、单位、坐标系、配置频率、实际接收频率、时间戳及归档位置。速度、加速度等需注明来自直接测量还是计算；世界真值、里程计和显示数据分别标识。')
heading('随机化与可复现的边界')
p('新方案描述每轮开始时采样质量、摩擦、重力，并提出传感器噪声与外观随机化。随机化开关或界面配置不证明物理参数已经生效；供方应输出实际生效记录。相同种子也不能单独证明整个分布式实验完全确定。')
p('暂停、单步、倍速和重启时，数据应保持实例、轮次及时间关联。中间层按冻结约定消费所需信息；完整训练、采集与回放记录由对应模块交付。')
p('依据：[新1]第2.1、2.2、2.5、3.1节；[新2]第2至4章。', 9.5)

page('15 新平台验证与交付证据')
p('下表列新增材料的目标和应核对的证据，均不是本轮通过结果。仿真层、训练层和显示层应分别记录条件与结果；不能只凭容器Running、话题可见或截图认定全链路达标。')
table(['对象', '材料所述目标', '核对条件与证据'], [
    ['实例规模', '≥20独立实例；每实例≥50机器人', '实例和模型清单、隔离验证、硬件与负载；区分仿真就绪和训练就绪'],
    ['超实时', '复杂场景RTF≥2', '场景与配置版本、采集/渲染开关、测量窗口、各实例仿真与墙钟增量及资源占用'],
    ['UE5同步', 'P99≤100ms；外协写连续10分钟', '明确起止测点、时钟对齐、采样窗口及丢帧；保留延迟原始记录和统计方法'],
    ['恢复', '异常后30秒内自动重启', '异常注入时刻、重启与可用时刻；区分进程恢复、服务就绪和任务/训练恢复'],
    ['采集与回放', '7类数据采集；归档与时间轴回放', '逐类样本、实际频率、实例轮次和时间关联、缺失项及回放对照'],
    ['随机化', '每轮参数采样并注入', '配置、种子、当轮生效值、注入记录及可观察验证；不能只看数值变化'],
], [2.4, 4.8, 10.2])
heading('降级与验收变更单独确认')
p('新方案把1.5倍实时、200ms同步列为拟议降级，要求书面确认；本轮没有取得批准证据，仍按原目标记录。dt=0.005、headless和网络优化只是方案设置，不能直接推出RTF或延迟达标。')
heading('建议供方提供的对接资料')
p('提供锁定版本与依赖清单、实际生成配置及插件加载日志、相关正式接口和样例、参数与生效记录、采集样本及性能报告。中间层保留自身适配与消费结果，联合报告注明双方测量范围和未完成项。')
p('当前状态：本次完成资料对照与文档修订，未安装或升级依赖，未启动仿真，未核验供方实际交付，也未新增性能实测。原公开参数与既有研究证据的适用范围保持不变。')
p('依据：[新1]第2.1、2.6、5.2、5.3、7章；[新2]第2.2、5.2、6.2节。', 9.5)

new_children = [el for el in doc.element.body if el not in old_children]
for el in new_children:
    anchor.addprevious(el)

doc.core_properties.subject = '公开参考参数 旧场景机制 新平台版本接口 交付边界与验证证据'
doc.core_properties.modified = datetime(2026, 10, 27, tzinfo=timezone.utc)
doc.core_properties.revision = 2
doc.save(OUTPUT)

check = Document(OUTPUT)
assert len(check.inline_shapes) == 1
assert sum(1 for _ in check.element.iter(qn('w:hyperlink'))) == original_hyperlinks
assert len(check.tables) == 16
assert len(check.comments) == len(changes) + 1
with ZipFile(BACKUP) as before, ZipFile(OUTPUT) as after:
    media = [n for n in before.namelist() if n.startswith('word/media/')]
    assert all(before.read(n) == after.read(n) for n in media)
assert all(any(p.text == title for p in check.paragraphs) for title in [
    '12 新平台范围 版本与依据', '13 接口与交付责任', '14 参数生命周期与采集数据', '15 新平台验证与交付证据'])
manifest = {'date': '2026-10-27', 'output': str(OUTPUT), 'backup': str(BACKUP),
            'changes': changes, 'tables': len(check.tables), 'comments': len(check.comments),
            'hyperlinks_preserved': original_hyperlinks,
            'inputs': {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in [
                BACKUP, Path('C:/Users/ammo/Desktop/智能体开发训练平台技术实施方案.docx'),
                Path('C:/Users/ammo/Desktop/外协内容.docx')]}}
(ROOT / 'revision_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: manifest[k] for k in ['output', 'tables', 'comments', 'hyperlinks_preserved']}, ensure_ascii=False))
