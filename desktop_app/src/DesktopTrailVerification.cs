using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
namespace MarlDesktopPreview {
 public sealed partial class MainWindow {
  public async Task VerifyRecordedTrails(string directory) {
   Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(70);
   while((desktopCatalog==null || desktopRun==null || !webReady) && DateTime.UtcNow<deadline)await Task.Delay(250);
   if(desktopRun==null)throw new Exception("Backend not ready");
   if(sceneLayerLabels.Length!=8 || Convert.ToString(sceneLayerLabels[7])!="运动轨迹")throw new Exception("Trajectory layer is missing");
   var results=new Dictionary<string,object>();
   foreach(string key in new[]{"interop_containment","interop_hold","interop_patrol","interop_recon","interop_asl"}) {
    scenarioBox.SelectedItem=key;OpenSelectedScenarioDemo();deadline=DateTime.UtcNow.AddSeconds(120);bool ready=false;
    while(DateTime.UtcNow<deadline){await Task.Delay(300);if(desktopRun==null || desktopRun.Scenario!=key || nativeRunning)continue;var frame=desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState()")) as Dictionary<string,object>;if(frame!=null && Convert.ToString(frame["runId"])==desktopRunId){ready=true;break;}}
    if(!ready)throw new Exception("Scene not ready: "+key);
    await Task.Delay(1600);
    ReadMapScript("MarlDesktop.pause();MarlDesktop.fit('all');MarlDesktop.setTime(Math.min(80,MarlDesktop.getState().duration-1));MarlDesktop.setLayer('planned',false)");
    SetSceneLayer(3,false);SetSceneLayer(7,true);
    int segments=Convert.ToInt32(desktopJson.DeserializeObject(ReadMapScript("Number(document.querySelector('#desktop-scene-host>canvas').dataset.recordedTrailSegments)")));
    if(segments<=0)throw new Exception("No recorded platform trails: "+key);
    ReadMapScript("window.__trailsOn=document.querySelector('#desktop-scene-host>canvas').toDataURL()");
    ClickLayerMenuItem(6);
    var off=desktopJson.DeserializeObject(ReadMapScript("({visible:MarlDesktop.getState().layers.trails,segments:Number(document.querySelector('#desktop-scene-host>canvas').dataset.recordedTrailSegments),different:window.__trailsOn!==document.querySelector('#desktop-scene-host>canvas').toDataURL()})")) as Dictionary<string,object>;
    if(Convert.ToBoolean(off["visible"]) || Convert.ToInt32(off["segments"])!=0 || !Convert.ToBoolean(off["different"]) || sceneLayerVisibility[7])throw new Exception("Native off switch did not hide trails: "+key+" "+desktopJson.Serialize(off)+" checked="+sceneLayerVisibility[7]);
    ClickLayerMenuItem(6);
    int restored=Convert.ToInt32(desktopJson.DeserializeObject(ReadMapScript("Number(document.querySelector('#desktop-scene-host>canvas').dataset.recordedTrailSegments)")));
    if(restored!=segments || !sceneLayerVisibility[7])throw new Exception("Trails did not restore");
    ReadMapScript("MarlDesktop.setTime(0)");
    int zero=Convert.ToInt32(desktopJson.DeserializeObject(ReadMapScript("Number(document.querySelector('#desktop-scene-host>canvas').dataset.recordedTrailSegments)")));
    if(zero!=0)throw new Exception("Future trails visible at zero time");
    ReadMapScript("MarlDesktop.setTime(Math.min(80,MarlDesktop.getState().duration-1))");
    results[key]=new { nativeMouseToggle=true, pixelsChanged=true, segments=segments, rewindHidesFuture=true, independentOfPlannedRoutes=true, run=desktopRunId };
    if(key=="interop_containment" || key=="interop_hold") { await SaveNativeScreenshot(Path.Combine(directory,key+"-trails.png"));await Task.Delay(150); }
   }
   File.WriteAllText(Path.Combine(directory,"trails-verification.json"),desktopJson.Serialize(results));
  }
 }
}
