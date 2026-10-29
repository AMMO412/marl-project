from pathlib import Path
import json
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
OUT=ROOT/"outputs"/"planning_middle_demo审查_20261026"
data=json.loads((ROOT/".work/platform_review_20261026/corrected_scope_20261027.json").read_text(encoding="utf-8"))
doc=Document();sec=doc.sections[0]
sec.page_width=Inches(8.5);sec.page_height=Inches(11)
sec.top_margin=sec.bottom_margin=Inches(.62)
sec.left_margin=sec.right_margin=Inches(.67)
sec.header_distance=Inches(.23);sec.footer_distance=Inches(.25)
def font(run,size=9.25,bold=False,white=False):
    run.font.name="Microsoft YaHei";run.font.size=Pt(size);run.bold=bold
    run.font.color.rgb=RGBColor(255,255,255) if white else RGBColor(0,0,0)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),"Microsoft YaHei")
for name in ["Normal","Title","Subtitle","Heading 1","Heading 2","Heading 3"]:
    st=doc.styles[name];st.font.name="Microsoft YaHei";st.font.color.rgb=RGBColor(0,0,0)
    st._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),"Microsoft YaHei")
doc.styles["Normal"].font.size=Pt(10.5)
doc.styles["Normal"].paragraph_format.space_after=Pt(6)
doc.styles["Normal"].paragraph_format.line_spacing=1.12
doc.styles["Title"].font.size=Pt(22);doc.styles["Title"].paragraph_format.space_after=Pt(8)
for name in ["Title","Subtitle","Heading 1","Heading 2","Heading 3"]:
    for border in list(doc.styles[name].element.findall(".//"+qn("w:pBdr"))):
        border.getparent().remove(border)
doc.styles["Subtitle"].font.size=Pt(9)
doc.styles["Heading 1"].font.size=Pt(15)
doc.styles["Heading 1"].paragraph_format.space_before=Pt(0);doc.styles["Heading 1"].paragraph_format.space_after=Pt(8)
doc.core_properties.title=data["title"];doc.core_properties.author="项目审查记录"
doc.core_properties.subject="基于固定源码快照的逐项实现证据与通用软件可靠性审查"
upd=OxmlElement("w:updateFields");upd.set(qn("w:val"),"true");doc.settings.element.append(upd)
h=sec.header.paragraphs[0];font(h.add_run("planning_middle_demo   责任归属纠正"),8)
f=sec.footer.paragraphs[0];f.alignment=WD_ALIGN_PARAGRAPH.RIGHT
font(f.add_run("2026-10-27   |   第 "),8)
fld=OxmlElement("w:fldSimple");fld.set(qn("w:instr"),"PAGE");f._p.append(fld)
font(f.add_run(" 页"),8)
def table(headers,rows):
    widths=[1.02,.75,3.19,2.2] if len(headers)==4 else [1.72,1.5,3.94]
    if headers[0]=="功能项":widths=[1.55,2.1,3.51]
    if headers[0]=="事项":widths=[1.45,2.45,3.26]
    if headers[0]=="模块":widths=[.82,1.4,2.5,2.44]
    if headers[0]=="接口":widths=[1.5,2.1,3.56]
    if headers[0]=="条款":widths=[1.12,1.65,2.65,1.74]
    if headers[0]=="验证对象":widths=[1.35,1.55,1.9,2.36]
    if headers[0]=="依据或产物":widths=[1.48,2.9,2.78]
    if headers[0]=="问题":widths=[1.55,2.9,2.71]
    if headers[0]=="证据标识":widths=[1.33,3.2,2.63]
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    for c,w in zip(t.columns,widths):c.width=Inches(w)
    borders=OxmlElement("w:tblBorders")
    for edge in ["top","left","bottom","right","insideH","insideV"]:
        e=OxmlElement("w:"+edge)
        for k,v in [("val","single"),("sz","4"),("color","D9D9D9")]:e.set(qn("w:"+k),v)
        borders.append(e)
    t._tbl.tblPr.append(borders)
    for idx,values in enumerate([headers]+rows):
        cells=t.rows[0].cells if idx==0 else t.add_row().cells
        rp=t.rows[idx]._tr.get_or_add_trPr()
        no=OxmlElement("w:cantSplit");rp.append(no)
        if idx==0:rp.append(OxmlElement("w:tblHeader"))
        for j,(cell,value) in enumerate(zip(cells,values)):
            cell.width=Inches(widths[j]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp=cell._tc.get_or_add_tcPr();mar=OxmlElement("w:tcMar")
            for edge,num in [("top",68),("bottom",68),("left",80),("right",80)]:
                x=OxmlElement("w:"+edge);x.set(qn("w:w"),str(num));x.set(qn("w:type"),"dxa");mar.append(x)
            cp.append(mar);sh=OxmlElement("w:shd")
            sh.set(qn("w:fill"),"263E55" if idx==0 else ("F1F4F7" if idx%2==0 else "FFFFFF"));cp.append(sh)
            p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.05
            if j==1 and headers[j] in ("状态","本目录状态"):p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            font(p.add_run(str(value)),9.25,idx==0,idx==0)
    p=doc.add_paragraph();p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1
for i,page in enumerate(data["pages"]):
    if i:doc.add_page_break()
    if i==0:
        doc.add_paragraph(data["title"],"Title")
        doc.add_paragraph("修订日期 2026-10-27    责任版    交付 对接 消费 验证","Subtitle")
    doc.add_heading(str(i+1)+" "+page["title"],1);doc.add_paragraph(page["intro"])
    table(page["headers"],page["rows"])
    for note in page["notes"]:
        p=doc.add_paragraph(note);p.paragraph_format.space_after=Pt(6)
        for r in p.runs:font(r,9.4)
dest=OUT/"planning_middle_demo责任分工与对接核查.docx"
doc.save(dest);print(str(dest))

