from pathlib import Path

p = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\build_report.py")
t = p.read_text(encoding="utf-8")
old = '''    r.para("建筑在 SDF 中以模型引用给出，本身没有尺寸。实现从本地模型文件读取显式盒体或 "
           "DAE 包围盒（含缩放），换算为平面占地；规划与显示使用同一套几何，"
           "避免“图上画的和规划躲的不是同一块”。本场景共 13 处障碍：7 处花坛/标识柱与 6 栋建筑（表 5）。")'''
new = '''    r.para("建筑在 SDF 中以模型引用给出，本身没有尺寸。实现从本地模型文件读取显式盒体或 "
           "DAE 包围盒（含缩放），换算为平面占地；规划与显示使用同一套几何，"
           "避免“图上画的和规划躲的不是同一块”。全场景共 39 处静态障碍，"
           "进入本演示规划范围（x ∈ [-185, 20]、y ∈ [-210, 30]）的为 13 处："
           "7 处花坛/标识柱与 6 栋建筑（表 5）。")'''
if old not in t:
    print("paragraph not found")
else:
    t = t.replace(old, new)
    p.write_text(t, encoding="utf-8")
    print("patched obstacle scope")
