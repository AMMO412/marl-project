using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        public async Task VerifyLegendAndReading(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(75);
            while((desktopApi==null||desktopRun==null||!webReady)&&DateTime.UtcNow<deadline)await Task.Delay(200);
            if(desktopRun==null||!webReady)throw new Exception("Reading verification backend not ready");
            await Task.Delay(1500);await webView.CoreWebView2.ExecuteScriptAsync("MarlDesktop.pause()");
            foreach(int width in new[]{1500,1180})
            {
                Size=new Size(width,width==1500?940:780);ResetLayout();Documents.SelectedIndex=0;await Task.Delay(350);
                var legend=(FlowLayoutPanel)Controls.Find("DesktopSceneLegend",true)[0];
                if(legend.AutoScroll||legend.WrapContents||legend.HorizontalScroll.Visible)throw new Exception("Legend still scrolls horizontally");
                foreach(Control item in legend.Controls)
                    if(item.Visible && (item.Left<0||item.Right>legend.ClientSize.Width||item.Bottom>legend.ClientSize.Height))throw new Exception("Clipped legend: "+item.Text+" "+item.Bounds+" "+legend.ClientRectangle);
                if(legend.Height>32)throw new Exception("Legend consumes too much map height");
                await SaveNativeScreenshot(Path.Combine(directory,"legend-"+width+".png"));
            }
            var details=await Task.Run(()=>desktopApi.GetDetails(desktopRunId));
            string[] preferred={"agent_tasks.md","agent_tasks.csv","agent_tasks.json"};
            for(int i=0;i<preferred.Length;i++)if(nativeFiles.Items[i].Text!=preferred[i]||!nativeFiles.Items[i].Group.Header.StartsWith("优先查看"))throw new Exception("Agent output priority missing");
            if(nativeFiles.Columns.Count!=3||Controls.Find("OpenAgentTaskDetails",true).Length!=1)throw new Exception("Agent task description or direct entry missing");
            if(nativeFiles.Items.Cast<ListViewItem>().Any(i=>!PrimaryArtifact(i.Text)))throw new Exception("Advanced artifacts visible by default");
            var gazebo=nativeFiles.Items.Cast<ListViewItem>().First(i=>i.Text=="ros2_plan_node.py");
            if(!gazebo.Group.Header.Contains("Gazebo")||!gazebo.SubItems[2].Text.Contains("待联调"))throw new Exception("Gazebo interface label missing");
            var allFiles=(CheckBox)Controls.Find("ShowAllArtifacts",true)[0];allFiles.Checked=true;
            if(nativeFiles.Items.Count!=desktopRun.Files.Count)throw new Exception("Show all does not preserve artifact access");allFiles.Checked=false;
            ((TabControl)Controls.Find("NativeOutputTabs",true)[0]).SelectedIndex=2;
            await Task.Delay(200);await SaveNativeScreenshot(Path.Combine(directory,"prioritized-agent-outputs.png"));
            Documents.SelectedIndex=0;
            if(taskGrid.Columns[4].DefaultCellStyle.WrapMode!=DataGridViewTriState.True || taskGrid.AutoSizeRowsMode!=DataGridViewAutoSizeRowsMode.AllCells)throw new Exception("Task platform list does not wrap");
            SelectDesktopTask(desktopRun.Tasks[0].Id,false);
            var members=(TextBox)Controls.Find("TaskMembersText",true)[0];
            foreach(string id in desktopRun.Tasks[0].Assigned)if(!members.Text.Contains(id))throw new Exception("Missing assigned platform: "+id);
            if(!members.WordWrap||!members.Multiline||!members.Visible)throw new Exception("Task members are not visible as wrapped text");
            await SaveNativeScreenshot(Path.Combine(directory,"task-properties-wrapped.png"));
            string markdown=Convert.ToString(details["agent_tasks_text"]);
            foreach(string field in new[]{"子任务 / 父任务","机动起点","时间窗口","协同约束"})if(!markdown.Contains(field))throw new Exception("Missing agent task field: "+field);
            string reading=NativeDocumentView.ReadingText(markdown);
            if(!reading.Contains("\r\n子任务 / 父任务：")||reading.Split('\n').Length<30)throw new Exception("Agent tasks not converted to vertical records");
            var page=new TabPage();page.Controls.Add(NativeDocumentView.Create("agent_tasks.md",markdown));
            var box=(TextBox)page.Controls.Find("NativeDocumentReading",true)[0];
            var source=(CheckBox)page.Controls.Find("NativeDocumentSource",true)[0];
            if(!box.WordWrap||box.ScrollBars!=ScrollBars.Vertical)throw new Exception("Reading still requires horizontal scrolling");
            source.Checked=true;if(NativeDocumentView.NormalizeLines(box.Text)!=NativeDocumentView.NormalizeLines(markdown))throw new Exception("Source text lost fields or line breaks");
            source.Checked=false;if(!NativeDocumentText(page).Contains("子任务 / 父任务："))throw new Exception("Copy/save cannot read the document view");page.Dispose();
            string fenced="```text\n|a|b|\n|---|---|\n|1|2|\n```";
            if(!NativeDocumentView.ReadingText(fenced).Contains("|1|2|"))throw new Exception("Code block altered");
            ShowNativeDocument("单平台任务明细 · 阅读预览",new System.Collections.Generic.Dictionary<string,object>{{"agent_tasks.md",markdown}},Path.Combine(directory,"agent-tasks-reading.png"));
            File.WriteAllText(Path.Combine(directory,"reading-verification.json"),desktopJson.Serialize(new {
                run=desktopRunId,legendWraps=false,singleRowLegend=true,taskPlatformsWrap=true,fullPlatformList=true,allLegendItemsVisible=true,widths=new[]{1500,1180},
                verticalTaskRecords=true,sourcePreserved=true,automaticWordWrap=true,copySave=true,codeBlocksPreserved=true}));
        }
    }
}
