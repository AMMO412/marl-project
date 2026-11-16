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
        public async Task VerifyHistoryObjectives(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(75);
            while((desktopCatalog==null||desktopRun==null||!webReady)&&DateTime.UtcNow<deadline)await Task.Delay(200);
            if(desktopCatalog==null||desktopRun==null||!webReady)throw new Exception("History verification backend not ready");
            await Task.Delay(1500);Documents.SelectedIndex=2;RefreshNativeHistoryFilter();
            if(history.Columns.Count!=5||history.Columns[2].Text!="优化目标")throw new Exception("Objective column missing");
            foreach(ListViewItem item in history.Items)
            {
                var run=desktopCatalog.Runs.First(r=>r.Id==Convert.ToString(item.Tag));
                if(item.SubItems[2].Text!=ObjectiveDisplayName(run.Objective))throw new Exception("Objective associated with wrong run");
            }
            var original=desktopCatalog;
            try
            {
                desktopCatalog=new DesktopCatalog();desktopCatalog.Scenarios["test"]="测试场景";
                string[] keys={"makespan","energy","balanced","exposure",""};
                string[] labels={"完工时间","能耗","均衡","暴露度","未记录"};
                for(int i=0;i<keys.Length;i++)desktopCatalog.Runs.Add(new DesktopRunSummary{Id="run_"+i,Scenario="test",Objective=keys[i]});
                for(int i=0;i<labels.Length;i++)
                {
                    nativeHistorySearch.Text=labels[i];RefreshNativeHistoryFilter();
                    if(history.Items.Count!=1||Convert.ToString(history.Items[0].Tag)!="run_"+i)throw new Exception("Objective search mismatch: "+labels[i]);
                }
                nativeHistorySearch.Text="balanced";if(history.Items.Count!=1||Convert.ToString(history.Items[0].Tag)!="run_2")throw new Exception("Raw objective key filter failed");
            }
            finally {desktopCatalog=original;nativeHistorySearch.Clear();RefreshNativeHistoryFilter();}
            Size=new Size(1500,940);ResetLayout();Documents.SelectedIndex=2;await Task.Delay(150);
            await SaveNativeScreenshot(Path.Combine(directory,"history-objectives.png"));
            File.WriteAllText(Path.Combine(directory,"history-verification.json"),desktopJson.Serialize(new {
                runs=history.Items.Count,objectiveColumn=true,perRunIdentity=true,fourObjectives=true,
                missingObjectiveExplicit=true,chineseSearch=true,rawKeySearch=true}));
        }
    }
}
