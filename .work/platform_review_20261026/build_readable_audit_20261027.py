from pathlib import Path
from docx import Document
from docx.shared import Inches,Pt,RGBColor,Cm
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.section import WD_ORIENT
import json,re,hashlib,uuid
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目");W=ROOT/".work/platform_review_20261026";O=ROOT/"outputs/planning_middle_demo指标核查_20261027"
# Retain the previous report before replacing its public path.
backup=ROOT/".work/backups"/("2026-10-27_readable_report_"+uuid.uuid4().hex[:8]);backup.mkdir(parents=True)
backed=[]
for p in [O/"planning_middle_demo指标逐项核查报告.docx",O/"report_content.json",O/"delivery_receipt.json"]:
 if p.exists():
  b=p.read_bytes();(backup/p.name).write_bytes(b);backed.append({"path":str(p),"sha256":hashlib.sha256(b).hexdigest()})
(W/"readable_report_backup.json").write_bytes(json.dumps({"backup":str(backup),"files":backed},ensure_ascii=False,indent=2).encode("utf-8"))
sources=json.loads((O/"sources_text.json").read_text(encoding="utf-8"))
c={x["id"]:x.get("text","") for x in sources["C"]["items"]}
old=[
("2.1（1）",7,"未完成","仅读取本地JSON，未订阅上层编组信息；无接收时延实测。需正式消息和接收端联调。"),
("2.1（2）",8,"部分完成","已有成员失联触发处理；无完整编组关系、分组及约束变更接入。"),
("2.1（3）",9,"部分完成","已有自定JSON、3个rules参数及4类预置timeline事件；未兼容正式想定和在线导调。"),
("2.1（4）",10,"部分完成","本地偏差、失败和超时取消后重试可运行；真实执行端反馈、取消生效及终态未验证。"),
("2.2（1）",12,"部分完成","已按平台生成独立命令和时序，替身可接收反馈；尚无真实逐台通信和执行确认。"),
("2.2（2）",13,"部分完成","已有分配及输出字段；默认场景为10台、6作业，无≥15台端到端通信和800ms达标证据。"),
("2.2（3）",14,"部分完成","已有时序冲突检查；未按确认的回合、分母和统计口径证明≥95%。"),
("2.3（1）",16,"部分完成","静态编成登记4类平台，可注入失联；新增、恢复及1至5台动态增减未完整验证。"),
("2.3（3）",17,"部分完成","有5类任务模板，但执行采用统一工作量过程；未证明完整任务语义及差异化要求。"),
("2.3（4）",18,"部分完成","有时效、能耗、分散度3种选择；分散度不等同原文暴露风险，尚未完全符合。"),
("2.3（5）",19,"部分完成","默认检查续航、载荷及高度；传感器、运动性能未默认启用，完整能力符合性未证明。"),
("2.4（1）",21,"待联调","Bridge及UE5通信由外协提供，我方尚未接入真实ROS时钟；无双引擎≤50ms实测。"),
("2.4（2）",22,"待联调","已有本地HTML报告和轨迹回放；未向外协UE5端实际推送或验证显示。"),
("2.4（3）",23,"部分完成","已有场景、计划、反馈、日志与自动报告；缺真实编组源、执行事实和完整指标口径。")
]
rows=[]
for num,para,state,summary in old:
 text=c["C-P%03d"%para]
 text=re.sub(r"^（\d+）","",text)
 rows.append([num,text,state,summary])
extra=json.loads((W/"readable_extra_pages_20261027.json").read_text(encoding="utf-8"))
pages=[
 {"title":"一 原询价技术指标对应情况","intro":"核查对象为planning_middle_demo，完成情况依据2026年10月27日代码和测试记录。下表保留原询价文件的条款编号及指标原文。","headers":["原文条款","原文技术指标","完成程度","当前实现及主要缺项"],"rows":rows[:7],"notes":["部分完成：已有局部功能，尚未满足整项标准。待联调：尚无真实跨模块验证。"]},
 {"title":"原询价技术指标对应情况 续表","intro":"以下对应原询价文件第2.3节和第2.4节，编号沿用原文。","headers":["原文条款","原文技术指标","完成程度","当前实现及主要缺项"],"rows":rows[7:],"notes":[]}
]+extra
data={"title":"现有系统技术指标完成情况对照表","date":"2026-10-27","pages":pages}
doc=Document();sec=doc.sections[0];sec.orientation=WD_ORIENT.LANDSCAPE;sec.page_width=Cm(29.7);sec.page_height=Cm(21)
sec.top_margin=sec.bottom_margin=Cm(1.25);sec.left_margin=sec.right_margin=Cm(1.5);sec.header_distance=sec.footer_distance=Cm(.5)
def font(r,size=10.5,bold=False,white=False):
 r.font.name="宋体";r.font.size=Pt(size);r.bold=bold;r.italic=False;r.font.color.rgb=RGBColor(255,255,255) if white else RGBColor(0,0,0)
 r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),"宋体")
