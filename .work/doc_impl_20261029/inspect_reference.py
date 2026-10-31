"""Inspect the reference DOCX: page setup, styles, paragraphs, tables, images."""
import json
import sys
from pathlib import Path

from docx import Document
from docx.shared import Emu

PATH = Path(r"D:\Desktop\MARL项目\资料\需求与任务\无人集群编队五类任务定义_1028.docx")


def q(name):
    return locals().get(name)


doc = Document(str(PATH))
print("FILE", PATH, PATH.stat().st_size)
for i, sec in enumerate(doc.sections):
    print("SECTION", i,
          "size", round(sec.page_width.cm, 2), round(sec.page_height.cm, 2),
          "margins", round(sec.left_margin.cm, 2), round(sec.right_margin.cm, 2),
          round(sec.top_margin.cm, 2), round(sec.bottom_margin.cm, 2))

print("\nSTYLES (used):")
used = {}
for p in doc.paragraphs:
    used[p.style.name] = used.get(p.style.name, 0) + 1
for name, count in sorted(used.items(), key=lambda kv: -kv[1]):
    print(" ", repr(name), count)

print("\nDEFAULT FONT:", doc.styles['Normal'].font.name,
      doc.styles['Normal'].font.size.pt if doc.styles['Normal'].font.size else None,
      doc.styles['Normal'].element.rPr.rFonts.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia')
      if doc.styles['Normal'].element.rPr is not None and doc.styles['Normal'].element.rPr.rFonts is not None else None)

print("\nPARAGRAPHS:")
for i, p in enumerate(doc.paragraphs):
    text = p.text.strip()
    if not text:
        continue
    runs = []
    for r in p.runs[:3]:
        color = r.font.color.rgb if r.font.color and r.font.color.rgb else None
        runs.append(dict(t=r.text[:18], font=r.font.name, size=r.font.size.pt if r.font.size else None,
                         bold=r.font.bold, color=str(color) if color else None))
    pf = p.paragraph_format
    print(i, "|", p.style.name, "|", "align", p.alignment,
          "| first", pf.first_line_indent.cm if pf.first_line_indent else None,
          "| before/after", pf.space_before.pt if pf.space_before else None,
          pf.space_after.pt if pf.space_after else None,
          "| line", pf.line_spacing,
          "|", repr(text[:60]), "|", runs[:2])

print("\nTABLES:", len(doc.tables))
for ti, tbl in enumerate(doc.tables[:6]):
    print("TABLE", ti, "rows", len(tbl.rows), "cols", len(tbl.columns), "style", tbl.style.name if tbl.style else None)
    for r in tbl.rows[:3]:
        print("   ", [c.text.strip()[:22] for c in r.cells])

print("\nINLINE SHAPES:", len(doc.inline_shapes))
for sh in doc.inline_shapes[:10]:
    print("  ", sh.type, round(Emu(sh.width).cm, 2), round(Emu(sh.height).cm, 2))

print("\nSECTIONS HEADER/FOOTER:")
for i, sec in enumerate(doc.sections):
    print(i, "header:", [p.text for p in sec.header.paragraphs],
          "footer:", [p.text for p in sec.footer.paragraphs])
