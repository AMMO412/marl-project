using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        public async Task VerifyPlatformPresentation(string directory)
        {
            Directory.CreateDirectory(directory);
            DateTime deadline=DateTime.UtcNow.AddSeconds(80);
            while((desktopRun==null || !webReady || altitudeRunId!=desktopRunId) && DateTime.UtcNow<deadline)await Task.Delay(250);
            if(desktopRun==null || !webReady || altitudeRunId!=desktopRunId)throw new Exception("Native altitude bridge not ready");
            // Initial scenario loading schedules autoplay after the first bridge frame.
            await Task.Delay(4000);
            await webView.CoreWebView2.ExecuteScriptAsync("MarlDesktop.pause();MarlDesktop.setTime(Math.min(80,MarlDesktop.getState().duration-1))");
            await Task.Delay(2300);
            if(altitudeAircraft.Items.Count==0)throw new Exception("Expected recorded aircraft in default scene");
            if(!altitudeReading.Text.Contains("z ") || altitudeChart.Samples.Count==0)throw new Exception("Missing native height reading");
            string run=desktopRunId;
            string height=altitudeReading.Text;
            await SaveNativeScreenshot(Path.Combine(directory,"scene-altitude.png"));
            int visibleSamples=altitudeChart.Samples.Count(p=>p.Time<=Time+1e-9);
            await webView.CoreWebView2.ExecuteScriptAsync("MarlDesktop.pause();MarlDesktop.setTime(0)");await Task.Delay(1800);
            int rewindSamples=altitudeChart.Samples.Count(p=>p.Time<=Time+1e-9);
            if(Time>.1 || rewindSamples>=visibleSamples)throw new Exception("Rewind did not hide future altitude samples");
            if(altitudeAircraft.Items.Count>1) { altitudeAircraft.SelectedIndex=1;if(!altitudeSamples.ContainsKey(Convert.ToString(altitudeAircraft.SelectedItem)))throw new Exception("Aircraft selection failed"); }
            await webView.CoreWebView2.ExecuteScriptAsync("MarlDesktop.setTime(Math.min(80,MarlDesktop.getState().duration-1))");await Task.Delay(2200);
            Documents.SelectedIndex=1;await Task.Delay(250);
            var ids=platformGrid.Rows.Cast<DataGridViewRow>().Select(r=>Convert.ToString(r.Cells[0].Value)).ToArray();
            var expected=ParticipatingPlatforms(desktopRun).Select(p=>p.Id).ToArray();
            if(!ids.SequenceEqual(expected)||ids.Length==desktopRun.Platforms.Count)throw new Exception("Unused platforms remain in table");
            var branch=tree.Nodes[0].Nodes.Cast<TreeNode>().First(n=>n.Text.StartsWith("平台"));
            if(branch.Nodes.Count!=ids.Length||!branch.Text.Contains(ids.Length.ToString()))throw new Exception("Used platform count mismatch");
            if(!branch.Nodes.Cast<TreeNode>().Select(n=>Convert.ToString(n.Tag).Replace("desktop:platform:","")).SequenceEqual(ids))throw new Exception("Tree and table participants differ");
            bool idle=false;
            foreach(DataGridViewRow row in platformGrid.Rows)
            {
                bool assigned=Convert.ToString(row.Cells[6].Value)=="已分配任务";
                if(!assigned)idle=true;else if(idle)throw new Exception("Mission platforms appear below idle ones");
                var p=desktopRun.Platforms.First(x=>x.Id==Convert.ToString(row.Cells[0].Value));
                if(Convert.ToString(row.Cells[2].Value)!=(string.IsNullOrEmpty(p.Job)?"—":p.Job))throw new Exception("Platform row identity mismatch");
                if(Convert.ToString(row.Cells[5].Value)!=p.Z.ToString("0.00"))throw new Exception("Height column not synchronized");
            }
            nativePlatformSearch.Text=ids[0];
            if(platformGrid.Rows.Cast<DataGridViewRow>().Count(r=>r.Visible)!=1)throw new Exception("Sorted grid filter failed");
            nativePlatformSearch.Text="";
            await SaveNativeScreenshot(Path.Combine(directory,"platforms-sorted.png"));
            var details=await Task.Run(()=>desktopApi.GetDetails(run));
            string text=Convert.ToString(details["agent_tasks_text"]);
            if(!text.Contains("时间窗口") || !text.Contains("协同约束") || !text.Contains("子任务"))throw new Exception("Missing per-agent plan output");
            if(nativeFiles.Items.Count<3 || nativeFiles.Items[0].Text!="agent_tasks.md")throw new Exception("Agent output is not prioritized");
            File.WriteAllBytes(Path.Combine(directory,"agent_tasks.md"),await Task.Run(()=>desktopApi.DownloadArtifact(run,"agent_tasks.md")));
            // Exercise sequence-independent natural sorting and update identity explicitly.
            var synthetic=new DesktopRunView();
            synthetic.Platforms.Add(new DesktopPlatform{Id="rover_10",Kind="UGV",Battery=10,Participates=true});
            synthetic.Platforms.Add(new DesktopPlatform{Id="rover_2",Kind="UGV",Battery=20,Participates=true});
            synthetic.Platforms.Add(new DesktopPlatform{Id="rover_41",Kind="WING",Participates=true,Job="T1",Battery=41});
            synthetic.Platforms.Add(new DesktopPlatform{Id="rover_3",Kind="UGV",Battery=100});
            RefreshNativePlatforms(synthetic);
            if(string.Join(",",platformGrid.Rows.Cast<DataGridViewRow>().Select(r=>Convert.ToString(r.Cells[0].Value)))!="rover_2,rover_10,rover_41")throw new Exception("Natural ordering failed");
            synthetic.Platforms.Reverse();synthetic.Platforms.First(p=>p.Id=="rover_41").Job="T2";RefreshNativePlatforms(synthetic);
            if(Convert.ToString(platformGrid.Rows[2].Cells[2].Value)!="T2")throw new Exception("Sorted update uses source row index");
            RefreshNativePlatforms(desktopRun);
            // Missing height, lost feedback, and no-aircraft states must be explicit.
            string sample="{\"type\":\"altitude\",\"runId\":"+desktopJson.Serialize(run)+",\"aircraft\":[{\"id\":\"test_air\",\"samples\":[[0,1,false],[1,null,false],[2,3,true]]}]}";
            HandleWebMessage(sample);Time=1;UpdateAircraftAltitude();if(!altitudeReading.Text.Contains("无有效"))throw new Exception("Missing sample shown as valid");
            Time=2;UpdateAircraftAltitude();if(!altitudeReading.Text.Contains("失联"))throw new Exception("Lost sample not marked");
            HandleWebMessage("{\"type\":\"altitude\",\"runId\":"+desktopJson.Serialize(run)+",\"aircraft\":[]}");
            if(!altitudeReading.Text.Contains("没有飞机"))throw new Exception("No-aircraft state missing");
            File.WriteAllText(Path.Combine(directory,"presentation-verification.json"),desktopJson.Serialize(new {
                run=run, height=height, platformOrder=ids, visibleSamples=visibleSamples,
                rewindSamples=rewindSamples, aircraftSwitch=true, noFutureHeight=true,
                missingHeight=true, lostFeedback=true, noAircraft=true,
                onlyUsedPlatforms=true, treeCountMatches=true, returnedParticipantsRetained=true, naturalOrdering=true, sortedRefreshIdentity=true, prioritizedAgentExports=true }));
        }
    }
}
