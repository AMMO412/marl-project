from pathlib import Path
import zipfile

p = Path(r"D:\Desktop\MARL项目\资料\需求与任务\无人集群编队五类任务定义_1028.docx")
with zipfile.ZipFile(p) as z:
    for name in z.namelist():
        if name.startswith("word/footer") or name.startswith("word/header"):
            data = z.read(name).decode("utf-8", "ignore")
            print("=" * 20, name, len(data))
            print(data[:1200])
    # sectPr footer refs
    doc = z.read("word/document.xml").decode("utf-8", "ignore")
    i = doc.find("<w:sectPr")
    while i >= 0 and i < len(doc):
        print("SECTPR:", doc[i:i + 900])
        print("----")
        i = doc.find("<w:sectPr", i + 1)
