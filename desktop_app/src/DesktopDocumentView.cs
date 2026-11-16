using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    internal sealed class WrappingLegendPanel : FlowLayoutPanel
    {
        private bool sizing;
        internal WrappingLegendPanel()
        {
            Name="DesktopSceneLegend";Dock=DockStyle.Bottom;BackColor=Color.White;
            Padding=new Padding(5,2,5,2);WrapContents=false;AutoScroll=false;
        }
        protected override void OnLayout(LayoutEventArgs e)
        {
            if(sizing)return;
            sizing=true;
            try {
                // Keep one row, reducing spacing and label size on compact windows.
                float size=8.2f;
                while(true) {
                    int width=Padding.Horizontal;
                    foreach(Control item in Controls) {
                        Label label=item as Label;
                        if(label==null)label=item.Controls.OfType<Label>().FirstOrDefault();
                        if(label!=null && Math.Abs(label.Font.Size-size)>.05) {var old=label.Font;label.Font=new Font(old.FontFamily,size);old.Dispose();}
                        if(item is Panel && label!=null)item.Width=TextRenderer.MeasureText(label.Text,label.Font).Width+20;
                        width+=(item is Label?item.PreferredSize.Width:item.Width)+item.Margin.Horizontal;
                    }
                    if(width<=ClientSize.Width||size<=7.0f)break;
                    size-=.3f;
                }
                Height=28;base.OnLayout(e);
            } finally{sizing=false;}
        }
    }

    internal static class NativeDocumentView
    {
        internal static string NormalizeLines(string text)
        {return (text??"").Replace("\r\n","\n").Replace("\r","\n").Replace("\n","\r\n");}

        // Markdown tables become vertical records so a whole subtask can be read
        // at ordinary window widths, including long collaboration constraints.
        internal static string ReadingText(string source)
        {
            string[] lines=(source??"").Replace("\r\n","\n").Replace("\r","\n").Split('\n');
            var output=new List<string>();bool fenced=false;
            for(int i=0;i<lines.Length;i++)
            {
                string line=lines[i],trim=line.Trim();
                if(trim.StartsWith("```")){fenced=!fenced;output.Add(line);continue;}
                if(!fenced && trim.StartsWith("|") && i+1<lines.Length && Regex.IsMatch(lines[i+1].Trim(),@"^\|?[\s:\-|]+\|?$"))
                {
                    var headers=Cells(line);i+=2;int row=0;
                    while(i<lines.Length && lines[i].Trim().StartsWith("|"))
                    {
                        var cells=Cells(lines[i]);output.Add("记录 "+(++row));
                        for(int c=0;c<headers.Length;c++)output.Add(headers[c]+"："+(c<cells.Length?cells[c]:""));
                        output.Add("");i++;
                    }
                    i--;continue;
                }
                if(!fenced)line=Regex.Replace(line,@"^\s*#{1,6}\s+","").Replace("**","");
                output.Add(line);
            }
            return NormalizeLines(string.Join("\n",output));
        }
        private static string[] Cells(string line)
        {return Regex.Split(line.Trim().Trim('|'),@"(?<!\\)\|").Select(c=>c.Trim().Replace(@"\|","|")).ToArray();}

        internal static Control Create(string title,object value)
        {
            string raw=value is string?(string)value:DesktopApi.Pretty(value);
            string extension=System.IO.Path.GetExtension(title).ToLowerInvariant();
            bool markdown=extension==".md" || title=="单平台任务与约束" || raw.TrimStart().StartsWith("# ");
            string reading=markdown?ReadingText(raw):NormalizeLines(raw);
            if(extension==".json")try{reading=NormalizeLines(DesktopApi.Pretty(new System.Web.Script.Serialization.JavaScriptSerializer {MaxJsonLength=4*1024*1024}.DeserializeObject(raw)));}catch(ArgumentException){}
            var content=new TextBox {Name="NativeDocumentReading",Dock=DockStyle.Fill,ReadOnly=true,Multiline=true,WordWrap=true,
                ScrollBars=ScrollBars.Vertical,BorderStyle=BorderStyle.None,BackColor=Color.White,
                Font=new Font("Microsoft YaHei UI",10f),Text=reading};
            var body=new Panel {Dock=DockStyle.Fill,Padding=new Padding(12,8,12,8)};
            var toolbar=new FlowLayoutPanel {Dock=DockStyle.Top,Height=34,WrapContents=false};
            var source=new CheckBox {Text="显示原文",AutoSize=true,Name="NativeDocumentSource",Margin=new Padding(0,5,14,0)};
            var note=new Label {Text=markdown?"阅读视图按记录纵向排列；原文保留完整字段与换行。":"自动换行，可纵向滚动阅读。",AutoSize=true,Margin=new Padding(0,6,0,0),ForeColor=Color.SlateGray};
            source.CheckedChanged+=delegate {content.Text=source.Checked?NormalizeLines(raw):reading;content.SelectionStart=0;content.ScrollToCaret();};
            toolbar.Controls.Add(source);toolbar.Controls.Add(note);body.Controls.Add(content);body.Controls.Add(toolbar);
            return body;
        }
    }
}
