from pathlib import Path

p = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\build_report.py")
lines = p.read_text(encoding="utf-8").split("\n")
out = []
for ln in lines:
    s = ln.strip()
    if s.startswith('r.figure("fig5_process.png"'):
        continue
    if s.startswith('r.figure("fig1_architecture.png"'):
        ln = '    r.figure("fig1_architecture.png", 14.6, "图 1 系统组成与运行闭环")'
    if s.startswith('r.figure("fig3_global.png"'):
        ln = '    r.figure("fig3_global.png", 14.4, "图 2 全局态势：十字路口建筑群、道路与目标点")'
    if s.startswith('r.figure("fig4_approach.png"'):
        ln = '    r.figure("fig4_approach.png", 14.4, "图 3 地面绕障接近与空中直飞（红虚线为被挡直线）")'
    if s.startswith('r.figure("fig2_timeline.png"'):
        ln = '    r.figure("fig2_timeline.png", 16.0, "图 4 毁伤运行的阶段时序")'
    out.append(ln)
p.write_text("\n".join(out), encoding="utf-8")
print("fixed")
for ln in out:
    if "r.figure(" in ln:
        print(ln.strip())
