using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        public async Task VerifyScenarioDemos(string directory)
        {
            Directory.CreateDirectory(directory);
            DateTime ready = DateTime.UtcNow.AddSeconds(60);
            while ((desktopCatalog == null || !webReady) && DateTime.UtcNow < ready) await Task.Delay(250);
            if (desktopCatalog == null || !webReady) throw new Exception("Desktop backend not ready");
            string[] demoScenarios = new string[] { "interop_containment", "interop_hold", "interop_patrol", "interop_recon", "interop_asl" };
            string[] benchmarkScenarios = new string[] { "interop_bench_multitask", "interop_bench_deadlines", "interop_bench_threats", "interop_bench_chokepoint" };
            if (scenarioBox.Items.Count != demoScenarios.Length + benchmarkScenarios.Length || desktopCatalog.Scenarios.Count != 10)
                throw new Exception("Scene selector must contain six delivery demos and four algorithm benchmarks");
            foreach (string key in demoScenarios) if (!scenarioBox.Items.Contains(key)) throw new Exception("Missing delivery demo: " + key);
            foreach (string key in benchmarkScenarios) if (!scenarioBox.Items.Contains(key)) throw new Exception("Missing algorithm benchmark: " + key);
            foreach (Control c in Controls) {
                ToolStrip strip = c as ToolStrip; if (strip == null || strip is MenuStrip || strip is StatusStrip) continue;
                foreach (ToolStripItem item in strip.Items) if (item.Visible && (item.Text == "播放" || item.Text == "暂停")) throw new Exception("Duplicate toolbar playback buttons remain");
            }
            var results = new Dictionary<string, object>();
            foreach (string key in new [] { "interop_containment", "interop_hold", "interop_patrol", "interop_recon", "interop_asl", "interop_hold", "interop_containment" })
            {
                scenarioBox.SelectedItem = key;
                OpenSelectedScenarioDemo();
                DateTime limit = DateTime.UtcNow.AddSeconds(150);
                bool loaded = false;
                while (DateTime.UtcNow < limit)
                {
                    await Task.Delay(500);
                    if (nativeRunning && nativeWorkProgress.Visible && !File.Exists(Path.Combine(directory,"planning-status.png"))) {
                        await SaveNativeScreenshot(Path.Combine(directory,"planning-status.png")); await Task.Delay(150);
                    }
                    if (desktopRun == null || desktopRun.Scenario != key || nativeRunning) continue;
                    var scene = desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState()")) as Dictionary<string, object>;
                    if (scene != null && Convert.ToString(scene["runId"]) == desktopRunId) { loaded = true; break; }
                }
                if (!loaded) throw new Exception("Scenario did not load: " + key);
                await Task.Delay(1600);
                ReadMapScript("MarlDesktop.pause();MarlDesktop.fit('all');MarlDesktop.setTime(0)");
                await Task.Delay(400);
                string script = @"(function(){
                  const canvas=document.querySelector('#desktop-scene-host>canvas');
                  let icons=0,threats=0,birth=false;
                  const startsMatch=state.run.replay.workers.every(w=>{const p=workerAt(w);return Math.hypot(p.x-w.start[0],p.y-w.start[1])<.01});
                  const icon=window.drawPlatformIcon, clear=CanvasRenderingContext2D.prototype.clearRect, text=CanvasRenderingContext2D.prototype.fillText;
                  CanvasRenderingContext2D.prototype.clearRect=function(){if(this.canvas===canvas){icons=0;threats=0;birth=false}return clear.apply(this,arguments)};
                  window.drawPlatformIcon=function(ctx){if(ctx.canvas===canvas)icons++;return icon.apply(this,arguments)};
                  CanvasRenderingContext2D.prototype.fillText=function(t){if(this.canvas===canvas){if(String(t).startsWith('威胁区 I='))threats++;if(String(t).includes('出发阵地'))birth=true}return text.apply(this,arguments)};
                  try{MarlDesktop.setTime(0)}finally{window.drawPlatformIcon=icon;CanvasRenderingContext2D.prototype.clearRect=clear;CanvasRenderingContext2D.prototype.fillText=text}
                  const count=state.run.replay.workers.length, expected=(state.run.threats||[]).length;
                  MarlDesktop.setLayer('threats',false);const off=canvas.toDataURL();MarlDesktop.setLayer('threats',true);const on=canvas.toDataURL();
                  return {startsMatch,icons,workers:count,threats,expectedThreats:expected,birth,threatPixels:expected===0||off!==on,canvas:canvas.id,run:state.run.id};
                })()";
                var check = desktopJson.DeserializeObject(ReadMapScript(script)) as Dictionary<string, object>;
                if (!Convert.ToBoolean(check["startsMatch"]) || Convert.ToInt32(check["icons"]) < Convert.ToInt32(check["workers"]) || Convert.ToInt32(check["threats"]) != Convert.ToInt32(check["expectedThreats"]) || !Convert.ToBoolean(check["threatPixels"]))
                    throw new Exception("Scene context incomplete: " + key + " " + desktopJson.Serialize(check));
                double middle = Math.Floor(desktopRun.End / 2);
                ReadMapScript("MarlDesktop.setTime(" + middle.ToString(System.Globalization.CultureInfo.InvariantCulture) + ")");
                double sought = Convert.ToDouble(desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState().time")));
                if (Math.Abs(sought - middle) > .15) throw new Exception("Seek failed: " + key);
                ReadMapScript("MarlDesktop.play()"); await Task.Delay(650); ReadMapScript("MarlDesktop.pause()");
                double played = Convert.ToDouble(desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState().time")));
                if (played <= sought) throw new Exception("Playback did not advance: " + key);
                check["seekAndPlayback"] = true;
                ReadMapScript("MarlDesktop.setTime(0)");
                results[key] = check;
                File.WriteAllText(Path.Combine(directory,"scenario-verification.json"),desktopJson.Serialize(results));
                await SaveNativeScreenshot(Path.Combine(directory,key+".png"));
                if (key == "interop_containment") {
                    await Task.Delay(150); // Leave the WebView2 capture callback before issuing another script.
                    ReadMapScript("MarlDesktop.fit('starts')"); await Task.Delay(300);
                    await SaveNativeScreenshot(Path.Combine(directory,"birth-fleet.png"));
                }

            }
        }
    }
}
