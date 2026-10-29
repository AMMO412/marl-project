# -*- coding: utf-8 -*-
"""把 docs/任务定义_中间层V1.md 转成 docx（仿《任务定义》的排版：表格驱动、短句成行）。"""
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


def set_font(run, name="宋体", size=10.5, bold=False, color=None, mono=False):
    run.font.name = "Consolas" if mono else name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rf)
    ea = "Consolas" if mono else name
    rf.set(qn("w:eastAsia"), ea)
    rf.set(qn("w:ascii"), "Consolas" if mono else "Times New Roman")
    rf.set(qn("w:hAnsi"), "Consolas" if mono else "Times New Roman")


CODE = re.compile(r"`([^`]+)`")       # 先切代码，再在普通段里切粗体
BOLD = re.compile(r"\*\*(.+?)\*\*")   # 否则 **粗体里的 `代码`** 会被粗体整段吞掉


def add_runs(p, text, size=10.5, base_bold=False, color=None):
    """处理 `代码` 与 **粗体**，两者可嵌套。"""
    for k, seg in enumerate(CODE.split(text)):
        if not seg:
            continue
        if k % 2:                      # 捕获组 → 代码段
            set_font(p.add_run(seg), size=size, bold=base_bold,
                     color=(0xC0, 0x39, 0x2B), mono=True)
            continue
        for j, sub in enumerate(BOLD.split(seg)):
            if not sub:
                continue
            set_font(p.add_run(sub), size=size,
                     bold=(base_bold or j % 2), color=color)


def main(src, dst):
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    lines = open(src, encoding="utf-8").read().splitlines()
    i = 0
    title_done = False
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # 代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            p.paragraph_format.space_after = Pt(6)
            set_font(p.add_run("\n".join(buf)), size=9.5, mono=True)
            continue

        # 分隔线
        if s in ("---", "***"):
            i += 1
            continue

        # 表格
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw = lines[i].strip().strip("|")
                if re.match(r"^[\s:|-]+$", raw):
                    i += 1
                    continue
                rows.append([c.strip() for c in raw.split("|")])
                i += 1
            ncol = max(len(r) for r in rows)
            t = doc.add_table(rows=0, cols=ncol)
            t.style = "Table Grid"
            for ri, r in enumerate(rows):
                cells = t.add_row().cells
                for ci in range(ncol):
                    txt = r[ci] if ci < len(r) else ""
                    cell = cells[ci]
                    cell.text = ""
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_after = Pt(2)
                    p.paragraph_format.space_before = Pt(2)
                    add_runs(p, txt, size=9.5, base_bold=(ri == 0))
                    if ri == 0:
                        shd = cell._tc.get_or_add_tcPr().makeelement(
                            qn("w:shd"), {qn("w:val"): "clear", qn("w:fill"): "F2F2F2"})
                        cell._tc.get_or_add_tcPr().append(shd)
            doc.add_paragraph()
            continue

        # 标题
        if s.startswith("### "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            add_runs(p, s[4:], size=12, base_bold=True)
            i += 1
            continue
        if s.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            add_runs(p, s[3:], size=14, base_bold=True)
            i += 1
            continue
        if s.startswith("# "):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(10)
            add_runs(p, s[2:], size=18, base_bold=True)
            title_done = True
            i += 1
            continue

        # 引用
        if s.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            p.paragraph_format.space_after = Pt(4)
            add_runs(p, s[2:], size=9.5, color=(0x59, 0x59, 0x59))
            i += 1
            continue

        # 列表
        if s.startswith("- ") or re.match(r"^\d+\.\s", s):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Pt(18)
            p.paragraph_format.space_after = Pt(2)
            txt = s[2:] if s.startswith("- ") else re.sub(r"^\d+\.\s", "", s)
            add_runs(p, txt, size=10.5)
            i += 1
            continue

        # 正文
        if s:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            add_runs(p, s, size=10.5)
        i += 1

    doc.save(dst)
    print("written:", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
