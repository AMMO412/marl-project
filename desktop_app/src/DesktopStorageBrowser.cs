using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;
namespace MarlDesktopPreview {
 public sealed partial class MainWindow {
  private void ShowNativeStorageDirectory(string root) {
   root=Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
   using(Form browser=new Form {Name="NativeStorageBrowser",Text="运行记录存储目录",Size=new Size(1000,640),MinimumSize=new Size(700,420),StartPosition=FormStartPosition.CenterParent,Font=Font,BackColor=Color.White}) {
    TextBox address=new TextBox {Name="StorageAddress",Dock=DockStyle.Fill,ReadOnly=true,BackColor=Color.White};
    FlowLayoutPanel tools=new FlowLayoutPanel {Dock=DockStyle.Top,Height=39,Padding=new Padding(7)};
    Button up=StandardButton("上一级",75),refresh=StandardButton("刷新",65),copy=StandardButton("复制当前路径",110),copyFile=StandardButton("复制所选路径",110);
    up.Name="StorageParent";refresh.Name="StorageRefresh";tools.Controls.AddRange(new Control[]{up,refresh,copy,copyFile});
    Panel pathRow=new Panel {Dock=DockStyle.Top,Height=32,Padding=new Padding(9,3,9,5)};pathRow.Controls.Add(address);
    ListView entries=new ListView {Name="StorageEntries",Dock=DockStyle.Fill,View=View.Details,FullRowSelect=true,MultiSelect=false,HideSelection=false,BorderStyle=BorderStyle.None,BackColor=Color.White};
    entries.Columns.Add("名称",410);entries.Columns.Add("类型",115);entries.Columns.Add("大小",110);entries.Columns.Add("修改时间",190);
    Label note=new Label {Dock=DockStyle.Bottom,Height=35,Padding=new Padding(10,8,0,0),Text="双击进入文件夹或预览文本；删除与恢复请使用主窗口“运行记录”中的按钮。",ForeColor=Color.SlateGray};
    Action<string> navigate=null;
    navigate=delegate(string target) {
     try {
      string directory=Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar);
      if(!directory.Equals(root,StringComparison.OrdinalIgnoreCase) && !directory.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("仅浏览当前运行记录存储目录。");
      DirectoryInfo info=new DirectoryInfo(directory);FileSystemInfo[] children=info.GetFileSystemInfos().OrderBy(delegate(FileSystemInfo item){return item is DirectoryInfo?0:1;}).ThenBy(delegate(FileSystemInfo item){return item.Name;},StringComparer.OrdinalIgnoreCase).ToArray();
      entries.BeginUpdate();entries.Items.Clear();
      foreach(FileSystemInfo item in children) {
       bool folder=item is DirectoryInfo;FileInfo file=item as FileInfo;
       string size=folder?"—":file.Length>=1024*1024?(file.Length/1024d/1024d).ToString("0.0")+" MB":file.Length>=1024?(file.Length/1024d).ToString("0.0")+" KB":file.Length+" B";
       entries.Items.Add(new ListViewItem(new[]{item.Name,folder?"文件夹":item.Extension,size,item.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")}){Tag=item.FullName,ForeColor=folder?Color.FromArgb(31,111,195):Color.FromArgb(60,75,95)});
      }
      entries.EndUpdate();address.Text=directory;up.Enabled=!directory.Equals(root,StringComparison.OrdinalIgnoreCase);note.Text=children.Length+" 项 · 双击进入文件夹或预览文本；删除与恢复请使用主窗口运行记录按钮。";
     } catch(Exception ex) { entries.EndUpdate();MessageBox.Show(browser,ex.Message,"目录读取失败",MessageBoxButtons.OK,MessageBoxIcon.Warning); }
    };
    up.Click+=delegate { if(up.Enabled)navigate(Directory.GetParent(address.Text).FullName); };
    refresh.Click+=delegate { navigate(address.Text); };
    copy.Click+=delegate { try{Clipboard.SetText(address.Text);}catch(Exception ex){MessageBox.Show(browser,ex.Message);} };
    copyFile.Click+=delegate { if(entries.SelectedItems.Count>0)try{Clipboard.SetText(Convert.ToString(entries.SelectedItems[0].Tag));}catch(Exception ex){MessageBox.Show(browser,ex.Message);} };
    entries.DoubleClick+=delegate {
     if(entries.SelectedItems.Count==0)return;string selected=Convert.ToString(entries.SelectedItems[0].Tag);
     if(Directory.Exists(selected)){navigate(selected);return;}
     string extension=Path.GetExtension(selected).ToLowerInvariant();
     if(!new[]{".json",".jsonl",".txt",".log",".csv",".md",".html",".xml"}.Contains(extension)){MessageBox.Show(browser,"此类型不提供文本预览，可复制所选路径后在系统中打开。","文件信息");return;}
     try {
      string text;using(StreamReader reader=new StreamReader(selected,Encoding.UTF8,true)){char[] chars=new char[1024*1024];int length=reader.ReadBlock(chars,0,chars.Length);text=new string(chars,0,length);if(!reader.EndOfStream)text+="\r\n\r\n文件较大，已截取前段预览。";}
      using(Form preview=new Form {Text=Path.GetFileName(selected),Size=new Size(850,600),StartPosition=FormStartPosition.CenterParent,Font=Font}) {
       preview.Controls.Add(new TextBox {Dock=DockStyle.Fill,Multiline=true,ReadOnly=true,WordWrap=false,ScrollBars=ScrollBars.Both,Font=new Font("Consolas",10),Text=text,BackColor=Color.White});preview.ShowDialog(browser);
      }
     }catch(Exception ex){MessageBox.Show(browser,ex.Message,"预览失败");}
    };
    browser.Controls.Add(entries);browser.Controls.Add(pathRow);browser.Controls.Add(tools);browser.Controls.Add(note);
    navigate(root);browser.ShowDialog(this);
   }
  }
 }
}
