from pathlib import Path
from docx import Document
from docx.shared import Inches,Pt,RGBColor,Cm
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.table import Table
from docx.text.paragraph import Paragraph
import json,re,hashlib
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目");W=ROOT/".work/platform_review_20261026";O=ROOT/"outputs/planning_middle_demo指标核查_20261027"
data=json.loads((W/"standard_audit_content_20261027.json").read_text(encoding="utf-8"))
for p in data["pages"]:
 for r in p["rows"]:
  if r[0].startswith("M3-18"):r[0]=r[0].replace("A2.3","A1.3")
  if r[0].startswith("M4-17"):r[0]=r[0].replace("A2.4","A3.1")
  if r[0].startswith("M4-18"):r[0]=r[0].replace("A2.4","A1.3")
# Freeze paragraph/table locators from the actual source files.
extract={}
names=[("A","智能体开发训练平台技术实施方案.docx"),("B","外协内容.docx"),("C","对手编队决策模型建模询价要求与报价单20261008.docx")]
for code,name in names:
 d=Document(O/"sources"/name);ps=ts=0;items=[]
 for x in d.element.body:
  if x.tag.endswith("}p"):
   ps+=1;s=Paragraph(x,d).text
   if s.strip():items.append({"id":code+"-P%03d"%ps,"text":s})
  elif x.tag.endswith("}tbl"):
   ts+=1
   for i,row in enumerate(Table(x,d).rows,1):items.append({"id":code+"-T%02dR%02d"%(ts,i),"cells":[c.text for c in row.cells]})
 extract[code]={"filename":name,"items":items}
(O/"sources_text.json").write_bytes(json.dumps(extract,ensure_ascii=False,indent=2).encode("utf-8"))
doc=Document();sec=doc.sections[0];sec.orientation=WD_ORIENT.LANDSCAPE
sec.page_width=Cm(29.7);sec.page_height=Cm(21);sec.top_margin=sec.bottom_margin=Cm(1.25);sec.left_margin=sec.right_margin=Cm(1.5)
sec.header_distance=Cm(.5);sec.footer_distance=Cm(.5)
BLACK=RGBColor(0,0,0)
def font(r,size=9.5,bold=False,white=False,face="宋体"):
 r.font.name=face;r.font.size=Pt(size);r.bold=bold;r.italic=False;r.font.color.rgb=RGBColor(255,255,255) if white else BLACK
 r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),face)
for name in ["Normal","Title","Subtitle","Heading 1","Heading 2"]:
 st=doc.styles[name];st.font.name="宋体";st.font.color.rgb=BLACK;st.font.italic=False
 st._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),"宋体")
 st.paragraph_format.space_after=Pt(5);st.paragraph_format.line_spacing=1.06
 for border in list(st.element.findall(".//"+qn("w:pBdr"))):border.getparent().remove(border)
doc.styles["Normal"].font.size=Pt(10.5);doc.styles["Title"].font.size=Pt(20)
doc.styles["Title"].paragraph_format.space_after=Pt(8)
doc.styles["Heading 1"].font.size=Pt(14);doc.styles["Heading 1"].font.bold=True;doc.styles["Heading 1"].paragraph_format.space_before=Pt(0)
h=sec.header.paragraphs[0];font(h.add_run("任务规划中间层指标完成情况核查报告"),8.5)
f=sec.footer.paragraphs[0];f.alignment=WD_ALIGN_PARAGRAPH.RIGHT;font(f.add_run("2026年10月27日    第 "),8)
fld=OxmlElement("w:fldSimple");fld.set(qn("w:instr"),"PAGE");f._p.append(fld);font(f.add_run(" 页"),8)
doc.core_properties.title=data["title"];doc.core_properties.author="";doc.core_properties.subject="需求指标逐项核查、实现证据及模块责任"
def tab(headers,rows):
 if len(headers)==6:widths=[1.15,2.5,.95,1.0,2.65,2.25]
 elif len(headers)==4:widths=[2.1,1.5,3.75,3.15] if headers[0].startswith("模块") else [1.8,2.0,4.0,2.7]
 else:widths=[1.8,2.2,6.5] if headers[0]=="来源或证据" else [1.8,1.8,6.9]
 t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
 for c,w in zip(t.columns,widths):c.width=Inches(w)
 borders=OxmlElement("w:tblBorders")
 for edge in ["top","left","bottom","right","insideH","insideV"]:
  x=OxmlElement("w:"+edge)
  for k,v in [("val","single"),("sz","4"),("color","D9D9D9")]:x.set(qn("w:"+k),v)
  borders.append(x)
 t._tbl.tblPr.append(borders)
 for i,vals in enumerate([headers]+rows):
  cells=t.rows[0].cells if i==0 else t.add_row().cells
  trp=t.rows[i]._tr.get_or_add_trPr();trp.append(OxmlElement("w:cantSplit"))
  if i==0:trp.append(OxmlElement("w:tblHeader"))
  for j,(cell,val) in enumerate(zip(cells,vals)):
   cell.width=Inches(widths[j]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   tc=cell._tc.get_or_add_tcPr();m=OxmlElement("w:tcMar")
   for edge,v in [("top",65),("bottom",65),("left",72),("right",72)]:
    x=OxmlElement("w:"+edge);x.set(qn("w:w"),str(v));x.set(qn("w:type"),"dxa");m.append(x)
   tc.append(m);sh=OxmlElement("w:shd");sh.set(qn("w:fill"),"444444" if i==0 else ("F5F5F5" if i%2==0 else "FFFFFF"));tc.append(sh)
   p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.02
   if len(headers)==6 and j in (2,3):p.alignment=WD_ALIGN_PARAGRAPH.CENTER
   font(p.add_run(str(val)),9.3,i==0,i==0)
 p=doc.add_paragraph();p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(2);p.paragraph_format.space_before=Pt(0)
for i,page in enumerate(data["pages"]):
 if i:doc.add_page_break()
 if not i:
  p=doc.add_paragraph(data["title"],"Title");p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  p=doc.add_paragraph("核查对象  planning_middle_demo        核查日期  2026年10月27日");p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  for r in p.runs:font(r,9.5)
 doc.add_heading(str(i+1)+"  "+page["title"],1);doc.add_paragraph(page["intro"])
 tab(page["headers"],page["rows"])
 for note in page["notes"]:
  p=doc.add_paragraph(note)
  for r in p.runs:font(r,9)
dest=O/"planning_middle_demo指标逐项核查报告.docx";doc.save(dest)
(O/"report_content.json").write_bytes(json.dumps(data,ensure_ascii=False,indent=2).encode("utf-8"))
assert len([r for p in data["pages"] for r in p["rows"] if r[0].startswith("M3-")])==18
assert len([r for p in data["pages"] for r in p["rows"] if r[0].startswith("M4-")])==18
assert len([r for p in data["pages"] for r in p["rows"] if r[0].startswith("IF-")])==13
assert len([r for p in data["pages"] for r in p["rows"] if r[0].startswith("C 2.")])==14
print(json.dumps({"docx":str(dest),"planned_pages":len(data["pages"]),"rows":sum(len(p["rows"]) for p in data["pages"]),"sha256":hashlib.sha256(dest.read_bytes()).hexdigest()},ensure_ascii=False))

