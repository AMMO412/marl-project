using System;
using System.Collections.Generic;
using System.IO;

namespace MarlDesktopPreview
{
    // A live window owns its slot through an OS file lease. Slots are reused after
    // exit, so parallel windows do not share a browser process or grow a new cache
    // directory on every launch. Run records are stored elsewhere.
    internal sealed class WebViewProfileLease : IDisposable
    {
        private FileStream lease;
        internal string DirectoryPath { get; private set; }
        private WebViewProfileLease(string path, FileStream lease) { DirectoryPath=path;this.lease=lease; }

        internal static WebViewProfileLease Acquire(HashSet<string> excluded)
        {
            string[] roots = {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"MARL界面预览","WebView2Profiles"),
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"data","webview2-profiles"),
                Path.Combine(Path.GetTempPath(),"MARL界面预览","WebView2Profiles")
            };
            Exception last=null;
            foreach(string root in roots)
            {
                try { Directory.CreateDirectory(root); }
                catch(UnauthorizedAccessException ex){last=ex;continue;}
                catch(IOException ex){last=ex;continue;}
                for(int slot=0;slot<32;slot++)
                {
                    string directory=Path.Combine(root,"slot-"+slot.ToString("00")), profile=Path.Combine(directory,"profile");
                    if(excluded.Contains(profile))continue;
                    FileStream handle=null;
                    try {
                        Directory.CreateDirectory(directory);
                        handle=new FileStream(Path.Combine(directory,"window.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
                        Directory.CreateDirectory(profile);
                        return new WebViewProfileLease(profile,handle);
                    }
                    catch(UnauthorizedAccessException ex){last=ex;if(handle!=null)handle.Dispose();break;}
                    catch(IOException ex){last=ex;if(handle!=null)handle.Dispose();}
                }
            }
            throw new IOException("无法分配可写的地图浏览器缓存目录。",last);
        }
        public void Dispose() { if(lease!=null){lease.Dispose();lease=null;} }
    }
}
