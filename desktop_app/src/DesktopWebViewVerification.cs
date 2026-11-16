using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        public async Task VerifyWebViewStartup(string directory)
        {
            Directory.CreateDirectory(directory);DateTime deadline=DateTime.UtcNow.AddSeconds(70);
            while(desktopApi==null&&DateTime.UtcNow<deadline)await Task.Delay(150);
            if(desktopApi==null)throw new Exception("Backend did not connect");
            // Calling the entry again while initialization is pending must not
            // create two controllers on the same WinForms control.
            InitializeWebView(desktopApi.BaseUrl);
            while(!webReady&&DateTime.UtcNow<deadline)await Task.Delay(200);
            if(!webReady||webProfile==null||webView.CoreWebView2==null){
                string page=webView.CoreWebView2==null?"no controller":await webView.CoreWebView2.ExecuteScriptAsync("({url:location.href,title:document.title,bridge:typeof window.MarlDesktop,errors:window.__nativeStartupErrors,text:document.body.innerText.slice(0,300)})");
                throw new Exception("WebView did not initialize; initializing="+webInitializing+" core="+(webView.CoreWebView2!=null)+" status="+taskViewStatus.Text+" page="+page+" log="+log.Text);
            }
            string profile=webProfile.DirectoryPath;
            if(!string.Equals(Path.GetFullPath(webView.CoreWebView2.Environment.UserDataFolder),Path.GetFullPath(profile),StringComparison.OrdinalIgnoreCase))throw new Exception("Runtime did not use the leased profile");
            bool locked=false;
            try{using(var other=new FileStream(Path.Combine(Path.GetDirectoryName(profile),"window.lock"),FileMode.Open,FileAccess.ReadWrite,FileShare.None)){} }
            catch(IOException){locked=true;}
            if(!locked)throw new Exception("Profile lease is not exclusive");
            uint browser=webView.CoreWebView2.BrowserProcessId;
            InitializeWebView(desktopApi.BaseUrl);await Task.Delay(500);
            if(webProfile.DirectoryPath!=profile||webView.CoreWebView2.BrowserProcessId!=browser)throw new Exception("Reentry replaced a running browser");
            File.WriteAllText(Path.Combine(directory,"ready.json"),desktopJson.Serialize(new { profile=profile,browser=browser,host=System.Diagnostics.Process.GetCurrentProcess().Id,exclusiveLease=locked,initializationReentry=true }));
            // Keep both test hosts alive together so cross-process allocation is tested.
            await Task.Delay(7000);
            await SaveNativeScreenshot(Path.Combine(directory,"startup.png"));
        }
    }
}
