using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
namespace MarlDesktopPreview {
 public sealed partial class MainWindow {
  [System.Runtime.InteropServices.DllImport("user32.dll",EntryPoint="SendMessageW")]
  private static extern IntPtr ReconControlMessage(IntPtr window,int message,IntPtr wparam,IntPtr lparam);
  public async Task VerifyReconSelection(string directory) {
   Directory.CreateDirectory(directory);
   DateTime deadline=DateTime.UtcNow.AddSeconds(70);
   while((desktopCatalog==null || !webReady || desktopRun==null || nativeRunning) && DateTime.UtcNow<deadline) await Task.Delay(300);
   if(desktopRun==null)throw new Exception("Startup failed");
   int index=scenarioBox.Items.IndexOf("interop_recon");
   ReconControlMessage(scenarioBox.ComboBox.Handle,0x014E,new IntPtr(index),IntPtr.Zero);
   ReconControlMessage(scenarioBox.ComboBox.Handle,0x2111,new IntPtr(9<<16),scenarioBox.ComboBox.Handle);
   if(SelectedScenario!="interop_recon")throw new Exception("Native combo selection failed");
   string expected=await Task.Run(delegate{return desktopApi.GetDemoRun("interop_recon");});
   deadline=DateTime.UtcNow.AddSeconds(90);
   while(DateTime.UtcNow<deadline){
    await Task.Delay(400);
    if(desktopRunId!=expected || nativeRunning)continue;
    var frame=desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState()")) as Dictionary<string,object>;
    if(frame!=null && Convert.ToString(frame["runId"])==expected)break;
   }
   if(desktopRunId!=expected)throw new Exception("Real combo selection loaded "+desktopRunId+" instead of "+expected);
   await Task.Delay(1800);
   string oldId="";
   foreach(DesktopRunSummary row in desktopCatalog.Runs) {
    if(row.Scenario!="interop_recon" || row.Id==expected)continue;
    DesktopRunView old=await Task.Run(delegate{return desktopApi.GetRun(row.Id,null);});
    if(old.Tasks.Count>0 && old.Tasks[0].Position!=null && old.Tasks[0].Position.Length>=2 && Math.Abs(old.Tasks[0].Position[0]+95)>1){oldId=row.Id;break;}
   }
   if(oldId!="") {
    LoadRunAsync(oldId);deadline=DateTime.UtcNow.AddSeconds(20);
    while(desktopRunId!=oldId && DateTime.UtcNow<deadline)await Task.Delay(200);
    if(!reconRecordNotice.Visible)throw new Exception("Old recon record was not identified");
    desktopRefreshButton.PerformClick();deadline=DateTime.UtcNow.AddSeconds(30);
    while((desktopRunId!=expected || reconRecordNotice.Visible) && DateTime.UtcNow<deadline)await Task.Delay(200);
    if(desktopRunId!=expected || reconRecordNotice.Visible)throw new Exception("Refresh did not replace outdated demo");
    await Task.Delay(1800);
   }
   var evidence=new Dictionary<string,object>();
   evidence["oldRecordRefresh"] = oldId;
   foreach(int time in new[]{0,45,80}) {
    ReadMapScript("MarlDesktop.pause();MarlDesktop.fit('area');MarlDesktop.setTime("+time+")");await Task.Delay(500);
    var check=desktopJson.DeserializeObject(ReadMapScript(@"(function(){const b=state.run.replay.behaviors.find(b=>b.type==='recon');return {run:state.run.id,time:state.t,area:b.area,job:state.run.scenario.jobs[0].pos,bounds:bounds.slice(),center:b.area.reduce((p,v)=>[p[0]+v[0]/b.area.length,p[1]+v[1]/b.area.length],[0,0])}})()")) as Dictionary<string,object>;
    object[] center=(object[])check["center"];
    if(Math.Abs(Convert.ToDouble(center[0])+95)>.01 || Math.Abs(Convert.ToDouble(center[1])+145)>.01)throw new Exception("Actual rendered recon region is still at wrong location");
    object[] camera=(object[])check["bounds"];
    if(Math.Abs((Convert.ToDouble(camera[0])+Convert.ToDouble(camera[2]))/2+95)>.01 || Math.Abs((Convert.ToDouble(camera[1])+Convert.ToDouble(camera[3]))/2+145)>.01)throw new Exception("Task-area camera is not centered on the building group");
    evidence[time.ToString()]=check;
    await SaveNativeScreenshot(Path.Combine(directory,"recon-"+time+".png"));await Task.Delay(150);
   }
   string original="workbench_20261107_163453_777301";
   var historic=desktopApi.GetConfiguration("interop_recon",original);
   string originalBytes=Convert.ToBase64String(desktopApi.DownloadArtifact(original,"desktop_input.json"));
   nativeDraft=(Dictionary<string,object>)historic["draft"];
   string before=desktopRunId;RunSelectedScenario();deadline=DateTime.UtcNow.AddSeconds(120);
   while((nativeRunning || nativeRunPreparing || desktopRunId==before) && DateTime.UtcNow<deadline)await Task.Delay(300);
   if(desktopRunId==before)throw new Exception("Old-preset new run did not finish");
   string created=desktopRunId;
   var updated=(Dictionary<string,object>)desktopApi.GetConfiguration("interop_recon",created)["draft"];
   if(Convert.ToString(((Dictionary<string,object>)updated["request"])["objective"])!="exposure")throw new Exception("Objective was lost during preset refresh");
   if(Math.Abs(desktopRun.Tasks[0].Position[0]+95)>.01)throw new Exception("New exposure run still used old origin coordinates");
   if(originalBytes!=Convert.ToBase64String(desktopApi.DownloadArtifact(original,"desktop_input.json")))throw new Exception("Original historical input was modified");
   evidence["oldPresetNewRun"] = created;
   evidence["oldHistoryPreserved"] = true;
   string report=Convert.ToBase64String(desktopApi.DownloadArtifact(created,"report.json"));
   Documents.SelectedIndex=2;nativeHistorySearch.Clear();
   foreach(ListViewItem row in history.Items)row.Selected=Convert.ToString(row.Tag)==created;
   if(history.SelectedItems.Count!=1 || Convert.ToString(history.SelectedItems[0].Tag)!=created)throw new Exception("Wrong test record selected for deletion");
   Button delete=history.Parent.Controls.Find("DeleteRunRecord",true)[0] as Button;
   delete.PerformClick();deadline=DateTime.UtcNow.AddSeconds(25);
   while(nativeRecordBusy && DateTime.UtcNow<deadline)await Task.Delay(200);
   if(desktopCatalog.Runs.Exists(delegate(DesktopRunSummary row){return row.Id==created;}) || desktopRunId==created)throw new Exception("Deleted record remains in UI");
   string token=nativeLastDeletedToken;
   Button restore=history.Parent.Controls.Find("RestoreRunRecord",true)[0] as Button;
   restore.PerformClick();deadline=DateTime.UtcNow.AddSeconds(25);
   while(nativeRecordBusy && DateTime.UtcNow<deadline)await Task.Delay(200);
   if(!desktopCatalog.Runs.Exists(delegate(DesktopRunSummary row){return row.Id==created;}) || report!=Convert.ToBase64String(desktopApi.DownloadArtifact(created,"report.json")))throw new Exception("Restored record contents differ");
   evidence["nativeDeleteRestore"] = true;
   evidence["deletedToken"] = token;
   await Task.Delay(400);
   await SaveNativeScreenshot(Path.Combine(directory,"history-controls.png"));await Task.Delay(150);
   File.WriteAllText(Path.Combine(directory,"recon-verification.json"),desktopJson.Serialize(evidence));
  }
 }
}
