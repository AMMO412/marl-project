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
        private async Task AwaitPlatformCursor(double target)
        {
            DateTime deadline = DateTime.UtcNow.AddSeconds(20);
            while (Math.Abs(desktopRun.At - target) > .15) {
                if (DateTime.UtcNow > deadline) throw new Exception("Platform cursor stayed at " + desktopRun.At + ", expected " + target);
                await Task.Delay(150);
            }
        }
        private string[] DynamicPlatformRow(string id)
        {
            var row = platformGrid.Rows.Cast<DataGridViewRow>().Single(r => Convert.ToString(r.Cells[0].Value) == id);
            return row.Cells.Cast<DataGridViewCell>().Select(c => Convert.ToString(c.Value)).ToArray();
        }
        public async Task VerifyDynamicPlatforms(string directory)
        {
            Directory.CreateDirectory(directory); DateTime deadline = DateTime.UtcNow.AddSeconds(75);
            while (desktopApi == null || desktopCatalog == null || !webReady) {
                if (DateTime.UtcNow > deadline) throw new Exception("Dynamic platform backend not ready"); await Task.Delay(200);
            }
            var selected = desktopCatalog.Runs.First(r => r.Scenario == "interop_containment" && r.Done > 0);
            LoadRunAsync(selected.Id);
            while (desktopRunId != selected.Id) { if (DateTime.UtcNow > deadline) throw new Exception("Run not loaded"); await Task.Delay(200); }
            await Task.Delay(2200); SetPlaying(false); SetTime(.5); await AwaitPlatformCursor(.5);
            string[] start = DynamicPlatformRow("rover_01");
            if (start[3] == "progress" || start[4] == "0.0" || start[4] == "—") throw new Exception("Sparse telemetry or phase is still wrong");
            Documents.SelectedIndex = 1; await Task.Delay(300);
            var chosen = platformGrid.Rows.Cast<DataGridViewRow>().Single(r => Convert.ToString(r.Cells[0].Value) == "rover_01");
            platformGrid.CurrentCell = chosen.Cells[0];
            await SaveNativeScreenshot(Path.Combine(directory, "platforms-before.png"));
            PlaybackSpeed = 8; await webView.CoreWebView2.ExecuteScriptAsync("MarlDesktop.setSpeed(8)");
            SetPlaying(true); await Task.Delay(5200); SetPlaying(false); await Task.Delay(600);
            double advanced = Time; await AwaitPlatformCursor(advanced);
            string[] moving = DynamicPlatformRow("rover_01");
            File.WriteAllText(Path.Combine(directory, "platforms-observed.json"), desktopJson.Serialize(new {run=selected.Id,start=start,after=moving,time=Time,cursor=desktopRun.At,tab=Documents.SelectedIndex}));
            if (advanced < 25 || moving[3] == start[3] || moving[4] == start[4] || Documents.SelectedIndex != 1) throw new Exception("Hidden replay did not update the platform list");
            if (Convert.ToString(platformGrid.CurrentRow.Cells[0].Value) != "rover_01") throw new Exception("Refresh changed platform selection");
            await SaveNativeScreenshot(Path.Combine(directory, "platforms-playing.png"));
            await Task.Delay(1400); if (Math.Abs(Time - advanced) > .15) throw new Exception("Pause did not stop background clock");
            SetTime(.5); await AwaitPlatformCursor(.5);
            if (Documents.SelectedIndex != 1 || !DynamicPlatformRow("rover_01").SequenceEqual(start)) throw new Exception("Rewind did not restore platform values on the same tab");
            SetTime(PlaybackEnd); await AwaitPlatformCursor(PlaybackEnd);
            string[] finished = DynamicPlatformRow("rover_01");
            if (finished[2] != "—" || finished[3] != "已返回出发点") throw new Exception("Finished platform still shows an active task");
            await SaveNativeScreenshot(Path.Combine(directory, "platforms-returned.png"));
            OpenTaskView(); await Task.Delay(500);
            string renderer = await webView.CoreWebView2.ExecuteScriptAsync("JSON.stringify(MarlDesktop.getState())");
            var otherRenderers = new Dictionary<string, object>();
            foreach (string scenario in new[] { "interop_hold", "interop_recon" }) {
                var record = desktopCatalog.Runs.First(r => r.Scenario == scenario && r.Done > 0);
                LoadRunAsync(record.Id); deadline = DateTime.UtcNow.AddSeconds(30);
                while (desktopRunId != record.Id) { if (DateTime.UtcNow > deadline) throw new Exception("Other renderer not loaded"); await Task.Delay(200); }
                await Task.Delay(2200); SetPlaying(false); SetTime(1.5); await AwaitPlatformCursor(1.5);
                PlaybackSpeed = 2; await webView.CoreWebView2.ExecuteScriptAsync("MarlDesktop.setSpeed(2)");
                Documents.SelectedIndex = 1; SetPlaying(true); await Task.Delay(2300);
                double hiddenTime = Time;
                if (hiddenTime < 4.5 || Documents.SelectedIndex != 1) throw new Exception("Background clock failed: " + scenario);
                OpenTaskView(); await Task.Delay(1600); SetPlaying(false); await Task.Delay(700);
                if (Time <= hiddenTime + 1 || Time > hiddenTime + 6.5) throw new Exception("Visible playback did not resume at correct speed: " + scenario);
                await AwaitPlatformCursor(Time);
                otherRenderers[scenario] = new {run=record.Id,hiddenTime=hiddenTime,resumedTime=Time};
            }
            File.WriteAllText(Path.Combine(directory, "dynamic-platform-verification.json"), desktopJson.Serialize(new {
                run=selected.Id,start=start,playing=moving,finished=finished,advancedTime=advanced,
                hiddenTabPlayback=true,eightTimesPlayback=true,phaseChanges=true,sparseBattery=true,
                stableSelection=true,pause=true,rewind=true,returnClearsCurrentTask=true,rendererState=renderer,
                otherRenderers=otherRenderers}));
        }
    }
}