for name in ["Normal","Title","Heading 1","Subtitle"]:
 st=doc.styles[name];st.font.name="宋体";st.font.color.rgb=RGBColor(0,0,0);st.font.italic=False;st._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),"宋体")
 st.paragraph_format.space_after=Pt(5);st.paragraph_format.line_spacing=1.02
 for x in list(st.element.findall(".//"+qn("w:pBdr"))):x.getparent().remove(x)
doc.styles["Normal"].font.size=Pt(10.5);doc.styles["Title"].font.size=Pt(19)
doc.styles["Heading 1"].font.size=Pt(14);doc.styles["Heading 1"].font.bold=True;doc.styles["Heading 1"].paragraph_format.space_before=Pt(0)
font(sec.header.paragraphs[0].add_run(data["title"]),8)
f=sec.footer.paragraphs[0];f.alignment=WD_ALIGN_PARAGRAPH.RIGHT;font(f.add_run("2026年10月27日    第 "),8)
fld=OxmlElement("w:fldSimple");fld.set(qn("w:instr"),"PAGE");f._p.append(fld);font(f.add_run(" 页"),8)
doc.core_properties.title=data["title"];doc.core_properties.author="";doc.core_properties.subject="原询价技术指标及新文件模块完成情况"
def table(page,idx):
 headers=page["headers"]
 widths=([.75,5.1,.85,3.8] if idx<2 else [4.1,.7,.85,4.85] if idx==2 else [2.65,1.6,.85,5.4] if idx==3 else [1.15,4.7,1.0,3.65] if idx==4 else [5.25,.9,4.35])
 t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
 for col,w in zip(t.columns,widths):col.width=Inches(w)
 bd=OxmlElement("w:tblBorders")
 for edge in ["top","left","bottom","right","insideH","insideV"]:
  x=OxmlElement("w:"+edge)
  for k,v in [("val","single"),("sz","4"),("color","D9D9D9")]:x.set(qn("w:"+k),v)
  bd.append(x)
 t._tbl.tblPr.append(bd)
 for i,values in enumerate([headers]+page["rows"]):
  cells=t.rows[0].cells if i==0 else t.add_row().cells
  rp=t.rows[i]._tr.get_or_add_trPr();rp.append(OxmlElement("w:cantSplit"))
  if i==0:rp.append(OxmlElement("w:tblHeader"))
  for j,(cell,value) in enumerate(zip(cells,values)):
   cell.width=Inches(widths[j]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   tc=cell._tc.get_or_add_tcPr();mar=OxmlElement("w:tcMar")
   for edge,n in [("top",65),("bottom",65),("left",75),("right",75)]:
    x=OxmlElement("w:"+edge);x.set(qn("w:w"),str(n));x.set(qn("w:type"),"dxa");mar.append(x)
   tc.append(mar);sh=OxmlElement("w:shd");sh.set(qn("w:fill"),"444444" if i==0 else ("F5F5F5" if i%2==0 else "FFFFFF"));tc.append(sh)
   p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.0
   if (idx<2 and j in (0,2)) or (idx in (2,3,4) and j==2) or (idx==2 and j==1) or (idx==5 and j==1):p.alignment=WD_ALIGN_PARAGRAPH.CENTER
   font(p.add_run(str(value)),10.2,i==0,i==0)
 p=doc.add_paragraph();p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(3)
for i,page in enumerate(pages):
 if i:doc.add_page_break()
 if i==0:
  p=doc.add_paragraph(data["title"],"Title");p.alignment=WD_ALIGN_PARAGRAPH.CENTER
 doc.add_heading(page["title"],1);doc.add_paragraph(page["intro"]);table(page,i)
 for note in page["notes"]:
  p=doc.add_paragraph(note)
  for r in p.runs:font(r,9.5)
dest=O/"planning_middle_demo指标逐项核查报告.docx";doc.save(dest)
(O/"report_content.json").write_bytes(json.dumps(data,ensure_ascii=False,indent=2).encode("utf-8"))
assert len(rows)==14
alltext="\n".join(p.text for p in doc.paragraphs)+"\n"+"\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
assert not re.search(r"\b(?:EX|IF|AC|DL|M3|M4)-\d+|T\d{2}R\d{2}|C-P\d+|\bE[1-9]\b",alltext)
print(json.dumps({"docx":str(dest),"planned_pages":6,"old_metrics":14,"new_modules":8,"new_interfaces":13,"external_modules":5,"backup":str(backup)},ensure_ascii=False))

