using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
namespace MarlDesktopPreview {
 public sealed partial class MainWindow {
  private string nativeLastDeletedToken="";
  private string nativeOpenedRecordsDirectory="", nativeFolderError="";
  private bool nativeFolderOpening;
  private bool nativeSuppressAutoDemo, nativeRecordBusy;
  private async void DeleteSelectedRecord() {
   if(!HasNativeBackend() || nativeRecordBusy || history.SelectedItems.Count==0)return;
   string id=Convert.ToString(history.SelectedItems[0].Tag);
   nativeRecordBusy=true;
   try {
    SetNativeWorkState("正在移入已删除目录…",true);
    Dictionary<string,object> response=await Task.Run(delegate{return desktopApi.DeleteRecord(id);});
    nativeLastDeletedToken=Convert.ToString(response["token"]);
    if(desktopRunId==id) {
     ++desktopLoadVersion;pendingRunId="";desktopRunId="";desktopTaskId="";desktopRun=null;
     ClearNativePlaceholders();nativeFiles.Items.Clear();Bridge("clearRun()");
     SetTaskViewStatus("场景视图：当前记录已删除，可从运行记录选择其他轮次。");
    }
    DesktopCatalog catalog=await Task.Run(delegate{return desktopApi.GetCatalog();});
    nativeSuppressAutoDemo=true;try{ApplyCatalog(catalog);}finally{nativeSuppressAutoDemo=false;}
    SetNativeWorkState("已删除，可恢复",false);status.Text="记录已移入已删除目录："+id+"。点击“恢复上次删除”可撤销。";
   } catch(Exception ex){SetNativeWorkState("删除失败",false);NativeIssue("删除失败",ex);}
   finally{nativeRecordBusy=false;}
  }
  private async void RestoreLastRecord() {
   if(!HasNativeBackend() || nativeRecordBusy)return;
   if(nativeLastDeletedToken.Length==0){status.Text="本次会话没有可撤销的删除；历史已删除目录可从存储目录打开。";return;}
   nativeRecordBusy=true;
   try {
    string token=nativeLastDeletedToken;
    Dictionary<string,object> result=await Task.Run(delegate{return desktopApi.RestoreRecord(token);});
    nativeLastDeletedToken="";
    DesktopCatalog catalog=await Task.Run(delegate{return desktopApi.GetCatalog();});
    nativeSuppressAutoDemo=true;try{ApplyCatalog(catalog);}finally{nativeSuppressAutoDemo=false;}
    status.Text="已恢复记录："+result["id"];SetNativeWorkState("记录已恢复",false);
   }catch(Exception ex){NativeIssue("恢复失败",ex);}finally{nativeRecordBusy=false;}
  }
  private async void OpenRecordsFolder() {
   if(!HasNativeBackend() || nativeFolderOpening)return;
   nativeFolderOpening=true;nativeOpenedRecordsDirectory="";nativeFolderError="";
   try {
    Dictionary<string,object> info=await Task.Run(delegate{return desktopApi.StorageInfo();});
    string directory=Path.GetFullPath(Convert.ToString(info["directory"]));
    if(!Directory.Exists(directory))throw new DirectoryNotFoundException("运行记录目录不存在："+directory);
    using(var entries=Directory.EnumerateFileSystemEntries(directory).GetEnumerator()) { entries.MoveNext(); }
    nativeOpenedRecordsDirectory=directory;
    status.Text="运行记录目录："+directory;
    ShowNativeStorageDirectory(directory);
   }catch(Exception ex){nativeFolderError=ex.Message;NativeIssue("打开目录失败",ex);}
   finally{nativeFolderOpening=false;}
  }
 }
}
