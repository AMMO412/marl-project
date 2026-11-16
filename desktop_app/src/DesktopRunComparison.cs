using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    internal sealed class RunComparisonDialog : Form
    {
        internal readonly ComboBox Scenario = new ComboBox { DropDownStyle=ComboBoxStyle.DropDownList, Width=250, DropDownWidth=430, Name="RunCompareScenario" };
        internal readonly DataGridView Table = new DataGridView { Dock=DockStyle.Fill, ReadOnly=true, AllowUserToAddRows=false, AllowUserToDeleteRows=false, RowHeadersVisible=false, SelectionMode=DataGridViewSelectionMode.FullRowSelect, MultiSelect=false, AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill, BackgroundColor=Color.White, BorderStyle=BorderStyle.None, Name="RunCompareTable" };
        internal readonly Label Note = new Label { Dock=DockStyle.Bottom, Height=125, Padding=new Padding(10,6,10,4), ForeColor=Color.SlateGray };
        private DesktopCatalog catalog;
        private readonly Action<string> loadRun;
        private readonly Func<Task<DesktopCatalog>> refreshCatalog;
        internal static readonly string[] Headers = {"目标","完成","计划 makespan / s","计划能耗","暴露量 计划 / 执行","被侦察到的概率（计划 / 执行）","重试 / 超时","运行"};

        private sealed class ScenarioItem
        {
            internal string Key, Label;
            public override string ToString() { return Label + " · " + Key; }
        }

        internal RunComparisonDialog(DesktopCatalog source, string selectedScenario, Action<string> load, Func<Task<DesktopCatalog>> refresh)
        {
            Text="同场景目标对比 · 已保存运行"; Size=new Size(1220,580); MinimumSize=new Size(930,420);
            StartPosition=FormStartPosition.CenterParent;BackColor=Color.White;Font=new Font("Microsoft YaHei UI",9f);
            catalog=source;loadRun=load;refreshCatalog=refresh;
            var heading=new FlowLayoutPanel { Dock=DockStyle.Top, Height=76, Padding=new Padding(10,7,10,4), WrapContents=false };
            var intro=new Label { Text="同场景目标对比\r\n汇总已保存运行；同一目标的多次运行逐行保留。", Width=510,Height=58, ForeColor=Color.FromArgb(53,88,124) };
            var refreshButton=new Button { Text="刷新",Width=65,Height=29,Name="RefreshRunComparison" };
            heading.Controls.AddRange(new Control[]{intro,new Label {Text="场景",AutoSize=true,Margin=new Padding(4,8,4,0)},Scenario,refreshButton});
            foreach(string title in Headers.Take(7))Table.Columns.Add(new DataGridViewTextBoxColumn {HeaderText=title,Name=title,SortMode=DataGridViewColumnSortMode.NotSortable,MinimumWidth=65});
            Table.Columns[0].FillWeight=135;Table.Columns[1].FillWeight=55;Table.Columns[2].FillWeight=115;
            Table.Columns[4].FillWeight=140;Table.Columns[5].FillWeight=140;
            Table.Columns[5].FillWeight=190;Table.Columns[5].MinimumWidth=170;
            Table.ColumnHeadersDefaultCellStyle.WrapMode=DataGridViewTriState.True;
            Table.Columns[4].ToolTipText="计划按静态计划路线估计；执行按同一轮本地模拟轨迹统计，统计时段和实际下发版本可能不同。";
            Table.Columns[5].ToolTipText="全队至少一台平台被侦察到的模型概率，由暴露量折算；未用真实探测器标定。左侧为计划估计，右侧为本轮模拟执行统计。";
            Table.Columns[0].ToolTipText="均衡对时效、暴露、能耗的归一化评分加权，权重为 0.5 / 0.3 / 0.2；不保证折中结果与单目标方案不同。";
            Table.Columns.Add(new DataGridViewButtonColumn { HeaderText="运行",Name="load",Text="载入 ↗",UseColumnTextForButtonValue=true,FillWeight=65,MinimumWidth=70 });
            Table.EnableHeadersVisualStyles=false;Table.ColumnHeadersDefaultCellStyle.BackColor=Color.FromArgb(235,243,253);
            Table.ColumnHeadersDefaultCellStyle.ForeColor=Color.FromArgb(53,91,138);Table.ColumnHeadersHeight=55;
            Table.DefaultCellStyle.ForeColor=Color.FromArgb(43,84,134);Table.DefaultCellStyle.SelectionBackColor=Color.FromArgb(220,235,252);
            Table.DefaultCellStyle.SelectionForeColor=Color.FromArgb(30,71,124);Table.RowTemplate.Height=43;
            Table.CellContentClick+=delegate(object sender,DataGridViewCellEventArgs e) {if(e.RowIndex>=0 && e.ColumnIndex==7)LoadRow(e.RowIndex);};
            Table.CellDoubleClick+=delegate(object sender,DataGridViewCellEventArgs e) {if(e.RowIndex>=0)LoadRow(e.RowIndex);};
            Table.SelectionChanged+=delegate {UpdateNote();};
            Scenario.SelectedIndexChanged+=delegate {Render();};
            refreshButton.Click+=async delegate {
                refreshButton.Enabled=false;
                try {var fresh=await refreshCatalog();if(!IsDisposed)SetCatalog(fresh,SelectedScenario);}
                catch(Exception ex) {if(!IsDisposed)Note.Text="刷新失败："+ex.Message;}
                finally {if(!IsDisposed)refreshButton.Enabled=true;}
            };
            var actions=new FlowLayoutPanel {Dock=DockStyle.Bottom,Height=44,Padding=new Padding(9,6,9,4)};
            var open=new Button {Text="载入所选运行",Width=120,Height=29};open.Click+=delegate {if(Table.CurrentRow!=null)LoadRow(Table.CurrentRow.Index);};
            var copy=new Button {Text="复制表格",Width=90,Height=29};copy.Click+=delegate {try {Clipboard.SetText(ExportCsv());}catch(Exception ex){Note.Text="复制失败："+ex.Message;}};
            var save=new Button {Text="导出 CSV…",Width=105,Height=29};save.Click+=delegate {
                using(var file=new SaveFileDialog {Filter="CSV (*.csv)|*.csv",FileName="run-objective-comparison.csv"})
                    if(file.ShowDialog(this)==DialogResult.OK)try {File.WriteAllText(file.FileName,ExportCsv(),new UTF8Encoding(true));}catch(Exception ex){Note.Text="导出失败："+ex.Message;}
            };
            var close=new Button {Text="关闭",Width=75,Height=29,DialogResult=DialogResult.Cancel};CancelButton=close;
            actions.Controls.AddRange(new Control[]{open,copy,save,close});
            Controls.Add(Table);Controls.Add(heading);Controls.Add(Note);Controls.Add(actions);
            SetCatalog(source,selectedScenario);
        }

        internal string SelectedScenario { get {var selected=Scenario.SelectedItem as ScenarioItem;return selected==null?"":selected.Key;} }
        internal void SetCatalog(DesktopCatalog source,string preferred)
        {
            catalog=source;Scenario.Items.Clear();
            var keys=source.Scenarios.Keys.Union(source.Runs.Select(r=>r.Scenario).Where(s=>!string.IsNullOrEmpty(s))).OrderBy(s=>s,StringComparer.Ordinal).ToList();
            foreach(string key in keys) {string label;source.Scenarios.TryGetValue(key,out label);Scenario.Items.Add(new ScenarioItem{Key=key,Label=label??key});}
            int index=keys.IndexOf(preferred);Scenario.SelectedIndex=index>=0?index:keys.Count>0?0:-1;Render();
        }
        private static int ObjectiveOrder(string value)
        {switch(value){case "makespan":case "timeliness":return 0;case "energy":return 1;case "balanced":return 2;case "exposure":case "dispersion":return 3;default:return 9;}}
        private static string ObjectiveLabel(string value)
        {switch(value){case "makespan":case "timeliness":return "完工时间";case "energy":return "能耗";case "balanced":return "均衡";case "exposure":case "dispersion":return "暴露度";default:return string.IsNullOrEmpty(value)?"未记录":value;}}
        private static string Number(double? value,string format="0.0") {return value.HasValue?value.Value.ToString(format,CultureInfo.InvariantCulture):"—";}
        private static string Probability(double? value) {return value.HasValue?(100*value.Value).ToString("0.0",CultureInfo.InvariantCulture)+"%":"—";}
        private void Render()
        {
            Table.Rows.Clear();
            foreach(var run in catalog.Runs.Where(r=>r.Scenario==SelectedScenario).OrderBy(r=>ObjectiveOrder(r.Objective)).ThenBy(r=>r.Id,StringComparer.Ordinal))
            {
                string source=run.PlanMetricsSource=="legacy_static_unbound"?" · 旧静态参考":run.PlanMetricsSource=="runtime_dispatch"?" · 已绑定下发":"";
                int index=Table.Rows.Add(ObjectiveLabel(run.Objective)+source,run.Done+" / "+run.Total,Number(run.Makespan),Number(run.PlanEnergy),
                    Number(run.PlanExposure,"0.00")+" / "+Number(run.ExecutionExposure,"0.00"),Probability(run.PlanProbability)+" / "+Probability(run.ExecutionProbability),
                    (run.Retries.HasValue?run.Retries.Value.ToString():"—")+" / "+(run.Timeouts.HasValue?run.Timeouts.Value.ToString():"—"));
                Table.Rows[index].Tag=run;foreach(DataGridViewCell cell in Table.Rows[index].Cells)cell.ToolTipText=run.Id+"\r\n"+run.ComparisonScope;
            }
            UpdateNote();
        }
        private void UpdateNote()
        {
            var run=Table.CurrentRow==null?null:Table.CurrentRow.Tag as DesktopRunSummary;
            Note.Text=(Table.Rows.Count==0?"当前场景暂无已保存运行。":"共 "+Table.Rows.Count+" 次运行；同一目标多行表示重复运行。")+
                "缺失值为 —。\r\n新记录：计划取实际下发版本，执行按同一轮、同次任务尝试的模拟轨迹统计；整轮含返航另存。"+
                "\r\n旧静态参考未绑定下发版本；失败、取消和未完成尝试不能直接作为规划误差。"+
                "\r\n被侦察到的概率由暴露量经演示模型折算，尚未实测标定。均衡按时效 / 暴露 / 能耗 0.5 / 0.3 / 0.2 折中。"+
                "\r\n同场景输入与版本可能不同；均衡结果也可能与其他目标同解。"+
                (run==null?"":"\r\n所选运行："+run.Id+(run.PlanMetricsSource=="runtime_dispatch"?(run.ComparisonComplete?" · 任务尝试已全部完成":" · 含异常/未完成片段"):" · 历史静态口径"));
        }
        internal void LoadRow(int index)
        {
            var run=Table.Rows[index].Tag as DesktopRunSummary;if(run==null)return;
            DialogResult=DialogResult.OK;Close();loadRun(run.Id);
        }
        internal string ExportCsv()
        {
            Func<string,string> quote=s=>"\""+(s??"").Replace("\"","\"\"")+"\"";
            var lines=new List<string>{string.Join(",",new[]{"场景","运行编号"}.Concat(Headers.Take(7)).Select(quote))};
            foreach(DataGridViewRow row in Table.Rows)
            {var run=(DesktopRunSummary)row.Tag;lines.Add(string.Join(",",new[]{SelectedScenario,run.Id}.Concat(row.Cells.Cast<DataGridViewCell>().Take(7).Select(c=>Convert.ToString(c.Value))).Select(quote)));}
            return string.Join("\r\n",lines);
        }
    }

    public sealed partial class MainWindow
    {
        private async void ShowNativeRunComparison()
        {
            if(!HasNativeBackend())return;
            try {
                var fresh=await Task.Run(()=>desktopApi.GetCatalog());if(IsDisposed)return;
                using(var dialog=new RunComparisonDialog(fresh,desktopRun==null?SelectedScenario:desktopRun.Scenario,
                    id=>{LoadRunAsync(id);OpenTaskView();},()=>Task.Run(()=>desktopApi.GetCatalog())))dialog.ShowDialog(this);
            }catch(Exception ex){NativeIssue("读取同场景目标对比失败",ex);}
        }
    }
}
