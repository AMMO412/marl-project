"""Inspect TableText style, body cell run sizes, caption formatting, and numbering."""
import json
import zipfile
from pathlib import Path
from lxml import etree
from docx import Document
from docx.oxml.ns import qn

PATH = Path(r"D:\Desktop\MARL项目\资料\需求与任务\无人集群编队五类任务定义_1028.docx")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

doc = Document(str(PATH))
t = doc.tables[0]
# body cell run props
for r in (0, 1, 2):
    cell = t.rows[r].cells[0]
    for p in cell.paragraphs[:1]:
        for run in p.runs[:1]:
            rPr = run._element.rPr
            print("row", r, "style", p.style.name, "text", run.text[:8],
                  "xml", etree.tostring(rPr, encoding="unicode")[:400] if rPr is not None else None)

# caption paragraph xml
for p in doc.paragraphs:
    if p.style.name == "Caption":
        print("CAPTION STYLE XML:", etree.tostring(p._element, encoding="unicode")[:1200])
        break

# find Figure paragraph (contains drawing) and its pPr
for p in doc.paragraphs:
    if p._element.findall('.//' + W + 'drawing'):
        print("FIGURE P XML:", etree.tostring(p._element, encoding="unicode")[:900])
        break

# styles.xml TableText + Code Block
with zipfile.ZipFile(PATH) as z:
    styles = z.read("word/styles.xml").decode("utf-8")
    for sid in ("TableText", "CodeBlock", "Caption", "Normal"):
        i = styles.find('w:styleId="%s"' % sid)
        if i >= 0:
            start = styles.rfind("<w:style ", 0, i)
            end = styles.find("</w:style>", i) + 10
            print("STYLE", sid, ":", styles[start:end][:1200])
    # docDefaults search
    for token in ("docDefaults", "rPrDefault", "w:themeFontLang"):
        print(token, "at", styles.find(token) if token != "docDefaults" else styles.find(token))
    i = styles.find("<w:docDefaults>")
    print("DOCDEFAULTS:", styles[i:i + 900] if i >= 0 else "n/a")
    settings = z.read("word/settings.xml").decode("utf-8")
    for token in ("updateFields", "defaultTabStop", "characterSpacingControl"):
        print("SETTINGS", token, settings.find(token))
