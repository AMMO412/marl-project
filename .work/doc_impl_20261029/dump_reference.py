"""Dump reference DOCX details to UTF-8 JSON for precise style matching."""
import json
from pathlib import Path

from docx import Document
from docx.shared import Emu
from docx.oxml.ns import qn

PATH = Path(r"D:\Desktop\MARL项目\资料\需求与任务\无人集群编队五类任务定义_1028.docx")
OUT = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\reference_dump.json")

doc = Document(str(PATH))
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def rpr(run):
    f = run.font
    r = run._element.rPr
    east = None
    if r is not None and r.rFonts is not None:
        east = r.rFonts.get(W + "eastAsia")
    return dict(name=f.name, eastAsia=east,
                size=f.size.pt if f.size else None,
                bold=f.bold, italic=f.italic,
                color=str(f.color.rgb) if f.color and f.color.rgb else None)


def para(p):
    pf = p.paragraph_format
    return dict(style=p.style.name, text=p.text,
                align=str(p.alignment) if p.alignment is not None else None,
                first_indent_cm=round(pf.first_line_indent.cm, 3) if pf.first_line_indent else None,
                left_indent_cm=round(pf.left_indent.cm, 3) if pf.left_indent else None,
                space_before=pf.space_before.pt if pf.space_before else None,
                space_after=pf.space_after.pt if pf.space_after else None,
                line=pf.line_spacing,
                keep_with_next=pf.keep_with_next,
                page_break_before=pf.page_break_before,
                runs=[rpr(r) for r in p.runs[:4]])


styles = {}
for st in doc.styles:
    try:
        f = st.font
        r = st.element.rPr
        east = r.rFonts.get(W + "eastAsia") if r is not None and r.rFonts is not None else None
        ascii_font = r.rFonts.get(W + "ascii") if r is not None and r.rFonts is not None else None
        pf = st.paragraph_format
        styles[st.name] = dict(type=str(st.type), base=st.base_style.name if st.base_style else None,
                               font=f.name, ascii=ascii_font, eastAsia=east,
                               size=f.size.pt if f.size else None, bold=f.bold,
                               color=str(f.color.rgb) if f.color and f.color.rgb else None,
                               first_indent_cm=round(pf.first_line_indent.cm, 3) if pf.first_line_indent else None,
                               space_before=pf.space_before.pt if pf.space_before else None,
                               space_after=pf.space_after.pt if pf.space_after else None,
                               line=pf.line_spacing, line_rule=str(pf.line_spacing_rule))
    except Exception as exc:  # noqa
        styles[st.name] = dict(error=str(exc))

tables = []
for t in doc.tables:
    rows = []
    for row in t.rows[:4]:
        rows.append([c.text.strip()[:30] for c in row.cells])
    tblPr = t._tbl.tblPr
    tables.append(dict(style=t.style.name if t.style else None,
                       rows=len(t.rows), cols=len(t.columns),
                       rows_sample=rows,
                       width=None,
                       jc=str(tblPr.find(qn('w:jc')).get(qn('w:val'))) if tblPr.find(qn('w:jc')) is not None else None))

body = []
for child in doc.element.body.iterchildren():
    if child.tag == W + "p":
        from docx.text.paragraph import Paragraph
        body.append(dict(kind="p", **para(Paragraph(child, doc))))
    elif child.tag == W + "tbl":
        body.append(dict(kind="tbl"))

dump = dict(
    sections=[dict(w_cm=round(s.page_width.cm, 2), h_cm=round(s.page_height.cm, 2),
                   margins=[round(s.left_margin.cm, 2), round(s.right_margin.cm, 2),
                            round(s.top_margin.cm, 2), round(s.bottom_margin.cm, 2)],
                   header=[p.text for p in s.header.paragraphs],
                   footer=[p.text for p in s.footer.paragraphs],
                   start_type=str(s.start_type))
              for s in doc.sections],
    styles=styles,
    tables=tables,
    images=[dict(w_cm=round(Emu(sh.width).cm, 2), h_cm=round(Emu(sh.height).cm, 2))
            for sh in doc.inline_shapes],
    body=body[:80],
)
OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", OUT, len(doc.paragraphs), "paras", len(doc.tables), "tables")

