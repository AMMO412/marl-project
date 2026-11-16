using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private bool showAllArtifacts;
        private static bool PrimaryArtifact(string name)
        {
            return ArtifactPriority(name)<3 || name=="report.json" || name=="summary.txt" || name=="execution_plan.json" || name=="chain_viewer.html" || name=="ros2_plan_node.py";
        }
        private static int ArtifactPriority(string name)
        {
            switch(name) {case "agent_tasks.md":return 0;case "agent_tasks.csv":return 1;case "agent_tasks.json":return 2;default:return 3;}
        }
        private static string ArtifactDescription(string name)
        {
            switch(name) {
                case "agent_tasks.md":return "子任务、任务时序、时间窗口、协同约束（阅读版）";
                case "agent_tasks.csv":return "单平台任务明细的表格版，可筛选与统计";
                case "agent_tasks.json":return "单平台任务明细的完整结构，供程序读取";
                case "execution_plan.json":return "实际下发绑定的规划版本、执行尝试和指令关联";
                case "planning_history.json":return "运行过程中生成的各次规划快照";
                case "plan.json":return "静态参考方案，区别于实际下发版本";
                case "chain_viewer.html":return "实际指令与反馈的全链路追溯页面";
                case "report.json":return "本轮运行结果和指标";
                case "report.md":return "旧版合并报告，已由单平台明细和运行报告替代";
                case "summary.txt":return "运行结果摘要（旧记录还可能包含事件全文）";
                case "trace.jsonl":return "原始过程审计与回放数据";
                case "ros2_plan_node.py":return "Gazebo 对接：ROS 2 计划发布节点（待联调）";
                case "ros2_commands.txt":return "旧版 ROS 2 命令参考，建议使用计划发布节点";
                case "commands.csv":return "静态计划速度指令表，非实际下发日志";
                case "assignments.csv":return "静态参考方案的平台与子任务分配表";
                case "desktop_input.json":return "桌面提交的完整任务、编成与运行配置快照";
                case "request.json":return "本轮启动参数与优化目标";
                case "input_message.json":return "4.1 原始任务输入";
                case "input_formation.json":return "平台编成、坐标、能力与约束输入";
                case "scenario.json":return "执行基座场景快照，回放依赖";
                case "manifest.json":return "本轮配置、来源、版本及关联产物";
                case "initial_config.json":return "全链路初始配置快照";
                case "final_config.json":return "全链路最后配置快照，非平台最终状态";
                case "chain_raw.json":return "全链路追溯汇总原始数据";
                case "chain_summary.json":return "全链路校验摘要";
                case "chain_verification.json":return "全链路关联、完整性与哈希检查";
                case "worker.log":return "后台运行日志与错误信息";
                default:return "其他运行产物";
            }
        }
        private void RefreshNativeFiles(DesktopRunView run)
        {
            nativeFiles.BeginUpdate();
            try {
                nativeFiles.Items.Clear(); nativeFiles.Groups.Clear();
                var priority = new ListViewGroup("优先查看：单平台智能体的子任务、任务时序、时间窗口、协同约束");
                var other = new ListViewGroup("运行结果与追溯");
                var gazebo = new ListViewGroup("Gazebo 对接（ROS 2，待联调）");
                var advanced = new ListViewGroup("高级文件：输入复现、规划参考与原始日志");
                nativeFiles.Groups.Add(priority);nativeFiles.Groups.Add(other);nativeFiles.Groups.Add(gazebo);nativeFiles.Groups.Add(advanced);
                foreach(string file in run.Files.Where(f=>showAllArtifacts||PrimaryArtifact(f)).OrderBy(ArtifactPriority)) {
                    var item=new ListViewItem(new[]{file,Path.GetExtension(file).TrimStart('.'),ArtifactDescription(file)});
                    item.Group=ArtifactPriority(file)<3?priority:file=="ros2_plan_node.py"||file=="ros2_commands.txt"?gazebo:PrimaryArtifact(file)?other:advanced;
                    item.ToolTipText=ArtifactDescription(file);item.Tag=file;
                    if(ArtifactPriority(file)<3)item.ForeColor=Color.FromArgb(31,111,195);
                    nativeFiles.Items.Add(item);
                }
            } finally {nativeFiles.EndUpdate();}
        }
    }
}
