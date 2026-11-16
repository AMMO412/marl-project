using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        public async Task VerifyColleagueInputs(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(70);
            while(desktopApi==null||desktopCatalog==null){if(DateTime.UtcNow>deadline)throw new Exception("Backend not ready");await Task.Delay(250);}
            var results=new Dictionary<string,object>();
            foreach(string key in new[]{"interop_containment","interop_hold","interop_patrol","interop_recon","interop_asl"}){
                var config=await Task.Run(()=>desktopApi.GetConfiguration(key,null));var draft=(Dictionary<string,object>)config["draft"];
                string original=NativeInputData.Json.Serialize(draft);
                using(var editor=new NativeInputEditor(desktopApi,draft,true)){
                    editor.ShowInTaskbar=false;editor.StartPosition=FormStartPosition.Manual;editor.Location=new Point(-15000,-15000);editor.Show();
                    var tabs=(TabControl)editor.Controls.Find("NativeInputTabs",true)[0];tabs.SelectedIndex=1;
                    var grid=(DataGridView)editor.Controls.Find("NativeInputUnits",true)[0];
                    if(grid.Rows.Count!=50)throw new Exception("Initial fleet count: "+key);
                    if(original!=NativeInputData.Json.Serialize(editor.Draft))throw new Exception("No-op changed inputs: "+key);
                    var rows=(IList)((Dictionary<string,object>)((Dictionary<string,object>)editor.Draft["formation"])["formation"])["units"];
                    var first=(Dictionary<string,object>)rows[0];string id=Convert.ToString(first["unit_id"]);
                    // The status button must edit the actual saved input, not a UI-only flag.
                    var toggle=(Button)tabs.TabPages[1].Controls.Find("NativeInputsToggle",true)[0];toggle.PerformClick();
                    if(Convert.ToString(first["status"])!="OFFLINE")throw new Exception("Platform toggle failed");
                    if(original!=NativeInputData.Json.Serialize(draft))throw new Exception("Original input was mutated");
                    ((Button)tabs.TabPages[1].Controls.Find("NativeInputsUndo",true)[0]).PerformClick();
                    if(original!=NativeInputData.Json.Serialize(editor.Draft))throw new Exception("Undo did not restore input");
                    Exception dialogError=null;bool edited=false;
                    using(var timer=new Timer {Interval=150}){
                        timer.Tick+=delegate {var fields=Application.OpenForms.Cast<Form>().OfType<NativeFieldEditor>().FirstOrDefault();if(fields==null)return;timer.Stop();
                            try {
                                var fieldGrid=(DataGridView)fields.Controls.Find("NativeFieldGrid",true)[0];
                                var robot=fieldGrid.Rows.Cast<DataGridViewRow>().Single(r=>Convert.ToString(r.Cells[0].Value).EndsWith("(robot_id)"));
                                object number=robot.Cells[1].Value;robot.Cells[1].Value="invalid-number";
                                ((Button)fields.Controls.Find("NativeFieldSave",true)[0]).PerformClick();
                                if(fields.DialogResult==DialogResult.OK)throw new Exception("Invalid number accepted");robot.Cells[1].Value=number;
                                fieldGrid.Rows.Cast<DataGridViewRow>().Single(r=>Convert.ToString(r.Cells[0].Value).EndsWith("(status)")).Cells[1].Value="OFFLINE";
                                var tree=(TreeView)fields.Controls.Find("NativeFieldTree",true)[0];tree.SelectedNode=tree.Nodes[0].Nodes.Cast<TreeNode>().Single(n=>n.Text.EndsWith("(position)"));
                                var x=fieldGrid.Rows.Cast<DataGridViewRow>().Single(r=>Convert.ToString(r.Cells[0].Value).EndsWith("(x)"));x.Cells[1].Value="1.25";
                                ((Button)fields.Controls.Find("NativeFieldSave",true)[0]).PerformClick();edited=fields.DialogResult==DialogResult.OK;
                            }catch(Exception ex){dialogError=ex;fields.DialogResult=DialogResult.Cancel;fields.Close();}
                        };timer.Start();((Button)tabs.TabPages[1].Controls.Find("NativeInputsEdit",true)[0]).PerformClick();
                    }
                    if(dialogError!=null)throw dialogError;if(!edited)throw new Exception("Native field dialog failed");
                    rows=(IList)((Dictionary<string,object>)((Dictionary<string,object>)editor.Draft["formation"])["formation"])["units"];first=(Dictionary<string,object>)rows[0];
                    if(Convert.ToString(first["status"])!="OFFLINE"||Convert.ToDouble(((Dictionary<string,object>)first["position"])["x"])!=1.25)throw new Exception("Field changes not saved");
                    var checkedDraft=await Task.Run(()=>desktopApi.ValidateDraft(editor.Draft));if(!Convert.ToBoolean(checkedDraft["valid"]))throw new Exception("Edited inputs invalid");
                    if(key=="interop_recon"){
                        using(var bitmap=new Bitmap(editor.Width,editor.Height)){editor.DrawToBitmap(bitmap,new Rectangle(0,0,editor.Width,editor.Height));bitmap.Save(Path.Combine(directory,"native-platform-editor.png"),ImageFormat.Png);}
                        using(var fields=new NativeFieldEditor(first,"编辑平台输入")){fields.ShowInTaskbar=false;fields.StartPosition=FormStartPosition.Manual;fields.Location=new Point(-15000,-15000);fields.Show();using(var bitmap=new Bitmap(fields.Width,fields.Height)){fields.DrawToBitmap(bitmap,new Rectangle(0,0,fields.Width,fields.Height));bitmap.Save(Path.Combine(directory,"native-platform-fields.png"),ImageFormat.Png);}fields.DialogResult=DialogResult.Cancel;fields.Close();}
                    }
                    // Removing a task must be undoable with every nested parameter restored.
                    string changed=NativeInputData.Json.Serialize(editor.Draft);tabs.SelectedIndex=0;
                    ((Button)tabs.TabPages[0].Controls.Find("NativeInputsRemove",true)[0]).PerformClick();
                    ((Button)tabs.TabPages[0].Controls.Find("NativeInputsUndo",true)[0]).PerformClick();
                    if(changed!=NativeInputData.Json.Serialize(editor.Draft))throw new Exception("Task remove/undo lost fields");
                    int taskCount=((IList)((Dictionary<string,object>)editor.Draft["message"])["tasks"]).Count;
                    using(var timer=new Timer {Interval=100}){
                        timer.Tick+=delegate {var fields=Application.OpenForms.Cast<Form>().OfType<NativeFieldEditor>().FirstOrDefault();if(fields==null)return;timer.Stop();((Button)fields.Controls.Find("NativeFieldSave",true)[0]).PerformClick();};
                        timer.Start();((Button)tabs.TabPages[0].Controls.Find("NativeInputsDuplicate",true)[0]).PerformClick();
                    }
                    var tasks=(IList)((Dictionary<string,object>)editor.Draft["message"])["tasks"];
                    if(tasks.Count!=taskCount+1||tasks.Cast<Dictionary<string,object>>().Select(t=>Convert.ToString(t["task_id"])).Distinct().Count()!=tasks.Count)throw new Exception("Task copy did not create a unique input");
                    ((Button)tabs.TabPages[0].Controls.Find("NativeInputsUndo",true)[0]).PerformClick();
                    if(changed!=NativeInputData.Json.Serialize(editor.Draft))throw new Exception("Task copy/undo lost fields");
                    if(key=="interop_recon")using(var fields=new NativeFieldEditor(((IList)((Dictionary<string,object>)editor.Draft["message"])["tasks"])[0],"编辑任务 · 区域顶点")){
                        fields.ShowInTaskbar=false;fields.StartPosition=FormStartPosition.Manual;fields.Location=new Point(-15000,-15000);fields.Show();
                        string before=NativeInputData.Json.Serialize(fields.Value);var tree=(TreeView)fields.Controls.Find("NativeFieldTree",true)[0];
                        var target=tree.Nodes[0].Nodes.Cast<TreeNode>().Single(n=>n.Text.EndsWith("(target)"));tree.SelectedNode=target.Nodes.Cast<TreeNode>().Single(n=>n.Text.EndsWith("(area)"));
                        ((Button)fields.Controls.Find("NativeFieldDuplicate",true)[0]).PerformClick();var vertices=(IList)tree.SelectedNode.Tag;if(vertices.Count!=5)throw new Exception("Coordinate append failed");
                        var fieldGrid=(DataGridView)fields.Controls.Find("NativeFieldGrid",true)[0];fieldGrid.CurrentCell=fieldGrid.Rows[4].Cells[0];
                        ((Button)fields.Controls.Find("NativeFieldRemove",true)[0]).PerformClick();if(before!=NativeInputData.Json.Serialize(fields.Value))throw new Exception("Coordinate order changed");
                        using(var bitmap=new Bitmap(fields.Width,fields.Height)){fields.DrawToBitmap(bitmap,new Rectangle(0,0,fields.Width,fields.Height));bitmap.Save(Path.Combine(directory,"native-task-coordinates.png"),ImageFormat.Png);}
                        fields.DialogResult=DialogResult.Cancel;fields.Close();
                    }
                    // Exercise the actual asynchronous apply button and backend validation.
                    ((Button)editor.Controls.Find("NativeInputsSave",true)[0]).PerformClick();deadline=DateTime.UtcNow.AddSeconds(35);
                    while(editor.DialogResult!=DialogResult.OK&&DateTime.UtcNow<deadline)await Task.Delay(100);
                    if(editor.DialogResult!=DialogResult.OK)throw new Exception("Apply did not finish");
                    results[key]=new{platformCount=50,roundTrip=true,originalUnchanged=true,toggleAndUndo=true,nestedCoordinateEdit=true,invalidNumberRetained=true,taskDeleteUndo=true,taskCopyUniqueIdAndUndo=true,backendValidationAndApply=true,unit=id};
                }
            }
            var parentConfig=await Task.Run(()=>desktopApi.GetConfiguration("interop_recon",null));
            using(var parent=new NativeRunConfiguration(desktopApi,desktopCatalog,parentConfig)){
                parent.ShowInTaskbar=false;parent.StartPosition=FormStartPosition.Manual;parent.Location=new Point(-15000,-15000);parent.Show();
                Application.DoEvents();
                var configTabs=(TabControl)parent.Controls.Find("NativeConfigurationTabs",true)[0];configTabs.SelectedIndex=3;
                var threatGrid=(DataGridView)parent.Controls.Find("NativeThreatGrid",true)[0];
                if(threatGrid.Rows.Count<1)throw new Exception("Threat editor did not load the template threat");
                var threatSummary=(Label)parent.Controls.Find("NativeThreatSummary",true)[0];
                foreach(string numericColumn in new[]{"intensity","center_x","center_y","width","height"}){
                    object originalNumber=threatGrid.Rows[0].Cells[numericColumn].Value;
                    threatGrid.Rows[0].Cells[numericColumn].Value=null;Application.DoEvents();
                    if(!threatSummary.Text.Contains("编辑尚未完成"))throw new Exception("Clearing "+numericColumn+" did not remain editable");
                    threatGrid.Rows[0].Cells[numericColumn].Value=originalNumber;Application.DoEvents();
                }
                threatGrid.Rows[0].Cells["applies_to"].Value="空地";
                threatGrid.Rows[0].Cells["intensity"].Value="0.85";
                threatGrid.Rows[0].Cells["center_x"].Value="0";
                threatGrid.Rows[0].Cells["center_y"].Value="-20";
                threatGrid.Rows[0].Cells["width"].Value="60";
                threatGrid.Rows[0].Cells["height"].Value="70";
                Application.DoEvents();
                if(!threatSummary.Text.Contains("配置允许运行")||!threatSummary.Text.Contains("对地"))
                    throw new Exception("Initial-position threat overlap warning was not shown");
                ((Button)parent.Controls.Find("NativeThreatDuplicate",true)[0]).PerformClick();
                if(threatGrid.Rows.Count!=2)throw new Exception("Threat duplicate did not create a second zone");
                var read=parent.ReadDraft();var units=(IList)((Dictionary<string,object>)((Dictionary<string,object>)read["formation"])["formation"])["units"];
                if(units.Count!=50)throw new Exception("Threat edit changed the fleet input");
                var constraints=(IList)((Dictionary<string,object>)read["formation"])["constraints"];
                var threats=constraints.Cast<object>().Select(x=>(Dictionary<string,object>)x).Where(x=>Convert.ToString(x["type"])=="threat").ToList();
                if(threats.Count!=2||Convert.ToString(threats[0]["applies_to"])!="all"||Math.Abs(Convert.ToDouble(threats[0]["intensity"])-.85)>.0001)throw new Exception("Threat fields did not round-trip");
                var threatChecked=await Task.Run(()=>desktopApi.ValidateDraft(read));if(!Convert.ToBoolean(threatChecked["valid"]))throw new Exception("Edited threats are invalid");
                using(var bitmap=new Bitmap(parent.Width,parent.Height)){parent.DrawToBitmap(bitmap,new Rectangle(0,0,parent.Width,parent.Height));bitmap.Save(Path.Combine(directory,"configuration-editor-entry.png"),ImageFormat.Png);}
                var overlap=threatChecked["summary"] as Dictionary<string,object>;
                var overlapSummary=overlap!=null?overlap["initial_threat_overlap"] as Dictionary<string,object>:null;
                if(overlapSummary==null||!Convert.ToBoolean(overlapSummary["allowed"])||Convert.ToInt32(overlapSummary["total"])<1)
                    throw new Exception("Backend did not report the non-blocking initial threat overlap");
                using(var bitmap=new Bitmap(parent.Width,parent.Height)){parent.DrawToBitmap(bitmap,new Rectangle(0,0,parent.Width,parent.Height));bitmap.Save(Path.Combine(directory,"configuration-threat-overlap.png"),ImageFormat.Png);}
                parent.DialogResult=DialogResult.OK;parent.Close();results["configurationIntegration"]=new{threatEditorLoads=true,editsWriteBackToJson=true,blankNumberAllowed=true,threatRows=threats.Count,threatScopeRoundTrip=true,threatValidation=true,initialOverlapWarning=true,initialOverlapAllowed=true};
            }
            File.WriteAllText(Path.Combine(directory,"native-inputs-verification.json"),desktopJson.Serialize(results));
        }
        public async Task VerifyColleaguePlayback(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(70);
            while((desktopCatalog==null||desktopRun==null||!webReady)&&DateTime.UtcNow<deadline)await Task.Delay(250);
            if(desktopRun==null)throw new Exception("Backend not ready");var results=new Dictionary<string,object>();
            foreach(string key in new[]{"interop_containment","interop_hold","interop_patrol","interop_recon","interop_asl"}){
                scenarioBox.SelectedItem=key;OpenSelectedScenarioDemo();deadline=DateTime.UtcNow.AddSeconds(120);bool ready=false;
                while(DateTime.UtcNow<deadline){await Task.Delay(300);if(desktopRun==null||desktopRun.Scenario!=key||nativeRunning)continue;
                    var frame=desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState()")) as Dictionary<string,object>;
                    if(frame!=null&&Convert.ToString(frame["runId"])==desktopRunId){ready=true;break;}}
                if(!ready)throw new Exception("Scene not ready: "+key);await Task.Delay(1000);
                string script=@"(()=>{MarlDesktop.pause();const before=JSON.stringify(state.run.replay),original=window.ReplayPose;let candidate;
                    for(const w of state.run.replay.workers){for(let i=1;i<w.samples.length;i++){const a=w.samples[i-1],b=w.samples[i];
                    if(a.command===b.command&&b.t>a.t&&['accepted','progress'].includes(a.status)&&Number.isFinite(a.yaw)&&Number.isFinite(b.yaw)&&Math.abs(a.yaw-b.yaw)>1e-5){candidate={a,b};break;}}if(candidate)break;}
                    if(!candidate)throw Error('No recorded turn');const t=(candidate.a.t+candidate.b.t)/2;let calls=0,matched=false;
                    window.ReplayPose={between(a,b,time){const result=original.between(a,b,time);calls++;
                    if(a.t===candidate.a.t&&b.t===candidate.b.t&&a.command===candidate.a.command&&Math.abs(time-t)<1e-6){
                    const delta=Math.atan2(Math.sin(b.yaw-a.yaw),Math.cos(b.yaw-a.yaw));matched=Math.abs(result.yaw-a.yaw-delta/2)<1e-8;}return result;}};
                    try{const c=document.querySelector('#desktop-scene-host>canvas');if(c.id==='ck-canvas'){ContainmentPage.syncTime(t);ContainmentPage.draw();}
                    else if(c.id==='hl-canvas'){HoldPage.syncTime(t);HoldPage.draw();}else setTime(t);
                    return {calls,matched,recordingUnchanged:before===JSON.stringify(state.run.replay),canvas:c.id,time:t,run:state.run.id};}
                    finally{window.ReplayPose=original;}})()";
                var check=desktopJson.DeserializeObject(ReadMapScript(script)) as Dictionary<string,object>;
                if(check==null||Convert.ToInt32(check["calls"])==0||!Convert.ToBoolean(check["matched"])||!Convert.ToBoolean(check["recordingUnchanged"]))throw new Exception("Pose interpolation not used by scene: "+key+" "+desktopJson.Serialize(check));
                results[key]=check;
            }
            File.WriteAllText(Path.Combine(directory,"playback-interpolation-verification.json"),desktopJson.Serialize(results));
        }
    }
}
