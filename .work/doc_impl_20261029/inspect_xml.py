"""Inspect XML details: table formatting, TOC page, alignment, default fonts."""
import json
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

PATH = Path(r"D:\Desktop\MARL项目\资料\需求与任务\无人集群编队五类任务定义_1028.docx")
OUT = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\xml_details.json")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

doc = Document(str(PATH))
body = doc.element.body

# 1) first table xml (trim attrs)
tables = body.findall(W + "tbl")
first = tables[0]
xml = etree.tostring(first, pretty_print=True, encoding="unicode")
tblpr = first.find(W + "tblPr")
print("TABLE PR:\n", etree.tostring(tblpr, pretty_print=True, encoding="unicode")[:3000])
row = first.findall(W + "tr")[0]
print("HEADER ROW:\n", etree.tostring(row, pretty_print=True, encoding="unicode")[:4000])

# 2) neighbors of the TOC: find paragraph whose text is 目录
toc_par = None
for p in doc.paragraphs:
    if p.text.strip() == "目录":
        toc_par = p
        break
if toc_par is not None:
    el = toc_par._element
    parent = el.getparent()
    print("TOC parent:", parent.tag)
    print("TOC prev siblings:", [c.tag.split('}')[-1] for c in el.getprevious()] if el.getprevious() is not None else None)
    print("TOC paragraph xml:", etree.tostring(el, pretty_print=True, encoding="unicode")[:2500])
    # following sibling shape?
    nxt = el.getnext()
    print("TOC next:", nxt.tag if nxt is not None else None)
    if nxt is not None:
        print(etree.tostring(nxt, pretty_print=True, encoding="unicode")[:3000])

# 3) Normal paragraph alignment snapshot
for p in doc.paragraphs[:8]:
    print("P", repr(p.text[:20]), "alignment", p.alignment)

# 4) doc defaults + theme
import zipfile
with zipfile.ZipFile(PATH) as z:
    names = [n for n in z.namelist() if n in ("word/document.xml", "word/theme/theme1.xml", "word/settings.xml")]
    print("zip entries", names)
    docxml = z.read("word/document.xml").decode("utf-8")
    i = docxml.find("<w:docDefaults>")
    print("DOCDEFAULTS:", docxml[i:i + 1500])
    theme = z.read("word/theme/theme1.xml").decode("utf-8")
    j = theme.find("<a:minorFont>")
    print("THEME MINOR:", theme[j:j + 400])
