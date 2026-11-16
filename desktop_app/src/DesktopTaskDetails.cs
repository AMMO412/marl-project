using System;
using System.Drawing;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private static string TaskTypeCode(DesktopTask task)
        {
            switch(task.Type) {
                case "recon":return "T-RCN";
                case "blockade":return "T-SEC";
                case "patrol":return "T-PTL";
                case "hold":return "T-HLD";
                case "assault":return "T-ASL";
                default:return task.Type;
            }
        }
        private Control BuildTaskMembers()
        {
            var panel = new Panel { Name="TaskMembersPanel", Dock=DockStyle.Top, Padding=new Padding(10,3,10,5), Visible=false };
            var label = new Label { Text="分配平台", Dock=DockStyle.Top, Height=21, ForeColor=Blue };
            var text = new TextBox { Name="TaskMembersText", Dock=DockStyle.Fill, Multiline=true, WordWrap=true, ReadOnly=true,
                BorderStyle=BorderStyle.None, BackColor=Color.White, ScrollBars=ScrollBars.Vertical };
            panel.Controls.Add(text); panel.Controls.Add(label);
            Action refresh = delegate {
                var task = properties.SelectedObject as TaskProperties;
                panel.Visible=task!=null;
                if(task==null)return;
                text.Text=(task.Members??"").Replace(" · ","、");
                int height=TextRenderer.MeasureText(text.Text,text.Font,new Size(Math.Max(80,panel.Width-35),1000),TextFormatFlags.WordBreak|TextFormatFlags.TextBoxControl).Height;
                text.ScrollBars=height+7>120?ScrollBars.Vertical:ScrollBars.None;
                panel.Height=29+Math.Max(32,Math.Min(120,height+7));
            };
            properties.SelectedObjectsChanged+=delegate {refresh();};
            panel.SizeChanged+=delegate {refresh();};
            return panel;
        }
    }
}
