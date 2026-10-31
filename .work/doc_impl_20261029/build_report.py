# -*- coding: utf-8 -*-
"""Build the implementation report DOCX in the style of the reference document."""
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(r"D:\Desktop\MARL项目")
FIG = ROOT / ".work" / "doc_impl_20261029" / "figures"
OUT = ROOT / "资料" / "需求与任务" / "机动突击任务规划与效果判定实现说明_20261029.docx"

SONG = "宋体"
HEI = "黑体"
TNR = "Times New Roman"

GRAY_NOTE = RGBColor(0x66, 0x66, 0x66)
INK = RGBColor(0x00, 0x00, 0x00)
HEADER_FILL = "F1F3F5"
BORDER_COLOR = "D9D9D9"

# TOC 页码：首轮渲染后回填
TOC_PAGES = {
    "1 概述": 3,
    "1.1 编写目的与范围": 3,
    "1.2 任务与对象": 3,
    "1.3 总体组成": 3,
    "1.4 术语与口径": 4,
    "2 输入与初始状态": 5,
    "2.1 场景与平台初始状态": 5,
    "2.2 任务指令": 6,
    "2.3 兵力编成": 7,
    "2.4 场景几何与障碍": 7,
    "3 关键实现": 9,
    "3.1 任务规划与分配": 9,
    "3.2 指令、反馈与重规划": 9,
    "3.3 运动与避障": 10,
    "3.4 到位行为状态机": 11,
    "3.5 效果判定与逐项结算": 12,
    "3.6 工作台与回放": 13,
    "4 验证结果": 14,
    "4.1 运行配置": 14,
    "4.2 毁伤任务结果": 14,
    "4.3 压制与夺占结果": 16,
    "4.4 测试与可复现性": 16,
    "4.5 结果解读": 17,
    "5 达成情况与差距": 17,
    "5.1 需求对照": 17,
    "5.2 已达成": 18,
    "5.3 部分达成": 19,
    "5.4 未实现": 19,
    "5.5 风险与建议": 19,
    "6 附录": 20,
    "6.1 关键参数汇总": 20,
    "6.2 产物与文件": 20,
    "6.3 参考资料": 21,
}


# ------------------------------------------------------------------
# 基础工具
# ------------------------------------------------------------------
def set_run_font(run, name=SONG, size=12, bold=None, color=None, ascii_font=TNR):
    run.font.name = ascii_font
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), ascii_font)
    rFonts.set(qn("w:hAnsi"), ascii_font)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:cs"), ascii_font)


def style_font(style, name=SONG, size=12, bold=None, ascii_font=TNR):
    style.font.name = ascii_font
    style.font.size = Pt(size)
    style.font.bold = bold
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), ascii_font)
    rFonts.set(qn("w:hAnsi"), ascii_font)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:cs"), ascii_font)


def set_first_line_chars(paragraph, chars=200):
    paragraph.paragraph_format.first_line_indent = Cm(0.847)
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    ind.set(qn("w:firstLineChars"), str(chars))
    ind.set(qn("w:firstLine"), str(int(chars * 2.4)))


def add_field(paragraph, instr):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = instr
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t")
    t.text = "1"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr_text)
    run._r.append(fld_sep)
    run._r.append(t)
    run._r.append(fld_end)
    return run


def set_cell_shading(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def set_cell_margins(cell, top=60, left=85, bottom=60, right=85):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for tag, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement("w:" + tag)
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tcPr.append(mar)


def set_table_borders(table):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement("w:" + edge)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), BORDER_COLOR)
        borders.append(el)
    tblPr.append(borders)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)


def set_repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    cant = OxmlElement("w:cantSplit")
    trPr.append(cant)
    header = OxmlElement("w:tblHeader")
    trPr.append(header)


