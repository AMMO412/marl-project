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
        public async Task VerifySavedRunComparison(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(75);
            while((desktopApi==null||desktopCatalog==null||!webReady) && DateTime.UtcNow<deadline)await Task.Delay(200);
            if(desktopApi==null||desktopCatalog==null||!webReady)throw new Exception("Comparison backend not ready");
            var catalog=await Task.Run(()=>desktopApi.GetCatalog());
            if(catalog.Runs.Count==0)throw new Exception("No saved run for real-data verification");
            string scenario=catalog.Runs.Any(r=>r.Scenario=="interop_containment")?"interop_containment":catalog.Runs[0].Scenario;
            string loaded="";
            using(var dialog=new RunComparisonDialog(catalog,scenario,id=>loaded=id,()=>Task.FromResult(catalog)))
            {
                dialog.ShowInTaskbar=false;dialog.StartPosition=FormStartPosition.Manual;dialog.Location=new Point(-16000,-16000);dialog.Show();
                if(dialog.Table.Rows.Count!=catalog.Runs.Count(r=>r.Scenario==scenario))throw new Exception("Saved run count differs");
                if(!dialog.Table.Columns[5].HeaderText.Contains("被侦察到的概率") || !dialog.Note.Text.Contains("同一轮") || !dialog.Note.Text.Contains("不能直接作为规划误差"))throw new Exception("Probability or metric source explanation missing");
                File.WriteAllText(Path.Combine(directory,"saved-run-comparison.csv"),dialog.ExportCsv(),new System.Text.UTF8Encoding(true));
                using(var bitmap=new Bitmap(dialog.Width,dialog.Height)){dialog.DrawToBitmap(bitmap,new Rectangle(0,0,dialog.Width,dialog.Height));bitmap.Save(Path.Combine(directory,"saved-run-comparison.png"));}
                dialog.LoadRow(0);
            }
            if(string.IsNullOrEmpty(loaded))throw new Exception("Run load callback did not receive identity");
            // The real parent callback must load this exact record in the main view.
            LoadRunAsync(loaded);deadline=DateTime.UtcNow.AddSeconds(30);
            while((desktopRun==null||desktopRun.Id!=loaded) && DateTime.UtcNow<deadline)await Task.Delay(200);
            if(desktopRun==null||desktopRun.Id!=loaded)throw new Exception("Selected comparison record not loaded");
            var sample=new DesktopCatalog();sample.Scenarios["a"]="场景 A";sample.Scenarios["empty"]="空场景";
            sample.Runs.Add(new DesktopRunSummary{Id="repeat_2",Scenario="a",Objective="makespan",Done=1,Total=1,Makespan=0,PlanEnergy=0,PlanExposure=0,ExecutionExposure=7,PlanProbability=0,ExecutionProbability=.5,Retries=0,Timeouts=0});
            sample.Runs.Add(new DesktopRunSummary{Id="repeat_1",Scenario="a",Objective="makespan",Done=0,Total=1});
            sample.Runs.Add(new DesktopRunSummary{Id="exposure",Scenario="a",Objective="exposure"});
            using(var dialog=new RunComparisonDialog(sample,"a",id=>loaded=id,()=>Task.FromResult(sample)))
            {
                if(dialog.Table.Rows.Count!=3)throw new Exception("Repeated objectives were merged");
                if(Convert.ToString(dialog.Table.Rows[0].Cells[2].Value)!="—")throw new Exception("Missing makespan fabricated");
                var zero=dialog.Table.Rows[1];
                if(Convert.ToString(zero.Cells[2].Value)!="0.0"||Convert.ToString(zero.Cells[3].Value)!="0.0"||Convert.ToString(zero.Cells[4].Value)!="0.00 / 7.00"||Convert.ToString(zero.Cells[5].Value)!="0.0% / 50.0%"||Convert.ToString(zero.Cells[6].Value)!="0 / 0")throw new Exception("Zero/missing/plan-execution metrics mixed");
                if(!dialog.ExportCsv().Contains("repeat_2")||!dialog.ExportCsv().Contains("运行编号"))throw new Exception("Export missing run identity");
                dialog.SetCatalog(sample,"empty");if(dialog.Table.Rows.Count!=0||!dialog.Note.Text.Contains("暂无"))throw new Exception("Empty scene kept stale rows");
                sample.Runs.RemoveAt(0);dialog.SetCatalog(sample,"a");if(dialog.Table.Rows.Count!=2||dialog.ExportCsv().Contains("repeat_2"))throw new Exception("Refresh kept removed record");
                dialog.LoadRow(0);if(loaded!="repeat_1")throw new Exception("Wrong repeated objective record loaded");
            }
            if(Controls.Find("CompareSavedRuns",true).Length!=1)throw new Exception("History entry missing");
            await Task.Delay(800);Documents.SelectedIndex=2;Size=new Size(1180,780);ResetLayout();await Task.Delay(200);
            var entry=Controls.Find("CompareSavedRuns",true)[0];
            if(!entry.Visible||!entry.Parent.ClientRectangle.Contains(entry.Bounds))throw new Exception("Comparison entry clipped at compact size: visible="+entry.Visible+" bounds="+entry.Bounds+" parent="+entry.Parent.ClientRectangle+" tab="+Documents.SelectedIndex);
            await SaveNativeScreenshot(Path.Combine(directory,"history-comparison-entry.png"));
            File.WriteAllText(Path.Combine(directory,"comparison-verification.json"),desktopJson.Serialize(new {
                realCatalog=true,scenario=scenario,savedRuns=catalog.Runs.Count(r=>r.Scenario==scenario),
                loadedRun=desktopRunId,repeatObjectivesPreserved=true,zeroPreserved=true,missingValuesExplicit=true,
                planAndExecutionSeparate=true,probabilityPercent=true,scenarioSwitch=true,refresh=true,csvWithRunIdentity=true,
                probabilityLabelChinese=true,sameRunExplanation=true,planVersionCaveat=true }));
        }
    }
}
