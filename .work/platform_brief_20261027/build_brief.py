from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
SOURCE = PROJECT / '四类平台参数指标与Gazebo实现详尽调研_更新版20261027.docx'
OUT = PROJECT / '四类平台参数指标与对接要点_简明展示版.docx'
doc = Document(SOURCE)
for element in list(doc.element.body):
    if element.tag != qn('w:sectPr'):
        doc.element.body.remove(element)
for section in doc.sections:
    for paragraph in section.header.paragraphs:
        paragraph.clear()
for element in list(doc.comments._comments_elm):
    doc.comments._comments_elm.remove(element)
for rel_id, rel in list(doc.part.rels.items()):
    if rel.reltype.endswith('/image') or rel.reltype.endswith('/hyperlink'):
        doc.part.drop_rel(rel_id)
for st in ['Title', 'Heading 1', 'Heading 2', 'Normal']:
    doc.styles[st].font.color.rgb = RGBColor(0, 0, 0)
doc.styles['Normal'].font.size = Pt(11)
doc.styles['Normal'].paragraph_format.line_spacing = Pt(16)
doc.styles['Normal'].paragraph_format.space_after = Pt(6)
doc.styles['Title'].font.size = Pt(20)
doc.styles['Title'].paragraph_format.space_after = Pt(9)
doc.styles['Heading 2'].font.size = Pt(12)
doc.styles['Heading 2'].paragraph_format.space_before = Pt(9)
doc.styles['Heading 2'].paragraph_format.space_after = Pt(6)

def p(text, size=None):
    a = doc.add_paragraph(text)
    if size:
        for r in a.runs:
            r.font.size = Pt(size)
    return a

def table(headers, rows, widths, font=10):
    t = doc.add_table(rows=1, cols=len(headers))
    t.autofit = False
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, width in zip(t.columns, widths):
        c.width = Cm(width)
    borders = OxmlElement('w:tblBorders')
    for edge in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        b = OxmlElement('w:' + edge)
        for k, v in [('val', 'single'), ('sz', '5'), ('color', 'D9D9D9')]:
            b.set(qn('w:' + k), v)
        borders.append(b)
    t._tbl.tblPr.append(borders)
    for i, values in enumerate([headers] + rows):
        row = t.rows[0] if i == 0 else t.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        if not i:
            row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
        for j, (cell, val) in enumerate(zip(row.cells, values)):
            cell.width = Cm(widths[j])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            shade = OxmlElement('w:shd')
            shade.set(qn('w:fill'), '244761' if not i else ('F1F5F8' if i % 2 == 0 else 'FFFFFF'))
            cell._tc.get_or_add_tcPr().append(shade)
            margins = OxmlElement('w:tcMar')
            for edge, value in [('top', '95'), ('bottom', '95'), ('left', '105'), ('right', '105')]:
                e = OxmlElement('w:' + edge)
                e.set(qn('w:w'), value)
                e.set(qn('w:type'), 'dxa')
                margins.append(e)
            cell._tc.get_or_add_tcPr().append(margins)
            a = cell.paragraphs[0]
            a.paragraph_format.line_spacing = Pt(14)
            a.paragraph_format.space_after = Pt(0)
            a.alignment = WD_ALIGN_PARAGRAPH.CENTER if j == 0 or not i else WD_ALIGN_PARAGRAPH.LEFT
            r = a.add_run(val)
            r.bold = not i
            r.font.size = Pt(font)
            r.font.color.rgb = RGBColor.from_string('FFFFFF' if not i else '000000')
    p('').paragraph_format.space_after = Pt(0)
    return t

