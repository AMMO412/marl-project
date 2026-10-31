from pathlib import Path

p = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\build_report.py")
t = p.read_text(encoding="utf-8")

# 封面：增加顶部留白，底部说明下移
t = t.replace("""    def cover(self):
        for _ in range(5):""", """    def cover(self):
        for _ in range(8):""")
t = t.replace("""        # 底部说明
        for _ in range(9):""", """        # 底部说明
        for _ in range(18):""")
p.write_text(t, encoding="utf-8")
print("cover spacing patched")
