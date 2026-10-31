from pathlib import Path

p = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\build_report.py")
t = p.read_text(encoding="utf-8")
old = '''    r.para("第一条命令重新提取 SDF 初始状态；最后一条运行 120 项测试。"
           "运行输出写入独立目录，已有记录不被覆盖。")
'''
if old in t:
    t = t.replace(old, "")
    print("removed duplicate sentence")
else:
    print("sentence not found")
p.write_text(t, encoding="utf-8")
