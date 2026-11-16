using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private string ReadMapScript(string script)
        {
            return WaitMapTask(webView.CoreWebView2.ExecuteScriptAsync(script));
        }

        private string WaitMapTask(Task<string> task)
        {
            DateTime deadline = DateTime.UtcNow.AddSeconds(6);
            while (!task.IsCompleted && DateTime.UtcNow < deadline) { Application.DoEvents(); Thread.Sleep(15); }
            if (!task.IsCompleted) throw new TimeoutException("地图交互验证超时");
            return task.GetAwaiter().GetResult();
        }

        private void VerifyMapControls(string directory)
        {
            string script = @"(function(){
              const api=window.MarlDesktop;api.pause();api.fit('all');
              const full=api.getState().cameraBounds;
              const span=b=>b[2]-b[0];
              if(!full)throw Error('Missing camera bounds');
              api.zoom(1.3);const zoomed=api.getState().cameraBounds;
              const canvas=document.querySelector('#desktop-scene-host>canvas');
              canvas.dispatchEvent(new WheelEvent('wheel',{deltaY:-80,clientX:400,clientY:220,bubbles:true,cancelable:true}));
              const wheel=api.getState().cameraBounds;
              api.fit('area');const area=api.getState().cameraBounds;
              api.setLayer('grid',false);const gridOff=canvas.toDataURL();
              api.setLayer('grid',true);const gridOn=canvas.toDataURL();
              let ticks=0;const original=CanvasRenderingContext2D.prototype.fillText;
              CanvasRenderingContext2D.prototype.fillText=function(text){if(/^[XY] /.test(text))ticks++;return original.apply(this,arguments)};
              try{api.setLayer('grid',true)}finally{CanvasRenderingContext2D.prototype.fillText=original}
              api.fit('all');const restored=api.getState().cameraBounds;
              return {zoom:span(zoomed)<span(full),wheel:span(wheel)<span(zoomed),
                fullScene:span(full)>span(area),restored:Math.abs(span(restored)-span(full))<.001,
                gridChangesPixels:gridOff!==gridOn,xyTicks:ticks>2,full,area,
                onlyCanvas:document.querySelector('#desktop-scene-host').children.length===1};
            })()";
            Dictionary<string, object> result = desktopJson.DeserializeObject(ReadMapScript(script)) as Dictionary<string, object>;
            if (result == null) throw new InvalidOperationException("地图未返回验证结果");
            foreach (string key in new string[] { "zoom", "wheel", "fullScene", "restored", "gridChangesPixels", "xyTicks", "onlyCanvas" })
                if (!result.ContainsKey(key) || !Convert.ToBoolean(result[key])) throw new InvalidOperationException("地图验证失败：" + key);
            int loaded = 0;
            foreach (PictureBox picture in agentLegendPictures.Values) if (picture.Image != null) loaded++;
            if (loaded != 4) throw new InvalidOperationException("四类平台图标图例未载入");
            result["agentIconCount"] = loaded;
            Button fullButton = sceneInfo.Parent.Controls.Find("MapFullScene", true)[0] as Button;
            Button areaButton = sceneInfo.Parent.Controls.Find("MapTaskArea", true)[0] as Button;
            fullButton.PerformClick();
            double fullSpan = Convert.ToDouble(desktopJson.DeserializeObject(ReadMapScript("(function(){const b=MarlDesktop.getState().cameraBounds;return b[2]-b[0]})()")));
            areaButton.PerformClick();
            double areaSpan = Convert.ToDouble(desktopJson.DeserializeObject(ReadMapScript("(function(){const b=MarlDesktop.getState().cameraBounds;return b[2]-b[0]})()")));
            if (fullSpan <= areaSpan) throw new InvalidOperationException("原生全景/任务区域按钮未生效");
            result["nativeCameraButtons"] = true;
            Button startsButton = sceneInfo.Parent.Controls.Find("MapStarts", true)[0] as Button;
            startsButton.PerformClick();
            string startsCheck = ReadMapScript("(function(){const b=MarlDesktop.getState().cameraBounds;return state.run.replay.workers.every(w=>w.start[0]>=b[0]&&w.start[0]<=b[2]&&w.start[1]>=b[1]&&w.start[1]<=b[3])})()");
            if (!Convert.ToBoolean(desktopJson.DeserializeObject(startsCheck))) throw new InvalidOperationException("出生阵地没有包含所有平台起点");
            result["nativeStartsButton"] = true;
            areaButton.PerformClick();

            string beforePan = ReadMapScript("MarlDesktop.getState().cameraBounds");
            WaitMapTask(webView.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", "{\"type\":\"mousePressed\",\"x\":360,\"y\":200,\"button\":\"left\",\"buttons\":1,\"clickCount\":1}"));
            WaitMapTask(webView.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", "{\"type\":\"mouseMoved\",\"x\":420,\"y\":230,\"button\":\"left\",\"buttons\":1}"));
            WaitMapTask(webView.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", "{\"type\":\"mouseReleased\",\"x\":420,\"y\":230,\"button\":\"left\",\"buttons\":0,\"clickCount\":1}"));
            if (beforePan == ReadMapScript("MarlDesktop.getState().cameraBounds")) throw new InvalidOperationException("鼠标拖动没有平移地图");
            result["pointerPan"] = true;
            File.WriteAllText(Path.Combine(directory, "map-verification.json"), desktopJson.Serialize(result));
            ReadMapScript("window.MarlDesktop.fit('area')");
        }
    }
}
