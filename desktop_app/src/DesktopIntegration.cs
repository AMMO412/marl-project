using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private WebView2 webView;
        private TabPage taskViewTab;
        private Label taskViewStatus;
        private ToolStripComboBox scenarioBox;
        private ToolStripButton desktopRunButton, desktopRefreshButton, desktopTaskViewButton, desktopPlayButton, desktopPauseButton;
        private ToolStripLabel desktopSourceLabel;
        private ToolStripStatusLabel desktopBackendStatus;
        private System.Windows.Forms.Timer desktopPoll;
        private BackendSupervisor desktopBackend;
        private DesktopApi desktopApi;
        private DesktopCatalog desktopCatalog;
        private DesktopRunView desktopRun;
        private string desktopRunId = "";
        private string desktopTaskId = "";
        private string pendingRunId = "";
        private string pendingTaskId = "";
        private double pendingStart;
        private bool webReady;
        private bool backendStarting;
        private bool polling;
        private readonly JavaScriptSerializer desktopJson = new JavaScriptSerializer();

        private void InitializeDesktop()
        {
            desktopPoll = new System.Windows.Forms.Timer { Interval = 1000 };
            desktopPoll.Tick += delegate { PollDesktop(); };
            desktopPoll.Start();
            Shown += delegate { StartDesktopBackend(); };
            FormClosed += delegate
            {
                if (desktopPoll != null) desktopPoll.Stop();
                if (desktopBackend != null) desktopBackend.Dispose();
                if (webView != null) webView.Dispose();
            };
        }

        private void AugmentDesktopToolbar(ToolStrip toolbar)
        {
            List<ToolStripItem> hide = new List<ToolStripItem>();
            foreach (ToolStripItem item in toolbar.Items)
            {
                if (item.Text == "打开" || item.Text == "保存" || item.Text == "生成示例")
                    hide.Add(item);
                if (item.Name == "desktopSourceLabel") desktopSourceLabel = item as ToolStripLabel;
            }
            foreach (ToolStripItem item in hide) item.Visible = false;

            toolbar.Items.Add(new ToolStripSeparator());
            toolbar.Items.Add(new ToolStripLabel("场景") { ForeColor = Color.FromArgb(83, 108, 138) });
            scenarioBox = new ToolStripComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 190, AutoSize = false };
            scenarioBox.Items.Add("interop_containment");
            scenarioBox.SelectedIndex = 0;
            scenarioBox.SelectedIndexChanged += delegate
            {
                if (status != null && scenarioBox.SelectedItem != null)
                    status.Text = "当前场景：" + scenarioBox.SelectedItem;
            };
            toolbar.Items.Add(scenarioBox);
            desktopRunButton = ToolButton("运行", "play", delegate { RunSelectedScenario(); }, true);
            desktopRefreshButton = ToolButton("刷新", "check", delegate { RefreshCatalogFromBackend(); }, false);
            desktopTaskViewButton = ToolButton("任务视图", "map", delegate { OpenTaskView(); }, false);
            toolbar.Items.Add(desktopRunButton);
            toolbar.Items.Add(desktopRefreshButton);
            toolbar.Items.Add(desktopTaskViewButton);
            toolbar.Items.Add(new ToolStripSeparator());
            desktopPlayButton = ToolButton("播放", "play", delegate { Bridge("play()"); }, false);
            desktopPauseButton = ToolButton("暂停", "list", delegate { Bridge("pause()"); }, false);
            toolbar.Items.Add(desktopPlayButton);
            toolbar.Items.Add(desktopPauseButton);

            desktopBackendStatus = FindStatusLabel("desktopBackendStatus");
            if (desktopSourceLabel != null) desktopSourceLabel.Text = "本地可视化演示  |  后端连接中";
            SetBackendStatus("本地演示 · 后端连接中", Color.FromArgb(112, 133, 156));
        }

        private void AugmentDesktopTabs()
        {
            taskViewTab = NewTab("任务视图");
            Panel top = new Panel { Dock = DockStyle.Top, Height = 32, BackColor = Color.FromArgb(248, 251, 254) };
            taskViewStatus = new Label
            {
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleLeft,
                Padding = new Padding(10, 0, 0, 0),
                ForeColor = Color.FromArgb(83, 108, 138),
                Font = new Font(Font.FontFamily, 8.5f),
                Text = "任务视图：等待本地后端连接…"
            };
            top.Controls.Add(taskViewStatus);
            webView = new WebView2 { Dock = DockStyle.Fill };
            taskViewTab.Controls.Add(webView);
            taskViewTab.Controls.Add(top);
            Documents.TabPages.Add(taskViewTab);
            Documents.SelectedIndexChanged += delegate
            {
                if (Documents.SelectedTab == taskViewTab && webReady && desktopRun != null)
                    Bridge("navigate('overview')");
            };

            if (tree != null)
            {
                tree.AfterSelect += delegate(object s, TreeViewEventArgs e)
                {
                    string tag = e.Node.Tag as string;
                    if (tag != null && tag.StartsWith("desktop:task:"))
                    {
                        SelectDesktopTask(tag.Substring("desktop:task:".Length));
                        OpenTaskView();
                    }
                    else if (tag != null && tag.StartsWith("desktop:platform:"))
                    {
                        OpenTaskView();
                    }
                };
            }
            if (history != null)
            {
                history.DoubleClick += delegate
                {
                    if (history.SelectedItems.Count == 0) return;
                    string id = history.SelectedItems[0].Tag as string;
                    if (!string.IsNullOrEmpty(id)) LoadRunAsync(id);
                };
            }
            if (taskGrid != null)
            {
                taskGrid.CellDoubleClick += delegate(object s, DataGridViewCellEventArgs e)
                {
                    if (e.RowIndex < 0 || desktopRun == null || e.RowIndex >= desktopRun.Tasks.Count) return;
                    SelectDesktopTask(desktopRun.Tasks[e.RowIndex].Id);
                    OpenTaskView();
                };
            }
            if (platformGrid != null)
            {
                platformGrid.Columns[0].HeaderText = "平台编号";
                platformGrid.Columns[1].HeaderText = "类别";
                platformGrid.Columns[2].HeaderText = "当前任务";
                platformGrid.Columns[3].HeaderText = "状态";
                platformGrid.Columns[4].HeaderText = "模型电量";
            }
            if (taskGrid != null)
            {
                taskGrid.Columns[0].HeaderText = "任务编号";
                taskGrid.Columns[1].HeaderText = "任务名称";
                taskGrid.Columns[2].HeaderText = "类型";
                taskGrid.Columns[3].HeaderText = "状态";
                taskGrid.Columns[4].HeaderText = "分配平台";
                taskGrid.Columns[5].HeaderText = "时间窗";
            }
        }

        private ToolStripStatusLabel FindStatusLabel(string name)
        {
            foreach (Control control in Controls)
            {
                StatusStrip strip = control as StatusStrip;
                if (strip == null) continue;
                foreach (ToolStripItem item in strip.Items)
                {
                    if (item.Name == name) return item as ToolStripStatusLabel;
                }
            }
            return null;
        }

        private void StartDesktopBackend()
        {
            if (backendStarting) return;
            backendStarting = true;
            SetBackendStatus("本地演示 · 正在启动后端…", Color.FromArgb(176, 112, 32));
            desktopBackend = new BackendSupervisor(LogDesktop);
            Task.Run(delegate
            {
                try
                {
                    string url = desktopBackend.EnsureStartedAsync().GetAwaiter().GetResult();
                    Ui(delegate { OnBackendReady(url); });
                }
                catch (Exception ex)
                {
                    Ui(delegate
                    {
                        backendStarting = false;
                        SetBackendStatus("本地演示 · 后端启动失败", Color.FromArgb(180, 60, 60));
                        SetTaskViewStatus("任务视图：后端启动失败。" + ex.Message);
                        LogDesktop("后端启动失败：" + ex.Message);
                    });
                }
            });
        }

        private void OnBackendReady(string url)
        {
            backendStarting = false;
            desktopApi = new DesktopApi(url);
            SetBackendStatus("本地演示 · 后端已连接", Color.FromArgb(47, 130, 96));
            if (desktopSourceLabel != null) desktopSourceLabel.Text = "本地可视化演示  |  " + url;
            InitializeWebView(url);
            RefreshCatalogFromBackend();
        }

        private async void InitializeWebView(string url)
        {
            if (webView == null) return;
            try
            {
                string userData = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "MARL界面预览", "WebView2");
                bool fallback = false;
                try { Directory.CreateDirectory(userData); }
                catch (Exception) { fallback = true; }
                if (fallback)
                {
                    // Sandboxed or locked-down profiles may deny %LOCALAPPDATA%;
                    // fall back inside the application folder so the demo still runs.
                    userData = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "data", "webview2");
                    Directory.CreateDirectory(userData);
                }
                CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(null, userData, null);
                await webView.EnsureCoreWebView2Async(environment);
                webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
                webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
                webView.CoreWebView2.WebMessageReceived += delegate(object s, CoreWebView2WebMessageReceivedEventArgs e)
                {
                    HandleWebMessage(e.WebMessageAsJson);
                };
                webView.CoreWebView2.NavigationCompleted += delegate
                {
                    SetTaskViewStatus("任务视图：页面已载入，等待数据…");
                };
                webView.CoreWebView2.Navigate(url + "/?desktop=1&page=containment");
                SetTaskViewStatus("任务视图：正在载入本地可视化页面…");
            }
            catch (Exception ex)
            {
                SetTaskViewStatus("任务视图：WebView2 初始化失败。" + ex.Message);
                LogDesktop("WebView2 初始化失败：" + ex.Message);
            }
        }

        private void HandleWebMessage(string body)
        {
            if (string.IsNullOrEmpty(body)) return;
            try
            {
                object raw = desktopJson.DeserializeObject(body);
                Dictionary<string, object> message = raw as Dictionary<string, object>;
                if (message == null) return;
                string type = Convert.ToString(message.ContainsKey("type") ? message["type"] : "");
                if (type == "ready")
                {
                    webReady = true;
                    SetTaskViewStatus("任务视图：已连接本地可视化页面");
                    if (!string.IsNullOrEmpty(pendingRunId))
                    {
                        string id = pendingRunId;
                        pendingRunId = "";
                        Bridge("selectRun(" + desktopJson.Serialize(id) + ")");
                        Bridge("startReplay(" + desktopJson.Serialize(pendingTaskId) + ", "
                               + pendingStart.ToString("0.###", CultureInfo.InvariantCulture) + ", "
                               + desktopJson.Serialize(id) + ")");
                    }
                    else if (!string.IsNullOrEmpty(desktopRunId))
                    {
                        Bridge("selectRun(" + desktopJson.Serialize(desktopRunId) + ")");
                    }
                }
                else if (type == "state")
                {
                    Dictionary<string, object> state = message.ContainsKey("state") ? message["state"] as Dictionary<string, object> : null;
                    if (state == null) return;
                    double t = 0;
                    if (state.ContainsKey("time")) double.TryParse(Convert.ToString(state["time"], CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out t);
                    double duration = 0;
                    if (state.ContainsKey("duration")) double.TryParse(Convert.ToString(state["duration"], CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out duration);
                    if (timeStatus != null) timeStatus.Text = "任务视图 " + t.ToString("0.0") + " / " + duration.ToString("0.0") + " s";
                    if (clock != null) clock.Text = t.ToString("0.0") + " / " + duration.ToString("0.0") + " s";
                }
            }
            catch (Exception ex)
            {
                LogDesktop("页面消息解析失败：" + ex.Message);
            }
        }

        private void RefreshCatalogFromBackend()
        {
            if (desktopApi == null)
            {
                SetTaskViewStatus("任务视图：本地后端尚未连接。");
                return;
            }
            Task.Run(delegate
            {
                try
                {
                    DesktopCatalog catalog = desktopApi.GetCatalog();
                    Ui(delegate { ApplyCatalog(catalog); });
                }
                catch (Exception ex)
                {
                    Ui(delegate
                    {
                        SetBackendStatus("本地演示 · 后端读取失败", Color.FromArgb(180, 60, 60));
                        LogDesktop("读取运行记录失败：" + ex.Message);
                    });
                }
            });
        }

        private void ApplyCatalog(DesktopCatalog catalog)
        {
            desktopCatalog = catalog;
            SetBackendStatus("本地演示 · 后端已连接", Color.FromArgb(47, 130, 96));
            string selected = scenarioBox.SelectedItem as string;
            scenarioBox.Items.Clear();
            foreach (KeyValuePair<string, string> pair in catalog.Scenarios)
                scenarioBox.Items.Add(pair.Key);
            if (catalog.Scenarios.Count == 0)
            {
                scenarioBox.Items.Add("interop_containment");
                scenarioBox.Items.Add("interop_hold");
                scenarioBox.Items.Add("interop_patrol");
                scenarioBox.Items.Add("interop_recon");
                scenarioBox.Items.Add("interop_asl");
            }
            if (selected != null && scenarioBox.Items.Contains(selected)) scenarioBox.SelectedItem = selected;
            else if (scenarioBox.Items.Contains("interop_containment")) scenarioBox.SelectedItem = "interop_containment";
            else if (scenarioBox.Items.Count > 0) scenarioBox.SelectedIndex = 0;

            if (history != null)
            {
                history.BeginUpdate();
                history.Items.Clear();
                foreach (DesktopRunSummary run in catalog.Runs)
                {
                    string scenario = run.Scenario;
                    string label;
                    if (!string.IsNullOrEmpty(scenario) && catalog.Scenarios.TryGetValue(scenario, out label)) { }
                    else label = scenario;
                    ListViewItem item = new ListViewItem(new string[]
                    {
                        run.Id,
                        label,
                        (run.Motion == "real" ? "逐步运动" : "瞬移") + (run.Behavior ? " · 到位行为" : " · 到点作业"),
                        run.Done.ToString() + "/" + run.Total.ToString()
                    });
                    item.Tag = run.Id;
                    history.Items.Add(item);
                }
                history.EndUpdate();
            }
            SetTaskViewStatus("任务视图：已载入 " + catalog.Runs.Count + " 条运行记录；点“运行”生成新记录。");
            if (desktopRunId == "" && catalog.Runs.Count > 0)
            {
                DesktopRunSummary preferred = catalog.Runs.FirstOrDefault(delegate(DesktopRunSummary r) { return r.Scenario == "interop_containment"; });
                LoadRunAsync((preferred ?? catalog.Runs[0]).Id);
            }
        }

        private void LoadRunAsync(string runId)
        {
            if (desktopApi == null || string.IsNullOrEmpty(runId)) return;
            SetTaskViewStatus("任务视图：正在载入运行 " + runId + "…");
            Task.Run(delegate
            {
                try
                {
                    DesktopRunView run = desktopApi.GetRun(runId, null);
                    Ui(delegate { ApplyRun(run); });
                }
                catch (Exception ex)
                {
                    Ui(delegate { SetTaskViewStatus("任务视图：运行载入失败。" + ex.Message); LogDesktop("运行载入失败：" + ex.Message); });
                }
            });
        }

        private void ApplyRun(DesktopRunView run)
        {
            desktopRun = run;
            desktopRunId = run.Id;
            if (taskGrid != null)
            {
                taskGrid.Rows.Clear();
                foreach (DesktopTask task in run.Tasks)
                {
                    string window = "—";
                    if (task.Window != null && task.Window.Length >= 2)
                        window = task.Window[0].ToString("0") + "–" + task.Window[1].ToString("0") + " s";
                    taskGrid.Rows.Add(task.Id, task.Label, task.Label,
                        StatusText(string.IsNullOrEmpty(task.StatusAt) ? task.Status : task.StatusAt),
                        task.Assigned.Count == 0 ? "等待分配" : string.Join(" · ", task.Assigned.ToArray()),
                        window);
                }
            }
            if (platformGrid != null)
            {
                platformGrid.Rows.Clear();
                foreach (DesktopPlatform platform in run.Platforms)
                {
                    string battery = platform.Battery <= 0 ? "—" : platform.Battery.ToString("0.0");
                    platformGrid.Rows.Add(platform.Id, platform.Kind,
                        string.IsNullOrEmpty(platform.Job) ? "—" : platform.Job,
                        StatusText(string.IsNullOrEmpty(platform.Status) ? platform.Phase : platform.Status),
                        battery);
                }
            }
            if (history != null)
            {
                foreach (ListViewItem item in history.Items)
                {
                    if (Convert.ToString(item.Tag) == run.Id) { item.Selected = true; item.Focused = true; break; }
                }
            }
            UpdateDesktopTree(run);
            if (desktopRun.Tasks.Count > 0) SelectDesktopTask(desktopRun.Tasks[0].Id);
            SetTaskViewStatus("任务视图：运行 " + run.Id + " · " + run.Done + "/" + run.Total + " 完成 · " + run.End.ToString("0.0") + " s");
            if (status != null) status.Text = "已载入真实运行 " + run.Id + "（" + run.End.ToString("0.0") + " s）";
            double startAt = Math.Min(30.0, Math.Max(1.0, run.End * 0.35));
            if (!webReady)
            {
                pendingRunId = run.Id;
                pendingTaskId = run.Tasks.Count > 0 ? run.Tasks[0].Id : "";
                pendingStart = startAt;
                OpenTaskView();
                return;
            }
            Bridge("navigate('overview')");
            Bridge("selectRun(" + desktopJson.Serialize(run.Id) + ")");
            if (desktopRun.Tasks.Count > 0)
            {
                string taskId = desktopRun.Tasks[0].Id;
                Bridge("startReplay(" + desktopJson.Serialize(taskId) + ", "
                       + startAt.ToString("0.###", CultureInfo.InvariantCulture) + ", "
                       + desktopJson.Serialize(run.Id) + ")");
            }
            OpenTaskView();
        }

        private void UpdateDesktopTree(DesktopRunView run)
        {
            if (tree == null || tree.Nodes.Count == 0) return;
            TreeNode root = tree.Nodes[0];
            root.Text = "T1 区域封控 · 真实运行";
            TreeNode tasksNode = null, platformsNode = null;
            foreach (TreeNode node in root.Nodes)
            {
                if (node.Text.StartsWith("任务")) tasksNode = node;
                else if (node.Text.StartsWith("平台")) platformsNode = node;
            }
            if (tasksNode != null)
            {
                tasksNode.Text = "任务 (" + run.Tasks.Count + ")";
                tasksNode.Nodes.Clear();
                foreach (DesktopTask task in run.Tasks)
                    tasksNode.Nodes.Add(new TreeNode(task.Id + "  " + task.Label) { Tag = "desktop:task:" + task.Id });
                tasksNode.Expand();
            }
            if (platformsNode != null)
            {
                platformsNode.Text = "平台 (" + run.Platforms.Count + ")";
                platformsNode.Nodes.Clear();
                HashSet<string> assigned = new HashSet<string>();
                foreach (DesktopTask task in run.Tasks)
                    foreach (string pid in task.Assigned) assigned.Add(pid);
                int shown = 0;
                foreach (DesktopPlatform platform in run.Platforms)
                {
                    if (!assigned.Contains(platform.Id) && shown >= 8) continue;
                    platformsNode.Nodes.Add(new TreeNode(platform.Id + " " + platform.Kind +
                        (string.IsNullOrEmpty(platform.Job) ? "" : " · " + platform.Job)) { Tag = "desktop:platform:" + platform.Id });
                    shown++;
                }
                platformsNode.Expand();
            }
        }

        private void SelectDesktopTask(string taskId)
        {
            if (desktopRun == null) return;
            DesktopTask task = desktopRun.FindTask(taskId);
            if (task == null) return;
            desktopTaskId = taskId;
            if (properties != null)
            {
                string window = "—";
                if (task.Window != null && task.Window.Length >= 2)
                    window = task.Window[0].ToString("0") + "–" + task.Window[1].ToString("0") + " s";
                string position = "—";
                if (task.Position != null && task.Position.Length >= 2)
                    position = "(" + task.Position[0].ToString("0.0") + ", " + task.Position[1].ToString("0.0") + ")";
                string start = "—", end = "—";
                if (task.Window != null && task.Window.Length >= 2)
                {
                    start = task.Window[0].ToString("0.0") + " s";
                    end = task.Window[1].ToString("0.0") + " s";
                }
                double percent = task.Work > 0 ? Math.Max(0, Math.Min(100, task.Progress / task.Work * 100)) : 0;
                properties.SelectedObject = new TaskProperties
                {
                    Id = task.Id,
                    Name = task.Label,
                    Type = task.Label,
                    Area = "真实运行 · " + desktopRunId,
                    Start = start,
                    End = end,
                    Travel = "—",
                    Members = task.Assigned.Count == 0 ? "等待分配" : string.Join(" · ", task.Assigned.ToArray()),
                    Position = position,
                    Phase = StatusText(string.IsNullOrEmpty(task.StatusAt) ? task.Status : task.StatusAt),
                    Progress = percent.ToString("0") + "%",
                    Source = "本地真实运行记录"
                };
                if (selectedTitle != null) selectedTitle.Text = task.Id + "  " + task.Label;
                if (taskProgress != null) taskProgress.Value = (int)Math.Round(percent);
            }
            if (taskGrid != null)
            {
                foreach (DataGridViewRow row in taskGrid.Rows)
                {
                    if (Convert.ToString(row.Cells[0].Value) == taskId)
                    {
                        row.Selected = true;
                        taskGrid.CurrentCell = row.Cells[0];
                        break;
                    }
                }
            }
            Bridge("selectTask(" + desktopJson.Serialize(taskId) + ")");
            if (status != null) status.Text = "已选择任务 " + task.Id + " · " + task.Label;
        }

        private static string StatusText(string status)
        {
            switch ((status ?? "").ToLowerInvariant())
            {
                case "succeeded": return "已完成";
                case "running": return "执行中";
                case "failed": return "失败";
                case "timeout": return "超时";
                case "pending": return "待开始";
                default: return status ?? "";
            }
        }

        private void RunSelectedScenario()
        {
            if (desktopApi == null)
            {
                SetBackendStatus("本地演示 · 后端未连接", Color.FromArgb(180, 60, 60));
                return;
            }
            string scenario = scenarioBox.SelectedItem as string;
            if (string.IsNullOrEmpty(scenario)) scenario = "interop_containment";
            int maxTicks = scenario == "interop_asl" ? 620 : (scenario == "interop_containment" ? 320 : 420);
            SetTaskViewStatus("任务视图：正在运行 " + scenario + "…");
            if (desktopRunButton != null) desktopRunButton.Enabled = false;
            HashSet<string> before = new HashSet<string>(desktopCatalog == null
                ? new string[0]
                : desktopCatalog.Runs.Select(delegate(DesktopRunSummary r) { return r.Id; }).ToArray());
            Task.Run(delegate
            {
                try
                {
                    desktopApi.StartRun(scenario, "normal", "makespan", maxTicks);
                    for (int i = 0; i < 90; i++)
                    {
                        Thread.Sleep(1000);
                        DesktopCatalog catalog = desktopApi.GetCatalog();
                        DesktopRunSummary created = catalog.Runs.FirstOrDefault(delegate(DesktopRunSummary r) { return !before.Contains(r.Id); });
                        if (created != null && !catalog.ProcessRunning)
                        {
                            Ui(delegate
                            {
                                if (desktopRunButton != null) desktopRunButton.Enabled = true;
                                ApplyCatalog(catalog);
                                LoadRunAsync(created.Id);
                            });
                            return;
                        }
                    }
                    Ui(delegate
                    {
                        if (desktopRunButton != null) desktopRunButton.Enabled = true;
                        SetTaskViewStatus("任务视图：运行超时，未生成新记录。");
                    });
                }
                catch (Exception ex)
                {
                    Ui(delegate
                    {
                        if (desktopRunButton != null) desktopRunButton.Enabled = true;
                        SetTaskViewStatus("任务视图：运行失败。" + ex.Message);
                        LogDesktop("运行失败：" + ex.ToString());
                        try { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "run-error.txt"), ex.ToString()); } catch (Exception) { }
                    });
                }
            });
        }

        private void OpenTaskView()
        {
            if (taskViewTab == null || Documents == null) return;
            Documents.SelectedTab = taskViewTab;
        }

        private void PollDesktop()
        {
            if (polling || webView == null || webView.CoreWebView2 == null || !webReady) return;
            polling = true;
            try
            {
                string script = "window.MarlDesktop ? JSON.stringify(window.MarlDesktop.getState()) : ''";
                Task<string> task = webView.CoreWebView2.ExecuteScriptAsync(script);
                task.ContinueWith(delegate(Task<string> finished)
                {
                    Ui(delegate
                    {
                        polling = false;
                        if (finished.Status != TaskStatus.RanToCompletion) return;
                        string value = finished.Result;
                        if (string.IsNullOrEmpty(value) || value == "\"\"") return;
                        try
                        {
                            object raw = desktopJson.DeserializeObject(value);
                            string json = raw as string;
                            if (string.IsNullOrEmpty(json)) json = value;
                            Dictionary<string, object> state = desktopJson.DeserializeObject(json) as Dictionary<string, object>;
                            if (state == null) return;
                            double t = 0, duration = 0;
                            if (state.ContainsKey("time")) double.TryParse(Convert.ToString(state["time"], CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out t);
                            if (state.ContainsKey("duration")) double.TryParse(Convert.ToString(state["duration"], CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out duration);
                            if (timeStatus != null) timeStatus.Text = "任务视图 " + t.ToString("0.0") + " / " + duration.ToString("0.0") + " s";
                        }
                        catch (Exception) { }
                    });
                });
            }
            catch (Exception)
            {
                polling = false;
            }
        }

        private void Bridge(string script)
        {
            if (webView == null || webView.CoreWebView2 == null) return;
            try
            {
                webView.CoreWebView2.ExecuteScriptAsync("if(window.MarlDesktop){window.MarlDesktop." + script + ";}");
            }
            catch (Exception ex)
            {
                LogDesktop("页面控制失败：" + ex.Message);
            }
        }

        private void SetBackendStatus(string text, Color color)
        {
            if (status != null) { status.Text = text; status.ForeColor = color; }
            if (desktopBackendStatus == null) desktopBackendStatus = FindStatusLabel("desktopBackendStatus");
            if (desktopBackendStatus != null) { desktopBackendStatus.Text = text; desktopBackendStatus.ForeColor = color; }
            if (desktopSourceLabel == null)
            {
                foreach (Control control in Controls)
                {
                    ToolStrip strip = control as ToolStrip;
                    if (strip == null) continue;
                    foreach (ToolStripItem item in strip.Items)
                        if (item.Name == "desktopSourceLabel") desktopSourceLabel = item as ToolStripLabel;
                }
            }
        }

        private void SetTaskViewStatus(string text)
        {
            if (taskViewStatus != null) taskViewStatus.Text = text;
        }

        private void Ui(Action action)
        {
            if (IsDisposed) return;
            if (InvokeRequired) BeginInvoke(action);
            else action();
        }

        private void LogDesktop(string text)
        {
            if (string.IsNullOrEmpty(text)) return;
            Ui(delegate
            {
                if (log == null) return;
                if (log.TextLength > 60000) log.Text = log.Text.Substring(log.TextLength - 30000);
                log.AppendText("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + text + "\r\n");
            });
        }

        public void StartDemoRunForVerification()
        {
            RunSelectedScenario();
        }

        public void CaptureLiveVerification(string directory)
        {
            Directory.CreateDirectory(directory);
            if (WindowState != FormWindowState.Normal) WindowState = FormWindowState.Normal;
            Size = new Size(1500, 940);
            OpenTaskView();
            TopMost = true;
            SetForegroundWindow(Handle);
            Activate();
            BringToFront();
            Application.DoEvents();
            System.Threading.Thread.Sleep(900);
            Application.DoEvents();
            using (Bitmap bitmap = new Bitmap(Width, Height))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(Location, Point.Empty, Size);
                bitmap.Save(Path.Combine(directory, "live-preview.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
            Documents.SelectedIndex = 1;
            Application.DoEvents();
            using (Bitmap bitmap = new Bitmap(Width, Height))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(Location, Point.Empty, Size);
                bitmap.Save(Path.Combine(directory, "live-tasks.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
            Documents.SelectedIndex = 2;
            Application.DoEvents();
            using (Bitmap bitmap = new Bitmap(Width, Height))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(Location, Point.Empty, Size);
                bitmap.Save(Path.Combine(directory, "live-platforms.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
            Documents.SelectedIndex = 4;
            string webState = "";
            string webMetrics = "";
            try
            {
                if (webView != null && webView.CoreWebView2 != null)
                {
                    Task<string> stateTask = webView.CoreWebView2.ExecuteScriptAsync("JSON.stringify(window.MarlDesktop ? window.MarlDesktop.getState() : {})");
                    while (!stateTask.IsCompleted)
                    {
                        Application.DoEvents();
                        System.Threading.Thread.Sleep(20);
                    }
                    webState = stateTask.Status == TaskStatus.RanToCompletion ? stateTask.Result : "";
                    Task<string> metricTask = webView.CoreWebView2.ExecuteScriptAsync(
                        "JSON.stringify((function(){var c=document.querySelector('#ck-canvas');var s=document.querySelector('#scene');var r=c?c.getBoundingClientRect():null;var b=s?s.getBoundingClientRect():null;return {ck:r?[r.width,r.height]:null,scene:b?[b.width,b.height]:null,css:c?getComputedStyle(c).backgroundColor:null,page:getComputedStyle(document.body).backgroundColor};})())");
                    while (!metricTask.IsCompleted)
                    {
                        Application.DoEvents();
                        System.Threading.Thread.Sleep(20);
                    }
                    webMetrics = metricTask.Status == TaskStatus.RanToCompletion ? metricTask.Result : "";
                }
            }
            catch (Exception) { }
            string[] lines = new string[]
            {
                "web_ready=" + webReady,
                "web_state=" + webState,
                "web_metrics=" + webMetrics,
                "backend=" + (desktopApi == null ? "" : desktopApi.BaseUrl),
                "run=" + desktopRunId,
                "tasks=" + (desktopRun == null ? 0 : desktopRun.Tasks.Count),
                "platforms=" + (desktopRun == null ? 0 : desktopRun.Platforms.Count),
                "task_view_status=" + (taskViewStatus == null ? "" : taskViewStatus.Text),
                "status=" + (status == null ? "" : status.Text),
                "bounds=" + Location.X + "," + Location.Y + "," + Width + "," + Height
            };
            File.WriteAllLines(Path.Combine(directory, "live-verification.txt"), lines, new UTF8Encoding(false));
            TopMost = false;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        private void ShowAboutDesktop()
        {
            MessageBox.Show(this,
                "多智能体协同规划系统\n本地可视化演示版 0.5\n\n" +
                "本软件用于展示规划中间层的任务规划、分配、执行与回放能力。\n" +
                "真实平台展示目标是接入下层 Gazebo，并在 UE5 中呈现；\n" +
                "当前版本为本地演示，不代表真实平台联调完成。\n\n" +
                "运行数据来自本机 planning_middle_demo 后端，界面中的“任务视图”\n" +
                "显示真实运行回放；场景总览为布局示意。",
                "关于", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

}
