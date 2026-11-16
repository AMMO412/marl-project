using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        public async Task VerifyExecutionConfiguration(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(75);
            while(desktopApi==null||desktopCatalog==null){if(DateTime.UtcNow>deadline)throw new Exception("Mode verification backend not ready");await Task.Delay(200);}
            var config=await Task.Run(()=>desktopApi.GetConfiguration("interop_containment",null));
            var checks=new Dictionary<string,object>();
            using(var editor=new NativeRunConfiguration(desktopApi,desktopCatalog,config))
            {
                editor.ShowInTaskbar=false;editor.StartPosition=FormStartPosition.Manual;editor.Location=new Point(-15000,-15000);editor.Show();
                var mode=(ComboBox)editor.Controls.Find("NativeDemoMode",true)[0];
                var behavior=(CheckBox)editor.Controls.Find("NativeBehaviorEnabled",true)[0];
                var help=(Label)editor.Controls.Find("NativeModeHelp",true)[0];
                string[] keys={"normal","failure","timeout","kill","deviation"};
                for(int i=0;i<keys.Length;i++)
                {
                    mode.SelectedIndex=i;
                    var draft=editor.ReadDraft();var request=(Dictionary<string,object>)draft["request"];
                    bool expected=i!=2&&i!=4;
                    if(behavior.Checked!=expected || Convert.ToBoolean(request["behavior"])!=expected || help.Text.Length<35)throw new Exception("Mode policy mismatch: "+keys[i]);
                    var validated=await Task.Run(()=>desktopApi.ValidateDraft(draft));
                    var normalized=(Dictionary<string,object>)((Dictionary<string,object>)validated["draft"])["request"];
                    if(Convert.ToBoolean(normalized["behavior"])!=expected)throw new Exception("Native and backend mode disagree");
                    checks[keys[i]]=new {behavior=expected,description=help.Text};
                }
                mode.SelectedIndex=2;Application.DoEvents();
                using(var bitmap=new Bitmap(editor.Width,editor.Height)){editor.DrawToBitmap(bitmap,new Rectangle(0,0,editor.Width,editor.Height));bitmap.Save(Path.Combine(directory,"mode-configuration.png"));}
                editor.DialogResult=DialogResult.OK;editor.Close();
            }
            File.WriteAllText(Path.Combine(directory,"native-mode-verification.json"),desktopJson.Serialize(checks));
            await VerifyColleagueInputs(directory);
        }
    }
}
