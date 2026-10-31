from pathlib import Path

p = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\build_report.py")
t = p.read_text(encoding="utf-8")

t = t.replace("widths=[2.8, 2.2, 2.4, 2.0, 2.0, 2.4, 2.0],",
              "widths=[2.8, 2.0, 2.8, 2.0, 2.0, 2.4, 2.0],")

old_code = '''    r.code([
        "cd planning_middle_demo",
        "py -3.14 sdf_state.py                  # 重新提取 SDF 初始状态",
        "py -3.14 run_demo_v2.py --scenario scenarios/asl_city.json \\\\",
        "        --motion real --avoid --behavior --max-ticks 640 \\\\",
        "        --out outputs/asl_city_mixed",
        "py -3.14 -m unittest discover -s tests -q   # 120 项",
    ])'''
new_code = '''    r.code([
        "cd planning_middle_demo",
        "py -3.14 sdf_state.py",
        "py -3.14 run_demo_v2.py --scenario scenarios/asl_city.json \\\\",
        "        --motion real --avoid --behavior --max-ticks 640 \\\\",
        "        --out outputs/asl_city_mixed",
        "py -3.14 -m unittest discover -s tests -q",
    ])
    r.para("第一条命令重新提取 SDF 初始状态；最后一条运行 120 项测试。"
           "运行输出写入独立目录，已有记录不被覆盖。")'''
if old_code not in t:
    print("code block pattern not found")
t = t.replace(old_code, new_code)
p.write_text(t, encoding="utf-8")
print("patched table18 width and code block")
