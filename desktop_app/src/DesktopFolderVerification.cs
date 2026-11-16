using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
namespace MarlDesktopPreview {
 public sealed partial class MainWindow {
  public async Task VerifyRecordsFolder(string directory) {
   Directory.CreateDirectory(directory);DateTime limit=DateTime.UtcNow.AddSeconds(60);
   while(desktopApi==null && DateTime.UtcNow<limit)await Task.Delay(200);
   if(desktopApi==null)throw new Exception("Backend not ready");
   Documents.SelectedIndex=2;
   Button button=history.Parent.Controls.Find("OpenRecordsFolder",true)[0] as Button;button.PerformClick();
   Form browser=null;limit=DateTime.UtcNow.AddSeconds(15);
   while(DateTime.UtcNow<limit && browser==null){await Task.Delay(200);foreach(Form candidate in Application.OpenForms)if(candidate.Name=="NativeStorageBrowser")browser=candidate;}
   if(browser==null)throw new Exception("Native storage browser did not open: "+nativeFolderError);
   TextBox address=browser.Controls.Find("StorageAddress",true)[0] as TextBox;
   ListView entries=browser.Controls.Find("StorageEntries",true)[0] as ListView;
   string root=nativeOpenedRecordsDirectory.TrimEnd(Path.DirectorySeparatorChar);
   if(address.Text!=root || entries.Items.Count!=Directory.GetFileSystemEntries(root).Length)throw new Exception("Folder entries differ from actual storage");
   bool navigated=false;
   foreach(ListViewItem item in entries.Items)if(Directory.Exists(Convert.ToString(item.Tag))){
    item.Selected=true;
    typeof(ListView).GetMethod("OnDoubleClick",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(entries,new object[]{EventArgs.Empty});
    if(address.Text==root)throw new Exception("Folder double click did not navigate");
    ((Button)browser.Controls.Find("StorageParent",true)[0]).PerformClick();
    if(address.Text!=root)throw new Exception("Return to storage root failed");navigated=true;break;
   }
   ((Button)browser.Controls.Find("StorageRefresh",true)[0]).PerformClick();
   using(Bitmap image=new Bitmap(browser.Width,browser.Height)){browser.DrawToBitmap(image,new Rectangle(0,0,browser.Width,browser.Height));image.Save(Path.Combine(directory,"storage-browser.png"),ImageFormat.Png);}
   var evidence=new Dictionary<string,object>{{"nativeButton",true},{"nativeDirectoryWindow",true},{"directory",root},{"actualEntries",entries.Items.Count},{"subfolderAndParent",navigated}};
   browser.Close();await Task.Delay(150);
   if(nativeFolderError.Length>0)throw new Exception(nativeFolderError);
   File.WriteAllText(Path.Combine(directory,"folder-verification.json"),desktopJson.Serialize(evidence));
  }
 }
}