doc.add_paragraph('四类平台常用参数指标', 'Title')
p('先看尺寸、质量、载荷、速度、加速度、转向、续航和能源。下表沿用原调研的公开参考值，不作为四类平台的统一标准。')
table(['参数指标', '无人车 UGV', '坦克 TANK', '常规固定翼', '飞翼'], [
    ['参考对象', 'Husky A200 [1]', 'Leopard 2 A7V [2]', 'PX4 rc_cessna [3]', 'ArduPilot Zephyr [4]'],
    ['资料性质', '厂家产品资料', '厂家产品资料', '公开仿真模型', '公开仿真模型'],
    ['外形尺寸\nm', '0.99×0.67×0.39', '宽3.77—4.00\n长高未列', '整机尺寸未列', '整机尺寸未列'],
    ['总质量\nkg', '50', '＜69000', '约1.67\n各link质量合计', '1.90\n各link质量合计'],
    ['载荷\nkg', '最大75\n全地形20', '原调研未采用', '未给出', '未给出'],
    ['最大速度', '1 m/s', '≤70 km/h', '未给出', '未给出'],
    ['加减速度\nm/s²', '未给出', '未给出', '未给出', '未给出'],
    ['转向能力\n角速度或半径', '未给出', '未给出', '未给出', '未给出'],
    ['续航或航程', '平均运行3 h', '行驶里程450 km', '未给出', '未给出'],
    ['能源规格', '24 V / 20 Ah', '未给出', '未给出', '未给出'],
], [2.6, 3.7, 3.7, 3.7, 3.7])
p('“未给出”指本次引用资料未列出，不表示0。飞机总质量来自原调研的模型统计；碰撞盒尺寸不当作整机尺寸。', 10)
doc.add_heading('按平台补充的指标', level=2)
p('地面平台：驱动形式、离地间隙、坡度及越障能力。\n空中平台：翼展、参考翼面积、空速与地速、爬升率。')
doc.add_heading('填写时保留的说明', level=2)
p('每项保留型号、单位、工况和来源。厂家公布、模型配置、估算、实测分别标记；没有依据的数值留空。', 10.5)

doc.add_page_break()
doc.add_paragraph('下层对接与验证要点', 'Title')
table(['对接项', '需要统一的内容'], [
    ['机器人身份', '实例编号、机器人编号、平台类型、模型版本'],
    ['参数配置', '数值、单位、来源、配置版本；随机化后的实际生效值'],
    ['执行命令', '任务级还是速度级；坐标系、有效期及执行承接人'],
    ['状态反馈', '约定的位置、速度、能源、执行结果与时间戳'],
    ['采集数据', '图像、深度、激光、里程计、速度、加速度、力；按平台明确必选项'],
    ['异常处理', '取消、失联、重启后的状态与结果如何回报'],
], [3.2, 14.2], 10.5)
p('我方负责约定输入的对接消费、任务安排及本层记录；模型、导航和动作执行的交付方由平台明确。', 10.5)
doc.add_heading('新文件增加的平台目标', level=2)
table(['项目', '目标'], [
    ['环境', 'ROS 2 Jazzy、Ubuntu 24.04；Gazebo与插件版本待锁定'],
    ['规模', '≥20个独立实例，每实例≥50机器人；类型比例待定'],
    ['性能', '复杂场景RTF≥2；UE5同步P99≤100ms'],
    ['恢复', '异常后30秒内自动重启；明确恢复到何种可用状态'],
], [3.2, 14.2], 10.5)
p('验证记录需附硬件、场景、负载与时间基准。上述为目标，尚无本次实测；1.5x和200ms属于待确认的降级值。', 10)
doc.add_heading('资料来源', level=2)
sources = [
    ('[1] Husky A200 官方手册', 'https://docs.clearpathrobotics.com/docs_robots/outdoor_robots/husky/a200/user_manual_husky/'),
    ('[2] KNDS Leopard 2 A7V 产品资料', 'https://knds.com/en/products/systems/leopard/leopard-2-a7'),
    ('[3] PX4 rc_cessna 模型', 'https://github.com/PX4/PX4-gazebo-models/blob/main/models/rc_cessna/model.sdf'),
    ('[4] ArduPilot Zephyr 模型', 'https://github.com/ArduPilot/ardupilot_gazebo/blob/main/models/zephyr/model.sdf'),
]
for label, url in sources:
    a = doc.add_paragraph()
    a.paragraph_format.space_after = Pt(2)
    a.paragraph_format.line_spacing = Pt(12)
    rel = a.part.relate_to(url, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink', is_external=True)
    link = OxmlElement('w:hyperlink')
    link.set(qn('r:id'), rel)
    run = OxmlElement('w:r')
    props = OxmlElement('w:rPr')
    size = OxmlElement('w:sz'); size.set(qn('w:val'), '19'); props.append(size)
    color = OxmlElement('w:color'); color.set(qn('w:val'), '24577A'); props.append(color)
    run.append(props)
    text = OxmlElement('w:t'); text.text = label; run.append(text)
    link.append(run); a._p.append(link)
p('新增目标与分工依据：桌面《智能体开发训练平台技术实施方案》《外协内容》。详细插件、公式与历史说明保留在18页更新版。', 9.5)
doc.core_properties.title = '四类平台参数指标与对接要点'
doc.core_properties.subject = '常用指标 公开参考 下层对接 平台目标'
doc.save(OUT)
print(str(OUT))
