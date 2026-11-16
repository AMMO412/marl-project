using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private readonly bool[] sceneLayerVisibility = { true, true, true, false, true, true, true, true };
        private readonly string[] sceneLayerLabels = { "建筑轮廓", "任务区域与边界", "平台与任务点", "规划路径", "被观察目标", "网格坐标（X / Y）", "威胁区", "运动轨迹" };
        private readonly Dictionary<string, PictureBox> agentLegendPictures = new Dictionary<string, PictureBox>();
        private ToolStripStatusLabel sceneCoordinates;
        private ContextMenuStrip sceneLayerMenu;
        private bool syncingLayerMenu;

        private Panel reconRecordNotice;
        private Label reconRecordText;
        private void UpdateReconRecordNotice() {
            if (reconRecordNotice == null || desktopRun == null) return;
            DesktopTask task=desktopRun.Tasks.Count>0 ? desktopRun.Tasks[0] : null;
            bool old=desktopRun.Scenario=="interop_recon" && task!=null && task.Position!=null && task.Position.Length>=2 && (Math.Abs(task.Position[0]+95)>.01 || Math.Abs(task.Position[1]+145)>.01);
            reconRecordNotice.Visible=old;
            if(old)reconRecordText.Text="本轮侦察中心 ("+task.Position[0].ToString("0.#")+", "+task.Position[1].ToString("0.#")+")，与当前建筑群演示不同。历史输入保持原样。";
        }

        private void BuildNativeSceneControls()
        {
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Right, Width = 414, Height = 32, WrapContents = false, Padding = new Padding(2, 2, 0, 0) };
            Button plus = StandardButton("+", 29), minus = StandardButton("−", 29), all = StandardButton("全景", 55), area = StandardButton("任务区域", 79), layers = StandardButton("图层 ▾", 71), starts = StandardButton("出发阵地", 80);
            actions.Name = "SceneMapActions";
            plus.Name = "MapZoomIn"; minus.Name = "MapZoomOut"; all.Name = "MapFullScene"; area.Name = "MapTaskArea";
            plus.Click += delegate { Bridge("zoom(1.3)"); };
            minus.Click += delegate { Bridge("zoom(1/1.3)"); };
            all.Click += delegate { Bridge("fit('all')"); };
            area.Click += delegate { Bridge("fit('area')"); };
            starts.Name = "MapStarts"; starts.Click += delegate { Bridge("fit('starts')"); };
            layers.Name = "MapLayerMenu";
            sceneLayerMenu = new ContextMenuStrip { Name = "SceneLayers", AutoClose = true };
            for (int i = 1; i < sceneLayerLabels.Length; i++)
            {
                int index = i;
                ToolStripMenuItem item = new ToolStripMenuItem(sceneLayerLabels[i]) { Tag = index, CheckOnClick = true, Checked = sceneLayerVisibility[i] };
                if (index == 4) item.ToolTipText = "显示被观察目标的位置和识别标注，例如封控场景中接近边界的目标；不控制平台运动。";
                item.CheckedChanged += delegate
                {
                    if (!syncingLayerMenu && !IsDisposed) SetSceneLayer(index, item.Checked);
                };
                sceneLayerMenu.Items.Add(item);
            }
            sceneLayerMenu.Opening += delegate
            {
                foreach (ToolStripMenuItem item in sceneLayerMenu.Items)
                    SyncSceneLayerMenu((int)item.Tag, sceneLayerVisibility[(int)item.Tag]);
            };
            // ToolStrip finishes mouse/click handling after Closed is raised.
            // Keep the menu alive through those callbacks and dispose with its form.
            Disposed += delegate { if (sceneLayerMenu != null) sceneLayerMenu.Dispose(); };
            layers.ContextMenuStrip = sceneLayerMenu;
            layers.Click += delegate
            {
                if (sceneLayerMenu.Visible) sceneLayerMenu.Close();
                else sceneLayerMenu.Show(layers, new Point(0, layers.Height));
            };
            new ToolTip().SetToolTip(all, "显示完整底图、平台起点与全部轨迹");
            actions.Controls.AddRange(new Control[] { plus, minus, all, area, starts, layers });
            sceneInfo.Parent.Controls.Add(actions);
            actions.BringToFront();
            reconRecordNotice = new Panel { Dock=DockStyle.Top, Height=32, BackColor=Color.FromArgb(255,247,230), Visible=false };
            reconRecordText = new Label { Dock=DockStyle.Fill, TextAlign=ContentAlignment.MiddleLeft, Padding=new Padding(8,0,0,0), ForeColor=Color.FromArgb(150,85,25) };
            Button currentRecon=StandardButton("打开建筑群演示",145);currentRecon.Dock=DockStyle.Right;currentRecon.Click+=delegate { scenarioBox.SelectedItem="interop_recon";OpenSelectedScenarioDemo(); };
            reconRecordNotice.Controls.Add(reconRecordText);reconRecordNotice.Controls.Add(currentRecon);taskViewTab.Controls.Add(reconRecordNotice);reconRecordNotice.BringToFront();
            sceneCoordinates = new ToolStripStatusLabel("X —  Y —") { Padding = new Padding(8, 0, 8, 0), ForeColor = Color.FromArgb(72, 110, 153) };
            Shown += delegate
            {
                foreach (Control control in Controls)
                {
                    StatusStrip strip = control as StatusStrip;
                    if (strip != null) { strip.Items.Insert(Math.Max(0, strip.Items.Count - 1), sceneCoordinates); break; }
                }
            };
        }

        private void SyncSceneLayerMenu(int index, bool visible)
        {
            if (sceneLayerMenu == null || sceneLayerMenu.IsDisposed) return;
            syncingLayerMenu = true;
            try { foreach (ToolStripMenuItem item in sceneLayerMenu.Items) if ((int)item.Tag == index) item.Checked = visible; }
            finally { syncingLayerMenu = false; }
        }

        private void AddAgentLegend(FlowLayoutPanel panel, string kind, string text, Color color)
        {
            Panel item = new Panel { Width = 61, Height = 24, Margin = new Padding(0, 0, 3, 0) };
            PictureBox picture = new PictureBox { Width = 19, Height = 24, Dock = DockStyle.Left, SizeMode = PictureBoxSizeMode.Zoom };
            Label label = new Label { Text = text, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, Font = new Font(Font.FontFamily, 8.2f), ForeColor = color };
            item.Controls.Add(label); item.Controls.Add(picture); panel.Controls.Add(item);
            agentLegendPictures[kind] = picture;
        }

        private bool HandleSceneUiMessage(string type, Dictionary<string, object> message)
        {
            if (HandleAltitudeMessage(type, message)) return true;
            if (type == "coordinate")
            {
                if (sceneCoordinates != null) sceneCoordinates.Text = message.ContainsKey("text") ? Convert.ToString(message["text"]) : "X —  Y —";
                return true;
            }
            if (type != "legend") return false;
            Dictionary<string, object> icons = message.ContainsKey("icons") ? message["icons"] as Dictionary<string, object> : null;
            if (icons == null) return true;
            foreach (KeyValuePair<string, PictureBox> pair in agentLegendPictures)
            {
                object raw;
                if (!icons.TryGetValue(pair.Key, out raw)) continue;
                string value = Convert.ToString(raw); int comma = value.IndexOf(',');
                if (comma < 0 || value.Length > 65536) continue;
                try
                {
                    using (MemoryStream stream = new MemoryStream(Convert.FromBase64String(value.Substring(comma + 1))))
                    using (Image image = Image.FromStream(stream))
                    {
                        Image previous = pair.Value.Image; pair.Value.Image = new Bitmap(image); if (previous != null) previous.Dispose();
                    }
                }
                catch (Exception ex) { LogDesktop("平台图例载入失败：" + ex.Message); }
            }
            return true;
        }
    }
}
