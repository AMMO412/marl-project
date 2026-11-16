using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
namespace MarlDesktopPreview {
 public sealed partial class MainWindow {
  public async Task VerifyResizeAndChoices(string directory) {
   Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(70);
   while((desktopCatalog==null || !webReady || desktopRun==null) && DateTime.UtcNow<deadline)await Task.Delay(300);
   if(desktopRun==null)throw new Exception("Backend/run not ready");
   if(desktopCatalog.Scenarios.Count!=10 || scenarioBox.Items.Count!=10)throw new Exception("Scene catalogs differ from six delivery demos plus four algorithm benchmarks");
   foreach(string key in new[]{"interop_containment","interop_hold","interop_patrol","interop_recon","interop_asl","interop_bench_multitask","interop_bench_deadlines","interop_bench_threats","interop_bench_chokepoint"})if(!scenarioBox.Items.Contains(key))throw new Exception("Scene catalog missing "+key);
   using(var dialog=new NativeRunConfiguration(desktopApi,desktopCatalog,desktopApi.GetConfiguration("interop_containment",null))) {
    var choices=(System.Windows.Forms.ComboBox)dialog.Controls.Find("NativeScenarioChoice",true)[0];
    var motion=(System.Windows.Forms.ComboBox)dialog.Controls.Find("NativeMotionChoice",true)[0];
    if(choices.Items.Count!=6 || motion.Items.Count!=1 || motion.Enabled)throw new Exception("Configuration dialog exposes retired scene or motion options");
    dialog.ShowInTaskbar=false;dialog.StartPosition=System.Windows.Forms.FormStartPosition.Manual;dialog.Location=new Point(-16000,-16000);dialog.Show();
    using(Bitmap image=new Bitmap(dialog.Width,dialog.Height)){dialog.DrawToBitmap(image,new Rectangle(0,0,image.Width,image.Height));image.Save(Path.Combine(directory,"six-scene-configuration.png"));}dialog.Close();
   }
   var results=new Dictionary<string,object>();
   foreach(string scene in new[]{"interop_containment","interop_hold","interop_recon"}) {
    scenarioBox.SelectedItem=scene;OpenSelectedScenarioDemo();deadline=DateTime.UtcNow.AddSeconds(120);
    bool loaded=false;
    while(DateTime.UtcNow<deadline){await Task.Delay(300);if(desktopRun==null || desktopRun.Scenario!=scene || nativeRunning)continue;var frame=desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState()")) as Dictionary<string,object>;if(frame!=null && Convert.ToString(frame["runId"])==desktopRunId){loaded=true;break;}}
    if(!loaded)throw new Exception("Scene not ready: "+scene);
    await Task.Delay(1000);ReadMapScript("MarlDesktop.pause();MarlDesktop.setTime(60);MarlDesktop.fit('area')");
    for(int layout=0;layout<4;layout++) {
     Size=layout==3?new Size(1280,800):new Size(1500,940);await Task.Delay(150);
     rightSplit.SplitterDistance=Math.Max(rightSplit.Panel1MinSize+30,Math.Min(rightSplit.Width-rightSplit.Panel2MinSize-10,(int)(rightSplit.Width*(layout==1?.46:layout==2?.64:.77))));
     await Task.Delay(450);
     string script=@"(function(){const c=document.querySelector('#desktop-scene-host>canvas'),r=c.getBoundingClientRect(),d=window.devicePixelRatio||1;let points;const api=document.querySelector('#ck-canvas')===c?ContainmentPage:document.querySelector('#hl-canvas')===c?HoldPage:null;if(api)points=api.projectPoints([[0,0],[50,0],[0,50]]);else{const s=mapScale();points=[[0,0],[50*s,0],[0,-50*s]]}const x=Math.abs(points[1][0]-points[0][0])*r.width*d/c.width,y=Math.abs(points[2][1]-points[0][1])*r.height*d/c.height;return {width:r.width,height:r.height,bitmapWidth:c.width,bitmapHeight:c.height,dpr:d,squareRatio:x/y,backingX:c.width/(r.width*d),backingY:c.height/(r.height*d),canvas:c.id,playing:MarlDesktop.getState().playing}})()";
     var check=desktopJson.DeserializeObject(ReadMapScript(script)) as Dictionary<string,object>;
     if(Math.Abs(Convert.ToDouble(check["squareRatio"])-1)>.005 || Math.Abs(Convert.ToDouble(check["backingX"])-1)>.005 || Math.Abs(Convert.ToDouble(check["backingY"])-1)>.005)throw new Exception("Canvas stretched while paused: "+scene+" "+desktopJson.Serialize(check));
     results[scene+"_"+layout]=check;
     if(layout==1){await SaveNativeScreenshot(Path.Combine(directory,scene+"-narrow.png"));await Task.Delay(150);}
     ReadMapScript("MarlDesktop.play()");await Task.Delay(350);
     var playing=desktopJson.DeserializeObject(ReadMapScript(script)) as Dictionary<string,object>;
     if(!Convert.ToBoolean(playing["playing"]) || Math.Abs(Convert.ToDouble(playing["squareRatio"])-1)>.005)throw new Exception("Canvas stretched while playing");
     results[scene+"_"+layout+"_playing"]=playing;
     ReadMapScript("MarlDesktop.pause()");
    }
   }
   File.WriteAllText(Path.Combine(directory,"resize-verification.json"),desktopJson.Serialize(results));
  }
 }
}