class Report:
    def __init__(self):
        self.doc = Document()
        self._setup_page()
        self._setup_styles()
        self._setup_footer()

    # ---------- 页面与样式 ----------
    def _setup_page(self):
        sec = self.doc.sections[0]
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.left_margin = Cm(2.0)
        sec.right_margin = Cm(2.0)
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.header_distance = Cm(0.8)
        sec.footer_distance = Cm(0.8)
        sec.different_first_page_header_footer = True

    def _setup_styles(self):
        styles = self.doc.styles
        normal = styles["Normal"]
        style_font(normal, SONG, 12)
        normal.font.color.rgb = INK
        pf = normal.paragraph_format
        pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf.line_spacing = 1.5
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        # 首行缩进 2 字符（样式级）
        pf.first_line_indent = Cm(0.847)
        ind = normal.element.get_or_add_pPr().find(qn("w:ind"))
        ind.set(qn("w:firstLineChars"), "200")
        ind.set(qn("w:firstLine"), "480")

        specs = {
            "Heading 1": (18, 18, 8),
            "Heading 2": (16, 12, 6),
            "Heading 3": (14, 9, 4),
        }
        for name, (size, before, after) in specs.items():
            st = styles[name]
            style_font(st, HEI, size, bold=True)
            st.font.color.rgb = INK
            pf = st.paragraph_format
            pf.first_line_indent = Cm(0)
            pPr = st.element.get_or_add_pPr()
            ind = pPr.find(qn("w:ind"))
            if ind is None:
                ind = OxmlElement("w:ind")
                pPr.append(ind)
            ind.set(qn("w:firstLineChars"), "0")
            ind.set(qn("w:firstLine"), "0")
            ind.set(qn("w:leftChars"), "0")
            ind.set(qn("w:left"), "0")
            pf.space_before = Pt(before)
            pf.space_after = Pt(after)
            pf.line_spacing = 1.25
            pf.keep_with_next = True

        title = styles["Title"]
        style_font(title, HEI, 24, bold=True)
        title.font.color.rgb = INK
        title_pPr = title.element.get_or_add_pPr()
        for bdr in title_pPr.findall(qn("w:pBdr")):
            title_pPr.remove(bdr)

        caption = styles["Caption"]
        style_font(caption, SONG, 10.5)
        caption.font.color.rgb = INK
        pf = caption.paragraph_format
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf.space_before = Pt(3)
        pf.space_after = Pt(12)
        pf.line_spacing = 1.0
        pf.first_line_indent = Cm(0)
        pf.keep_with_next = True

        table_text = styles.add_style("Table Text", 1)  # paragraph style
        table_text.base_style = styles["Normal"]
        style_font(table_text, SONG, 10.5, ascii_font="Calibri")
        pf = table_text.paragraph_format
        pf.first_line_indent = Cm(0)
        pf.line_spacing = 1.1
        pf.space_before = Pt(2)
        pf.space_after = Pt(2)
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER

        code = styles.add_style("Code Block", 1)
        code.base_style = styles["Normal"]
        style_font(code, SONG, 10, ascii_font="Consolas")
        pf = code.paragraph_format
        pf.first_line_indent = Cm(0)
        pf.left_indent = Cm(0.6)
        pf.line_spacing = 1.2
        pf.space_before = Pt(3)
        pf.space_after = Pt(3)
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT

    def _setup_footer(self):
        sec = self.doc.sections[0]
        footer = sec.footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("— ")
        set_run_font(run, SONG, 9, color=GRAY_NOTE)
        field_run = add_field(p, " PAGE ")
        set_run_font(field_run, SONG, 9, color=GRAY_NOTE)
        run2 = p.add_run(" —")
        set_run_font(run2, SONG, 9, color=GRAY_NOTE)
        # 首页（封面）不显示页码：first_page_footer 留空
        sec.first_page_footer.paragraphs[0].text = ""

    # ---------- 内容构件 ----------
    def para(self, text, indent=True):
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = p.add_run(text)
        set_run_font(run, SONG, 12)
        if indent:
            set_first_line_chars(p, 200)
        return p

    def lead_para(self, lead, rest):
        """加粗引语 + 正文，如“任务目标：……”。"""
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        r1 = p.add_run(lead)
        set_run_font(r1, SONG, 12, bold=True)
        r2 = p.add_run(rest)
        set_run_font(r2, SONG, 12)
        set_first_line_chars(p, 200)
        return p

    def note(self, text):
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = p.add_run(text)
        set_run_font(run, SONG, 12, color=GRAY_NOTE)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        return p

    def bullet(self, text, bold_lead=None):
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        r0 = p.add_run("● ")
        set_run_font(r0, SONG, 10.5, color=RGBColor(0x1F, 0x5F, 0x4A))
        if bold_lead:
            r1 = p.add_run(bold_lead)
            set_run_font(r1, SONG, 12, bold=True)
        r2 = p.add_run(text)
        set_run_font(r2, SONG, 12)
        p.paragraph_format.left_indent = Cm(0.85)
        p.paragraph_format.first_line_indent = Cm(-0.85)
        return p

    def heading(self, text, level=1):
        p = self.doc.add_paragraph(style="Heading %d" % level)
        run = p.add_run(text)
        set_run_font(run, HEI, {1: 18, 2: 16, 3: 14}[level], bold=True)
        return p

    def caption(self, text):
        p = self.doc.add_paragraph(style="Caption")
        run = p.add_run(text)
        set_run_font(run, SONG, 10.5)
        return p

    def figure(self, filename, width_cm, caption):
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.keep_with_next = True
        run = p.add_run()
        run.add_picture(str(FIG / filename), width=Cm(width_cm))
        self.caption(caption)

    def table(self, caption, headers, rows, widths, align=None):
        self.caption(caption)
        table = self.doc.add_table(rows=0, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        set_table_borders(table)
        for i, w in enumerate(widths):
            table.columns[i].width = Cm(w)
        align = align or ["center"] * len(headers)
        # header
        header_row = table.add_row()
        set_repeat_header(header_row)
        for i, text in enumerate(headers):
            cell = header_row.cells[i]
            cell.width = Cm(widths[i])
            set_cell_shading(cell, HEADER_FILL)
            set_cell_margins(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.style = self.doc.styles["Table Text"]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(str(text))
            set_run_font(run, SONG, 12, bold=True)
        # body
        for row in rows:
            tr = table.add_row()
            for i, text in enumerate(row):
                cell = tr.cells[i]
                cell.width = Cm(widths[i])
                set_cell_margins(cell)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                p = cell.paragraphs[0]
                p.style = self.doc.styles["Table Text"]
                p.alignment = {"center": WD_ALIGN_PARAGRAPH.CENTER,
                               "left": WD_ALIGN_PARAGRAPH.LEFT}[align[i]]
                run = p.add_run(str(text))
                set_run_font(run, SONG, 10.5)
        # 表头与前两行跟随标题留在同页；其余允许跨页，避免整张表被推到下一页
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            trPr.append(OxmlElement("w:cantSplit"))
        for row in table.rows[:3]:
            for cell in row.cells:
                for para in cell.paragraphs:
                    para.paragraph_format.keep_with_next = True
        # 段后留白
        spacer = self.doc.add_paragraph(style="Normal")
        spacer.paragraph_format.space_after = Pt(4)
        spacer.paragraph_format.first_line_indent = Cm(0)
        spacer.paragraph_format.line_spacing = 0.6
        return table

    def code(self, lines):
        for i, line in enumerate(lines):
            p = self.doc.add_paragraph(style="Code Block")
            run = p.add_run(line)
            set_run_font(run, SONG, 9.5, ascii_font="Consolas")
            if i < len(lines) - 1:
                p.paragraph_format.keep_with_next = True

    def page_break(self):
        from docx.enum.text import WD_BREAK
        p = self.doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0)
        p.add_run().add_break(WD_BREAK.PAGE)

    def toc_entry(self, text, page, level=1):
        p = self.doc.add_paragraph(style="Normal")
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.left_indent = Cm(0 if level == 1 else 0.9)
        p.paragraph_format.space_before = Pt(3 if level == 1 else 0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.12
        tab_stops = p.paragraph_format.tab_stops
        tab_stops.add_tab_stop(Cm(16.9), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        run = p.add_run(text)
        set_run_font(run, HEI if level == 1 else SONG, 11.5 if level == 1 else 10.5, bold=(level == 1))
        run2 = p.add_run("\t" + str(page))
        set_run_font(run2, SONG, 10.5)
        return p

    # ---------- 封面 / 目录 ----------
    def cover(self):
        for _ in range(8):
            p = self.doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.0
        p = self.doc.add_paragraph(style="Title")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("机动突击任务规划")
        set_run_font(run, HEI, 24, bold=True)
        run.add_break()
        run2 = p.add_run("与效果判定实现说明")
        set_run_font(run2, HEI, 24, bold=True)
        # 副标题
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_before = Pt(18)
        run = p.add_run("—— ASL-CITY-1 城市十字路口建筑群演示")
        set_run_font(run, SONG, 14, color=RGBColor(0x59, 0x59, 0x59))
        for _ in range(6):
            p = self.doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.0
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        run = p.add_run("2026 年 10 月 29 日")
        set_run_font(run, SONG, 12)
        # 底部说明
        for _ in range(18):
            p = self.doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.0
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        run = p.add_run("内部技术说明 · 基于本地仿真替身与桩判定评估 · 不作为验收结论")
        set_run_font(run, SONG, 10.5, color=GRAY_NOTE)
        self.page_break()

    def toc(self, entries):
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(18)
        run = p.add_run("目 录")
        set_run_font(run, HEI, 18, bold=True)
        for text, level in entries:
            page = TOC_PAGES.get(text, "00")
            self.toc_entry(text, page, level)
        self.page_break()


# ------------------------------------------------------------------
# 正文内容
# ------------------------------------------------------------------
def build_content(r):
    # ============ 1 概述 ============
    r.heading("1 概述", 1)
    r.heading("1.1 编写目的与范围", 2)
    r.para("本文说明“机动突击”演示任务的实现范围、技术路径、已实现能力与验证结果，"
           "并如实列出与需求之间的差距。文件面向项目组内部评审和甲方沟通，"
           "不作为装备性能、实兵运用或实装接口的验收结论。")
    r.para("本文对应任务编号 ASL-CITY-1：在甲方提供的 SDF 城市场景中，"
           "对带有小十字路口的建筑群实施一次多类型兵力协同突击，"
           "按毁伤、压制、夺占三类效果之一进行判定。文中出现的数值均来自本机运行记录，"
           "除注明“模型参数”“暂定值”外，均为本次运行的实际输出。")
    r.heading("1.2 任务与对象", 2)
    r.lead_para("任务目标：", "对指定目标产生规定效果，并在规定时间窗内完成；"
                             "效果由外部评估接口判定。弹药耗尽、目标消失、超时、被迫撤离属于终止条件，"
                             "只有达到规定效果才计为成功。")
    r.para("目标点取 SDF 中 env_city_square 广场中心 (-95, -145)。广场为 34 m × 34 m，"
           "南北向与东西向两条城市道路在此交叉；四角为 4 栋民居（House 1–4，"
           "x = -137 / -53，y = -185 / -105），东西两侧为 2 栋办公楼（Office 1/2，"
           "x = -165 / -25，y = -145），共同构成“带小十字路口的建筑群”。")
    r.para("任务要求把“指令发送、平台到位、动作结束、效果达成”作为四个不同事实分别记录、"
           "分别核验：平台到位不等于动作完成，动作完成不等于效果达成，效果达成还需评估接口回传确认。")
    r.heading("1.3 总体组成", 2)
    r.para("实现分为五层，层间通过场景文件、指令消息和运行记录衔接（图 1）："
           "输入层提供任务指令、兵力编成与 SDF 初始状态；规划层完成能力过滤、代价打分、"
           "分配求解、时序排程、冲突消解与方案校验，并支持滚动重规划；"
           "指令与执行层负责幂等下发、反馈核对，以及地面 A* 绕障、空中直飞和五阶段行为状态机；"
           "判定层按毁伤、压制、夺占三类效果逐项结算，并通过可插拔接口调用评估；"
           "呈现层把轨迹、事件、阶段与结果组织为可回放的工作台。")
    r.figure("fig1_architecture.png", 14.6, "图 1 系统组成与运行闭环")
    r.para("实现全部基于 Python 标准库和本地浏览器前端，运行于 Windows 单机，"
           "底层使用本地逐步运动替身，不连接 ROS、Gazebo 或真实平台。"
           "规划、执行、判定各自保留独立数据，界面只读运行记录，不额外生成结论。")
    r.heading("1.4 术语与口径", 2)
    r.para("为避免“动作结束即成功”“仿真值当实测值”等歧义，本文使用以下口径（表 1）。")
    r.table("表 1 术语与口径",
            ["术语", "含义", "本实现的处理"],
            [
                ["任务 / 作业", "一次完整的突击任务，含目标、时间窗、兵力和效果要求", "以 job_id 标识，本演示为 ASL-CITY-1"],
                ["平台", "参与任务的无人平台，含轮式、履带、固定翼、飞翼四类", "以 robot_no / pid 标识，起点取自 SDF"],
                ["效果", "毁伤、压制、夺占三类结果之一", "以 effect_kind 标识，可按运行切换"],
                ["判定", "由评估接口按规则给出的逐项结论", "绑定本任务、本目标与当前执行版本 attempt"],
                ["桩判定", "按开火与占位日志的确定性规则模拟的判定，非真实裁决", "verified=false，界面标注“桩判定·未验证”"],
                ["场景单位", "本演示的坐标与长度单位，1 单位 = 1 m", "与 SDF 米制坐标一致，未缩放"],
                ["事实分离", "指令、到位、动作、效果、确认分别记录", "各有独立事件与时间戳，不相互替代"],
            ],
            widths=[3.2, 7.2, 6.4], align=["center", "left", "left"])
    r.note("注：本文中的“成功”只表示本次运行按规则达到规定效果并完成确认，"
           "不代表长期成功率，也不代表装备已具备该能力。")

    # ============ 2 输入与初始状态 ============
    r.heading("2 输入与初始状态", 1)
    r.heading("2.1 场景与平台初始状态", 2)
    r.para("规划开始时的“场上有什么”由甲方 SDF 直接提取，不手工填报。提取脚本解析 "
           "container_00_combined_scene.sdf，生成场景初始状态文件，内容包括 50 台平台的位姿与尺寸、"
           "39 个静态障碍、5 段道路/广场和 14 处地标。两块湿地与山体只有模型引用、本地没有几何，"
           "统一列入缺项清单，不臆造形状。")
    r.para("平台按号段分为四类，初始位姿直接取 SDF 的 model pose；三维尺寸取碰撞几何的外包络，"
           "用于避障膨胀与图上比例，不代表厂商实测外形（表 2）。")
    r.table("表 2 平台类别与三维尺寸",
            ["类别", "号段", "底盘/机体", "整机包络", "包络半径", "初始高度"],
            [
                ["轮式 UGV", "1–20", "2.011 × 1.000 × 0.569", "2.011 × 1.850 × 0.875", "1.366", "0.35"],
                ["履带 TANK", "21–30", "2.011 × 1.000 × 0.569", "2.011 × 1.850 × 0.875", "1.366", "0.35"],
                ["固定翼 PLANE", "31–40", "—", "1.000 × 2.000 × 0.200", "1.118", "6.00"],
                ["飞翼 WING", "41–50", "—", "1.000 × 2.000 × 0.200", "1.118", "10.00"],
            ],
            widths=[2.6, 2.2, 3.8, 3.8, 2.2, 2.2],
            align=["center", "center", "center", "center", "center", "center"])
    r.note("注：表中长度单位为米（m）。轮式与履带平台在 SDF 中共用同一代理碰撞盒，因此包络尺寸相同；"
           "履带外观差异来自视觉网格，不改变碰撞几何。空中平台的包络为简化盒体。")
    r.heading("2.2 任务指令", 2)
    r.para("任务以结构化指令下达，包含目标、时间窗、效果要求、执行与确认截止、兵力编成和交战规则。"
           "本演示的指令参数见表 3。")
    r.table("表 3 任务指令参数",
            ["参数", "取值", "说明"],
            [
                ["任务编号", "ASL-CITY-1", "本演示唯一标识"],
                ["目标", "JUNCTION-CROSS-01（-95, -145）", "十字路口建筑群中心，点目标"],
                ["时间窗", "0–700 s", "效果须在窗内达成"],
                ["效果类型", "毁伤（可切换压制 / 夺占）", "默认毁伤，要求等级 ≥ 6.0"],
                ["执行截止", "520 s", "超时按终止处理"],
                ["确认截止", "120 s（自动作结束起）", "评估未回传按未达成处理"],
                ["撤离", "撤至 (-75, -130)，环半径 7 m，限 200 s", "撤离完成单独记录"],
                ["兵力", "6 台，四类平台", "侦察指示 1、突击 4、评估 1"],
                ["交战规则", "仅打击经侦察指示的目标", "正识别要求已开启"],
            ],
            widths=[2.8, 7.8, 6.2], align=["center", "left", "left"])
    r.heading("2.3 兵力编成", 2)
    r.para("兵力包按角色编成，而不是同型平台堆叠。侦察指示组由固定翼承担，前出至观察位完成目标指示；"
           "突击组由两台履带、两台轮式组成，分进至 4 个执行位；评估组由飞翼承担，"
           "前出至评估观察位并在位发起评估（表 4）。平台起点均取自 SDF，不改写。")
    r.table("表 4 兵力编成与角色",
            ["角色", "平台", "类别", "巡航高度", "载荷", "职责"],
            [
                ["侦察指示组", "rover_31", "固定翼", "30 m", "2.0", "观察位 (-70,-145)，完成目标指示"],
                ["突击组", "rover_21 / 22", "履带", "地面", "8.0", "主攻与压制，进入执行位"],
                ["突击组", "rover_01 / 11", "轮式", "地面", "6.0", "两翼协同，进入执行位"],
                ["评估组", "rover_41", "飞翼", "25 m", "1.5", "评估观察位 (-95,-120)，发起评估"],
            ],
            widths=[3.0, 3.0, 2.0, 2.2, 1.6, 5.0],
            align=["center", "center", "center", "center", "center", "left"])
    r.para("这里有一个容易被忽略的约束：任务级载荷要求为 4.0，若对全部成员一刀切，"
           "载荷 1.5 的评估飞翼会被挡在编队之外；若为放飞机而把任务载荷降到 1.5，"
           "突击组的战斗载荷要求又会被一并废掉。实现采用角色级校核：突击组按 4.0，"
           "侦察与评估组按 0.5（只带传感器）。规划器先核一次，行为层在收到成员后再核一次，"
           "不达标直接终止并记录 role_infeasible，避免“不合理的编成跑完也算成功”。")
    r.heading("2.4 场景几何与障碍", 2)
    r.para("建筑在 SDF 中以模型引用给出，本身没有尺寸。实现从本地模型文件读取显式盒体或 "
           "DAE 包围盒（含缩放），换算为平面占地；规划与显示使用同一套几何，"
           "避免“图上画的和规划躲的不是同一块”。全场景共 39 处静态障碍，"
           "进入本演示规划范围（x ∈ [-185, 20]、y ∈ [-210, 30]）的为 13 处："
           "7 处花坛/标识柱与 6 栋建筑（表 5）。")
    r.table("表 5 建筑占地（DAE 包围盒）",
            ["建筑", "占地（m × m）", "高度（m）", "图中位置"],
            [
                ["民居 1 / 4", "16.49 × 12.93", "7.69", "西北 / 东北"],
                ["民居 2", "12.71 × 9.77", "7.19", "东南"],
                ["民居 3", "13.17 × 8.71", "9.17", "西南"],
                ["办公楼 1 / 2", "17.70 × 17.70", "18.66", "西侧 / 东侧"],
            ],
            widths=[3.4, 4.6, 3.2, 5.6], align=["center", "center", "center", "center"])
    r.figure("fig3_global.png", 14.4, "图 2 全局态势：十字路口建筑群、道路与目标点")
    r.para("图 2 中，浅色底图是 SDF 的道路与广场，蓝灰色块为 6 栋建筑，红色准星为目标点，"
           "任务区取景与右侧缩略图分别回答“目标周边是什么”和“目标在全场景中的位置”。")

    # ============ 3 关键实现 ============
    r.heading("3 关键实现", 1)
    r.heading("3.1 任务规划与分配", 2)
    r.para("规划采用规则化六步流程，目的是把“谁去、何时去、能不能去”讲清楚，并让每次决策可追溯（表 6）。"
           "规划结果以指派（平台、作业、开工与完工时刻）形式输出，滚动重规划时保持已派出成员的承诺，"
           "避免开工基准反复后移。")
    r.table("表 6 规划流程与实现",
            ["步骤", "内容", "实现要点"],
            [
                ["能力过滤", "高度、载荷、传感器、续航、运动性能", "载荷按角色校核；续航按全程里程估算"],
                ["代价打分", "完工时间、能耗、空间分散度", "目标可切换，权重组内固定"],
                ["分配求解", "目标—平台配对", "单人作业用匈牙利；多人作业按代价排序取足额"],
                ["时序排程", "开工、完工与窗口", "真实运动下按到达时间反推出发时刻"],
                ["冲突消解", "同一平台串行、协同人数不足", "能修则修，结构性不足显式上报"],
                ["方案校验", "叠加续航与窗口复核", "校验不过的方案整单撤下，不拆分下发"],
            ],
            widths=[2.8, 6.6, 7.4], align=["center", "left", "left"])
    r.para("续航闸门把“集结环 + 执行环 + 撤离环”的全程里程计入估算，而不是只算到作业点的直线距离。"
           "这条规则来自一次真实暴露的问题：早期只按直线距离估电，平台在行为段中途电量归零，"
           "作业却仍被判成功。现在不满足全程续航的平台在规划阶段就会被拒绝，"
           "报告里明确写成“续航不足（全程……需……剩……）”，不再事后解释。")
    r.heading("3.2 指令、反馈与重规划", 2)
    r.para("中间层与执行替身之间只通过 JSON 消息交互，消息骨架保证“发出去、收得到、对得上、可重试”（表 7）。"
           "指令带 command_id 与 attempt：重复下发按幂等处理；反馈按身份、时间、进度核对；"
           "超时只请求取消，不直接改状态；失败允许有限次重试。执行侧还有第二道能力闸门，"
           "防止上层漏检的能力约束直接落到平台。")
    r.table("表 7 消息与反馈要素",
            ["要素", "作用", "本实现的处理"],
            [
                ["command_id", "指令唯一标识", "重发返回同一回执，避免重复执行"],
                ["attempt", "执行版本", "结果与评估绑定当前版本，重试即新版本"],
                ["反馈核对", "身份、时间、进度", "不匹配的反馈不采纳，单独记录"],
                ["超时", "在途停滞或超窗", "请求取消并确认，再按规则重试或终止"],
                ["成员变化", "失联或补充", "触发重规划，保持其余成员承诺"],
                ["周期更新", "滚动优化", "按固定周期重排未开工部分"],
            ],
            widths=[3.0, 6.4, 7.4], align=["center", "left", "left"])
    r.para("重规划触发源包括首次规划、周期更新、成员变化、执行失败、超时和进度偏差。"
           "六类触发各自独立记录，报告里可以分开统计，不把“重规划次数”混成一个指标。")
    r.heading("3.3 运动与避障", 2)
    r.para("地面平台在已知静态地图上做膨胀栅格 A*，空中平台按巡航高度直飞。"
           "两者共用同一套坐标与障碍，但避障语义不同：地面必须绕开建筑，"
           "空中按“建筑高度低于巡航高度”的假设越障（表 8）。")
    r.table("表 8 运动与避障参数",
            ["项", "取值", "说明"],
            [
                ["栅格分辨率", "0.5 m", "场景约 205 × 150 m"],
                ["膨胀半径", "1.75 m", "平台包络 1.366 m 加安全余量"],
                ["平滑", "整段可通行才走捷径", "不做切角，避免贴墙"],
                ["跟随", "视线前瞻点 + 前向安全投影", "被挡即局部重规划"],
                ["空中", "直飞 + 爬升率 8 m/s（仿真）", "巡航 30 m / 25 m，z 写入反馈"],
                ["点位吸附", "最近可通行点，记录偏移", "不悄悄挪点"],
            ],
            widths=[3.2, 6.6, 6.8], align=["center", "left", "left"])
    r.para("本次运行中，4 台地面平台的接近路线全部被民居 4 挡住，A* 路径相对直线绕行 1.6%–5.2%，"
           "规划净空 1.8–1.9 m；两台空中平台按 30 m / 25 m 直飞越障。"
           "图 3 把“被挡直线”和“实际路径”画在同一张图上，避免把近似直线的绕行看成没有避障。")
    r.figure("fig4_approach.png", 14.4, "图 3 地面绕障接近与空中直飞（红虚线为被挡直线）")
    r.note("注：绕行比只有 1.02–1.05，直观上接近直线；这不是避障失效，而是建筑只挡住了斜穿角。"
           "本演示是已知静态地图上的路径规划，不是 SLAM，也没有动态障碍。")
    r.heading("3.4 到位行为状态机", 2)
    r.para("到达作业区后，平台不再“原地刷进度”，而是进入按任务类型定义的行为状态机。"
           "机动突击分为五个阶段：机动、到位、执行、结果确认、撤离（表 9）。"
           "侦察组先到观察位并完成目标指示，突击组按“同时到达”分配出发偏移，"
           "评估组前出评估观察位；执行阶段受攻击窗口与执行截止约束。")
    r.table("表 9 机动突击五阶段",
            ["阶段", "进入条件", "主要动作", "记录"],
            [
                ["机动", "指令下发", "各平台按角色前往集结区或观察位", "受领、到达、指示"],
                ["到位", "突击组全部到达集结区", "计算同时到达偏移并等待", "全员到位、同时性"],
                ["执行", "释放时刻到达", "进入执行位；侦察指示后开火/压制/占控", "开火、覆盖、控制"],
                ["结果确认", "动作结束", "评估组在位发起评估，等待回传", "评估发起/回传、逐项结果"],
                ["撤离", "结果确认成功", "撤至收拢点并核对时限", "撤离完成、用时"],
            ],
            widths=[2.4, 4.8, 5.4, 4.2], align=["center", "left", "left", "left"])
    r.para("“同时到达”不是让所有平台同时出发，而是按各自路径长度与速度反推释放时刻，"
           "让最慢的先走、最快的后走。这样既保持协同，又不会在集结区无效等待。")
    r.heading("3.5 效果判定与逐项结算", 2)
    r.para("效果判定按三类规则执行，每类都有明确的主成功标准、辅助指标和终止条件（表 10）。"
           "动作结束只是进入“结果确认”，评估接口回传后才形成结论；确认截止前未回传按未达成处理。")
    r.table("表 10 三类效果判定",
            ["效果", "主成功标准", "辅助指标", "终止条件"],
            [
                ["毁伤", "目标毁伤等级不低于规定值", "命中率、弹药消耗、二次打击、我方损失", "弹药耗尽、执行超时"],
                ["压制", "目标连续被压制不低于规定时长", "覆盖时间、恢复时间、我方损失", "覆盖中断、执行超时"],
                ["夺占", "控制权保持不低于规定时长", "控制时长、敌方反击、移交与坚守", "控制丢失、执行超时"],
            ],
            widths=[2.2, 5.4, 5.8, 3.4], align=["center", "left", "left", "left"])
    r.para("逐项结算把“必需项”和“信息项”分开。必需项只有达成、未达成、待确认三种状态；"
           "信息项用于说明过程，不参与成败。总体结论遵循“必需项全部达成才算成功，"
           "任一项未达成即失败，确认截止后仍待确认按未达成”，部分达成不冒充全部成功。")
    r.para("三类效果的辅助指标在本次实现中补齐（表 11）。此前只统计少数几项，"
           "敌方反击固定写 0，命中率与损失没有进入结果，指标面板看不出“打得怎么样、代价多大”。"
           "现在每项都带数值、单位、判定与口径说明，随结果一起落盘。")
    r.table("表 11 辅助指标与口径",
            ["效果", "指标", "口径"],
            [
                ["毁伤", "命中率", "命中发数 / 发射发数（演示口径：在目标环内且有弹即命中）"],
                ["毁伤", "弹药消耗 / 二次打击", "逐发记录；未达规定等级时的补射次数"],
                ["毁伤", "我方损失", "执行期失联或被判定退出的平台数（本层只统计失联注入）"],
                ["压制", "火力覆盖时间 / 最长连续", "覆盖区间累计与最长连续段，中断后重新计时"],
                ["压制", "目标恢复时间", "无人开火超过恢复门限即视为目标恢复行动能力（模型参数）"],
                ["夺占", "控制时长 / 区间", "满足最少在位人数的连续控制时间"],
                ["夺占", "敌方反击 / 移交 / 坚守", "按周期注入的反击事件、控制移交时刻、移交后坚守时长"],
            ],
            widths=[2.2, 5.2, 8.8], align=["center", "left", "left"])
    r.para("评估接口采用可插拔协议：输入是本任务、本目标、当前执行版本与证据，"
           "输出是逐项判定和来源标识。默认实现按开火、覆盖、控制日志的确定性规则判定，"
           "verified 固定为 false，界面统一标注“桩判定·未验证”。接真实裁决或战损评估时，"
           "替换同协议实现即可，不需要改行为层与工作台。")
    r.note("注：命中判定是“占位在目标环内且有弹即命中”的演示口径，不是弹道或毁伤模型；"
           "敌方反击是按周期注入的演示事件，默认被击退、不打断控制。")
    r.heading("3.6 工作台与回放", 2)
    r.para("工作台读取运行产生的场景、报告与轨迹记录，提供全局态势、任务执行、平台状态和实验记录四个页面。"
           "任务执行页把地图、阶段、成员、路径证据和效果判定放在同一时间轴上，"
           "支持播放、暂停、逐步、倍速、拖动与阶段跳转。")
    r.para("地图上做了几处针对性处理：任务区取景并配全场景缩略图，避免把 150 m 外的出发阵地拉进来"
           "把中间拉空；平台按类目用不同形状、按任务用不同颜色，空中平台带高度牌；"
           "建筑标注“民居/办公楼”，道路广场作浅色底图；被挡直线默认显示，绕行倍数与净空直接标在图上。"
           "效果判定区先显示辅助指标卡，再列必需项结算，最后给总体结论与评估来源。")

    # ============ 4 验证结果 ============
    r.heading("4 验证结果", 1)
    r.heading("4.1 运行配置", 2)
    r.para("本文引用三次单次运行：一次毁伤、一次压制、一次夺占。三次使用同一场景、同一编成与同一运动配置，"
           "仅切换效果类型，便于横向对照（表 12）。")
    r.table("表 12 运行配置",
            ["项", "配置", "备注"],
            [
                ["场景", "asl_city（SDF 十字路口建筑群）", "13 处障碍，6 栋建筑"],
                ["编成", "6 台：2 轮式 + 2 履带 + 1 固定翼 + 1 飞翼", "起点取自 SDF"],
                ["运动", "逐步运动 + 建筑绕障 + 到位行为", "本地运动替身"],
                ["上限", "640 步（1 步 = 1 s）", "实际 299 / 308 / 316 s 结束"],
                ["规划视野", "H = 700，滚动周期 K = 25", "场景声明"],
                ["评估", "constructed_assessment_stub", "桩判定，未验证"],
            ],
            widths=[2.8, 8.2, 5.8], align=["center", "left", "left"])
    r.heading("4.2 毁伤任务结果", 2)
    r.para("毁伤运行在 299 s 结算完成，规划 12 次，无重试、无超时。"
           "受领任务后，突击组用约 164 s 完成机动集结，全员到位与突击开始相差 1 s；"
           "执行阶段持续 71 s，动作结束后 21 s 收到评估回传，随后撤离 41 s（图 4、表 13）。")
    r.figure("fig2_timeline.png", 16.0, "图 4 毁伤运行的阶段时序")
    r.table("表 13 毁伤运行阶段时刻",
            ["阶段", "时刻（s）", "说明"],
            [
                ["受领任务", "1", "指令下发并受理"],
                ["全员到位", "165", "突击组到达集结区，侦察组已在观察位"],
                ["突击开始", "166", "释放偏移生效，进入执行"],
                ["动作结束", "237", "效果达成，进入结果确认"],
                ["评估回传 / 确认", "258", "桩判定回传，确认项达成"],
                ["撤离完成 / 结算", "299", "撤至收拢点，总体结论形成"],
            ],
            widths=[4.2, 3.8, 8.8], align=["center", "center", "left"])
    r.table("表 14 毁伤运行结果",
            ["类别", "结果项", "结论", "依据"],
            [
                ["必需项", "毁伤等级不低于规定值", "达成", "等级 8.0 ≥ 6.0"],
                ["必需项", "效果在规定时间窗内达成", "达成", "达成时刻 237 s，窗口 0–700 s"],
                ["必需项", "结果确认（评估回传）", "达成", "评估回传 258 s"],
                ["信息项", "命中率", "1.0", "8 发 8 中"],
                ["信息项", "弹药消耗", "8 发", "四台突击平台各余弹 4 发"],
                ["信息项", "二次打击需求", "1 次", "未达等级时补射一次"],
                ["信息项", "我方损失", "0 台", "执行期无失联"],
                ["总体", "任务结论", "成功", "桩判定·未验证"],
            ],
            widths=[2.4, 6.6, 2.6, 5.2], align=["center", "left", "center", "left"])
    r.heading("4.3 压制与夺占结果", 2)
    r.para("切换效果类型后，同一编成在 308 s / 316 s 完成。压制运行形成 12 s 连续覆盖，"
           "无中断；夺占运行建立 10 s 控制，期间发生 1 次敌方反击并被击退，"
           "控制于 243 s 移交，移交后坚守 10 s（表 15）。")
    r.table("表 15 三类效果结果对照",
            ["效果", "完成时刻", "主成功标准", "关键辅助指标"],
            [
                ["毁伤", "299 s", "等级 8.0 ≥ 6.0", "命中率 1.0、弹药 8 发、二次打击 1 次、损失 0"],
                ["压制", "308 s", "连续压制 12 s ≥ 10 s", "覆盖 12 s、中断 0、恢复时间 3 s（模型）、损失 0"],
                ["夺占", "316 s", "控制 10 s ≥ 10 s，移交后坚守 10 s", "控制区间 1 段、反击 1 次、移交 243 s、损失 0"],
            ],
            widths=[2.2, 2.6, 5.4, 6.6], align=["center", "center", "left", "left"])
    r.note("注：三次运行均为单次结果，不是统计样本；压制与夺占的完成时刻较毁伤晚，"
           "原因是效果达成条件不同，不是平台性能差异。")
    r.heading("4.4 测试与可复现性", 2)
    r.para("当前测试集共 120 项，全部通过。其中新增 11 项覆盖本轮能力：SDF 提取值与场景起点一致、"
           "角色级载荷校核、空地面分流与爬升高度、角色闸门、毁伤/损失/夺占辅助指标。"
           "既有回归覆盖机动非瞬移、续航闸门、六作业收尾、消息骨架与效果判定十条验收。")
    r.code([
        "cd planning_middle_demo",
        "py -3.14 sdf_state.py",
        "py -3.14 run_demo_v2.py --scenario scenarios/asl_city.json \\",
        "        --motion real --avoid --behavior --max-ticks 640 \\",
        "        --out outputs/asl_city_mixed",
        "py -3.14 -m unittest discover -s tests -q",
    ])
    r.para("工作台可直接打开预置运行，也可在“新建演示”中切换效果类型重新运行；"
           "每次运行写入独立目录，结果文件包括 report.json、trace.jsonl、report.html 与 trajectory.html，"
           "原始记录不被覆盖。")
    r.heading("4.5 结果解读", 2)
    r.para("三点需要说明。第一，三次运行都是单次结果，不能据此给出成功率或置信区间；"
           "第二，评估为桩判定，命中率、控制时长等是过程口径，不是外部裁决；"
           "第三，运行在本机运动替身上完成，时间和位置是仿真值，不等于实装性能。"
           "因此本文只做“功能是否走通、记录是否自洽”的判断，不做能力排名。")

    # ============ 5 达成与差距 ============
    r.heading("5 达成情况与差距", 1)
    r.heading("5.1 需求对照", 2)
    r.para("按需求中“作用对象、区域、时间、兵力、能力”和“编队决策要素”逐条对照，"
           "结论分为达成、部分达成、未实现三类（表 16）。")
    r.table("表 16 需求对照",
            ["需求条目", "本实现", "结论"],
            [
                ["任务目标与成功标准", "三类效果、时间窗、逐项结算、评估接口", "达成（评估为桩）"],
                ["作用对象", "点目标（十字路口建筑群），含区域环", "部分达成（未建单位/编队目标模型）"],
                ["区域", "集结区、接近路线、执行位、撤离点", "达成（接近路线由 A* 生成）"],
                ["时间", "攻击窗口、到达、执行、评估时延、撤离时限", "达成"],
                ["兵力", "侦察指示组、突击组、评估组", "部分达成（缺压制组、掩护组）"],
                ["能力", "角色载荷、续航、高度、传感器过滤", "部分达成（未做能力等级分级）"],
                ["任务分配", "能力过滤 + 代价 + 分配 + 排程 + 消解 + 校验", "达成（单波次）"],
                ["队形", "未建模横队、纵队、楔形、梯队", "未实现"],
                ["协同关系", "同时到达、先后顺序、目标指示", "部分达成（无牵制与压制分工）"],
                ["航路 / 路径", "A* 绕障、空中直飞、撤离路径", "达成（未做地形遮蔽与低空突防）"],
                ["通信拓扑", "未建模通信链路、静默与简令", "未实现"],
                ["规则约束", "交战规则字段、正识别标志", "部分达成（无禁飞区、附带损伤评估）"],
                ["攻防时序", "侦察—机动—占位—打击—评估—撤离", "达成（无“转坚守”分支）"],
            ],
            widths=[3.8, 8.2, 4.8], align=["center", "left", "left"])
    r.heading("5.2 已达成", 2)
    for lead, text in [
        ("任务闭环，", "从任务下达、规划、下发、执行、判定到回放完整走通，运行可复现、记录可追溯。"),
        ("效果判定，", "毁伤、压制、夺占三类效果均有规则、逐项结算与终止条件，评估结果绑定任务、目标与执行版本。"),
        ("多类型编成，", "四类平台按角色编成，起点与尺寸来自 SDF；角色级载荷校核避免“一刀切”。"),
        ("空地面分流，", "地面按包络绕障，空中按巡航高度直飞，高度写入反馈与回放。"),
        ("避障证据，", "同一张图给出实际路径、被挡直线、绕行倍数与规划净空，图上所见即规划所避。"),
        ("指标补齐，", "命中率、弹药、二次打击、损失、覆盖、恢复、控制、反击、移交均有数值与判定。"),
        ("可读性，", "任务区取景、缩略图、类型图标、高度牌、阶段卡片与成员轨道，把“谁在哪、到哪一步”讲清楚。"),
    ]:
        r.lead_para(lead, text)
    r.heading("5.3 部分达成", 2)
    r.para("部分达成的项集中在“有框架、缺细节”：评估接口已可插拔但未接真实裁决；"
           "兵力有角色但缺压制组、掩护组；协同有同时到达与指示，但缺牵制、压制分工与波次；"
           "规则有交战规则与正识别字段，但禁飞区、附带损伤评估、禁止目标清单尚未进入执行判定；"
           "能力过滤有载荷、续航、高度、传感器，但没有按能力等级分级。")
    r.heading("5.4 未实现", 2)
    r.para("未实现的项主要是编队与通信层面的建模，以及真实执行链路（表 17）。"
           "这些项没有被界面或报告“补出来”，本文按实际状态列出。")
    r.table("表 17 主要差距",
            ["差距", "影响", "建议优先级"],
            [
                ["评估接口为桩", "效果结论无外部背书", "高：接真实裁决/战损评估"],
                ["无队形与通信拓扑", "编队决策要素不完整", "高：先做队形保持与通信可达性"],
                ["无动态障碍与感知", "避障只对已知静态地图成立", "中：接 ROS/Gazebo 与感知"],
                ["无压制组/掩护组", "兵力包角色不全", "中：按角色扩编与分工"],
                ["无多波次与转坚守", "任务样式单一", "中：扩展波次与阶段分支"],
                ["单次运行、无统计", "不能给成功率", "中：多种子与置信区间"],
                ["平台参数为暂定值", "与实装性能不一致", "高：替换甲方实测数据"],
            ],
            widths=[5.2, 6.8, 4.8], align=["left", "left", "left"])
    r.heading("5.5 风险与建议", 2)
    r.para("最需要优先处理的是评估接口与平台参数：前者决定“成功”是否有外部依据，"
           "后者决定规划结果是否可信。建议先以甲方实测数据替换暂定参数，再把评估从桩判定换成真实接口，"
           "之后补队形、通信与压制/掩护角色，最后扩展多波次与统计评估。"
           "在上述工作完成前，本文的所有结论只适用于当前演示配置。")

    # ============ 6 附录 ============
    r.heading("6 附录", 1)
    r.heading("6.1 关键参数汇总", 2)
    r.table("表 18 平台能力参数（暂定值）",
            ["类别", "速度", "作业效率", "续航", "载荷", "传感器", "弹药"],
            [
                ["轮式 UGV", "0.8", "1.0", "100", "6.0", "EO", "6"],
                ["履带 TANK", "1.0", "1.2", "120", "8.0", "EO", "8"],
                ["固定翼 PLANE", "2.0", "0.6", "320", "2.0", "SAR", "2"],
                ["飞翼 WING", "1.6", "0.5", "280", "1.5", "IR", "2"],
            ],
            widths=[2.8, 2.0, 2.8, 2.0, 2.0, 2.4, 2.0],
            align=["center"] * 7)
    r.note("注：速度单位为场景单位/步；以上为演示暂定值，不是厂商实测性能；真实数据到位后只改参数表，不改规划与判定逻辑。")
    r.heading("6.2 产物与文件", 2)
    r.table("表 19 主要产物",
            ["产物", "位置", "用途"],
            [
                ["实现说明（本文）", "资料/需求与任务/…_20261029.docx", "范围、实现、结果与差距"],
                ["场景初始状态", "scenarios/sdf_initial_state.json", "平台位姿、尺寸、障碍、道路"],
                ["任务场景", "scenarios/asl_city.json", "指令参数与编成"],
                ["毁伤运行", "outputs/workbench_20261029_181813_611337/", "报告、轨迹与回放"],
                ["压制运行", "outputs/asl_city_suppress/", "同上"],
                ["夺占运行", "outputs/asl_city_seize/", "同上"],
                ["工作台截图", "outputs/工作台_20261029_多类型兵力包/", "本文图 2–4 的来源"],
            ],
            widths=[3.0, 8.6, 5.2], align=["center", "left", "left"])
    r.note("注：除实现说明外，表中路径均相对 planning_middle_demo/。")
    r.heading("6.3 参考资料", 2)
    for item in [
        "[1] 无人集群编队五类任务定义（2026-10-28），本项目资料目录。",
        "[2] T-ASL 效果判定与逐项结算实现规范（2026-10-29），本项目资料目录。",
        "[3] container_00_combined_scene.sdf，甲方提供的城市场景文件。",
        "[4] planning_middle_demo/README_v2.md，实现说明与运行方式。",
        "[5] planning_middle_demo/docs/场景与平台数据记录.md，场景与平台数据口径。",
    ]:
        p = r.doc.add_paragraph(style="Normal")
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.line_spacing = 1.4
        run = p.add_run(item)
        set_run_font(run, SONG, 10.5)
    r.para("以上资料与运行记录随项目一并保存；复现时请使用独立输出目录，不要覆盖已有记录。")


TOC_ENTRIES = [
    ("1 概述", 1), ("1.1 编写目的与范围", 2), ("1.2 任务与对象", 2),
    ("1.3 总体组成", 2), ("1.4 术语与口径", 2),
    ("2 输入与初始状态", 1), ("2.1 场景与平台初始状态", 2), ("2.2 任务指令", 2),
    ("2.3 兵力编成", 2), ("2.4 场景几何与障碍", 2),
    ("3 关键实现", 1), ("3.1 任务规划与分配", 2), ("3.2 指令、反馈与重规划", 2),
    ("3.3 运动与避障", 2), ("3.4 到位行为状态机", 2), ("3.5 效果判定与逐项结算", 2),
    ("3.6 工作台与回放", 2),
    ("4 验证结果", 1), ("4.1 运行配置", 2), ("4.2 毁伤任务结果", 2),
    ("4.3 压制与夺占结果", 2), ("4.4 测试与可复现性", 2), ("4.5 结果解读", 2),
    ("5 达成情况与差距", 1), ("5.1 需求对照", 2), ("5.2 已达成", 2),
    ("5.3 部分达成", 2), ("5.4 未实现", 2), ("5.5 风险与建议", 2),
    ("6 附录", 1), ("6.1 关键参数汇总", 2), ("6.2 产物与文件", 2), ("6.3 参考资料", 2),
]


def main():
    r = Report()
    r.cover()
    r.toc(TOC_ENTRIES)
    build_content(r)
    r.doc.core_properties.title = "机动突击任务规划与效果判定实现说明"
    r.doc.core_properties.subject = "ASL-CITY-1 城市十字路口建筑群演示"
    r.doc.core_properties.author = "MARL 项目组"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    r.doc.save(str(OUT))
    print("saved", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()






