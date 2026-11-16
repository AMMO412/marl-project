using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        [DllImport("user32.dll", EntryPoint = "SendMessageW")]
        private static extern IntPtr SendLayerMouse(IntPtr handle, int message, IntPtr wparam, IntPtr lparam);

        private void ClickLayerMenuItem(int index)
        {
            Button button = sceneInfo.Parent.Controls.Find("MapLayerMenu", true)[0] as Button;
            button.PerformClick(); Application.DoEvents();
            if (!sceneLayerMenu.Visible || sceneLayerMenu.IsDisposed) throw new InvalidOperationException("图层菜单未正常打开");
            Rectangle item = sceneLayerMenu.Items[index].Bounds;
            IntPtr point = new IntPtr(((item.Top + item.Height / 2) << 16) | (item.Left + item.Width / 2));
            SendLayerMouse(sceneLayerMenu.Handle, 0x0200, IntPtr.Zero, point);
            SendLayerMouse(sceneLayerMenu.Handle, 0x0201, new IntPtr(1), point);
            SendLayerMouse(sceneLayerMenu.Handle, 0x0202, IntPtr.Zero, point);
            Application.DoEvents();
            if (sceneLayerMenu.IsDisposed) throw new InvalidOperationException("关闭图层菜单时对象被提前释放");
            if (sceneLayerMenu.Visible) sceneLayerMenu.Close();
        }

        private void VerifyLayerMenus(string directory)
        {
            string[] keys = { "buildings", "boundary", "units", "planned", "targets", "grid", "threats", "trails" };
            bool[] initial = new bool[keys.Length];
            List<string> uiErrors = new List<string>();
            Dictionary<string, object> results = new Dictionary<string, object>();
            ThreadExceptionEventHandler errorHandler = delegate(object sender, ThreadExceptionEventArgs e) { uiErrors.Add(e.Exception.ToString()); };
            Application.ThreadException += errorHandler;
            try
            {
                ReadMapScript("MarlDesktop.pause();MarlDesktop.fit('all');MarlDesktop.setTime(Math.min(120,MarlDesktop.getState().duration-1))");
                for (int i = 0; i < keys.Length; i++) initial[i] = sceneLayerVisibility[i];
                for (int i = 1; i < keys.Length; i++)
                {
                    ReadMapScript("window.__layerBefore=document.querySelector('#desktop-scene-host>canvas').toDataURL();true");
                    bool before = sceneLayerVisibility[i];
                    ClickLayerMenuItem(i - 1);
                    bool after = sceneLayerVisibility[i];
                    if (after == before) throw new InvalidOperationException("原生图层菜单未改变勾选：" + keys[i]);
                    bool renderer = Convert.ToBoolean(desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState().layers[" + desktopJson.Serialize(keys[i]) + "]")));
                    if (renderer != after) throw new InvalidOperationException("图层勾选未同步到地图：" + keys[i]);
                    bool pixels = Convert.ToBoolean(desktopJson.DeserializeObject(ReadMapScript("document.querySelector('#desktop-scene-host>canvas').toDataURL()!==window.__layerBefore")));
                    if (!pixels) throw new InvalidOperationException("图层开关没有改变地图绘制：" + keys[i]);
                    ClickLayerMenuItem(i - 1);
                    if (sceneLayerVisibility[i] != initial[i]) throw new InvalidOperationException("第二次点击未恢复图层：" + keys[i]);
                    SetSceneLayer(i, !initial[i]);
                    if (((ToolStripMenuItem)sceneLayerMenu.Items[i - 1]).Checked != !initial[i]) throw new InvalidOperationException("图层状态未同步菜单：" + keys[i]);
                    SetSceneLayer(i, initial[i]);
                    results[keys[i]] = new { nativeMouseClick = true, checkStateSynced = true, pixelsChanged = true, reopened = true, programmaticSync = true };
                }
                Button button = sceneInfo.Parent.Controls.Find("MapLayerMenu", true)[0] as Button;
                for (int i = 0; i < 10; i++) { button.PerformClick(); Application.DoEvents(); sceneLayerMenu.Close(ToolStripDropDownCloseReason.Keyboard); Application.DoEvents(); }
                if (uiErrors.Count > 0) throw new InvalidOperationException(string.Join("\r\n", uiErrors.ToArray()));
                results["menuOpenCloseCycles"] = keys.Length * 2 + 10;
                results["unhandledUiExceptions"] = uiErrors.Count;
                File.WriteAllText(Path.Combine(directory, "layer-menu-verification.json"), desktopJson.Serialize(results));
            }
            finally
            {
                Application.ThreadException -= errorHandler;
                if (sceneLayerMenu.Visible) sceneLayerMenu.Close();
                for (int i = 0; i < keys.Length; i++) SetSceneLayer(i, initial[i]);
                ReadMapScript("delete window.__layerBefore;MarlDesktop.fit('area')");
            }
        }
    }
}
