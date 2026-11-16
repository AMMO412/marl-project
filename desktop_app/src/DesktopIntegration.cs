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
        private WebViewProfileLease webProfile;
        private bool webInitializing;
        private int webNavigationVersion, webPageRecoveryAttempts;
        private TabPage taskViewTab;
        private Label taskViewStatus;
        private ToolStripComboBox scenarioBox;
        private ToolStripButton desktopRunButton, desktopRefreshButton, desktopTaskViewButton;
        private ToolStripLabel desktopSourceLabel;
        private ToolStripStatusLabel desktopBackendStatus;
        private System.Windows.Forms.Timer desktopPoll;
        private BackendSupervisor desktopBackend;
        private DesktopApi desktopApi;
        private DesktopCatalog desktopCatalog;
        private DesktopRunView desktopRun;
        private string desktopRunId = "";
        private int desktopLoadVersion;
        private string desktopTaskId = "";
        private string pendingRunId = "";
        private string pendingTaskId = "";
        private double pendingStart;
        private bool webReady;
        private bool webPlaying;
        private bool backendStarting;
        private bool polling;
        private readonly JavaScriptSerializer desktopJson = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };

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
                if (webProfile != null) webProfile.Dispose();
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
            scenarioBox.ComboBox.FormattingEnabled = true;
            scenarioBox.ComboBox.Format += delegate(object sender, ListControlConvertEventArgs e)
            { string label; if (desktopCatalog != null && desktopCatalog.Scenarios.TryGetValue(Convert.ToString(e.ListItem), out label)) e.Value = label; };
            scenarioBox.Items.Add("interop_containment");
            scenarioBox.SelectedIndex = 0;
            scenarioBox.SelectedIndexChanged += delegate
            {
                if (status != null && scenarioBox.SelectedItem != null)
                    status.Text = "当前场景：" + scenarioBox.SelectedItem;
            };
            scenarioBox.ComboBox.SelectionChangeCommitted += delegate { OpenSelectedScenarioDemo(); };
            toolbar.Items.Add(scenarioBox);
            desktopRunButton = ToolButton("运行", "play", delegate { RunSelectedScenario(); }, true);
            desktopRefreshButton = ToolButton("刷新", "check", delegate { RefreshCatalogFromBackend(true); }, false);
            desktopTaskViewButton = ToolButton("场景视图", "map", delegate { OpenTaskView(); }, false);
            toolbar.Items.Add(desktopRunButton);
            toolbar.Items.Add(desktopRefreshButton);
            toolbar.Items.Add(desktopTaskViewButton);
            toolbar.Items.Add(new ToolStripSeparator());

            desktopBackendStatus = FindStatusLabel("desktopBackendStatus");
            if (desktopSourceLabel != null) desktopSourceLabel.Text = "本地可视化演示  |  后端连接中";
            SetBackendStatus("本地演示 · 后端连接中", Color.FromArgb(112, 133, 156));
        }

        private void AugmentDesktopTabs()
        {
            taskViewTab = Documents.TabPages[0];
            taskViewStatus = sceneInfo;
            taskViewStatus.Text = "场景视图：等待本地运行数据…";
            Canvas.Visible = false;
            taskViewTab.Controls.Remove(Canvas);
            webView = new WebView2 { Dock = DockStyle.Fill };
            taskViewTab.Controls.Add(webView);
            taskViewTab.Controls.Add(BuildDesktopLegend());
            webView.BringToFront();
            BuildNativeSceneControls();
            Documents.SelectedIndexChanged += delegate
            {
                if (webReady) Bridge("setBackgroundPlayback(" + (Documents.SelectedTab == taskViewTab ? "false" : "true") + ")");
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
                        SelectNativePlatform(tag.Substring("desktop:platform:".Length), true);
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
                platformGrid.Columns.Add("altitude", "高度 / 场景单位");
                platformGrid.Columns.Add("participation", "本轮分配");
                foreach (DataGridViewColumn column in platformGrid.Columns) column.SortMode = DataGridViewColumnSortMode.NotSortable;
            }
            if (taskGrid != null)
            {
                taskGrid.Columns[0].HeaderText = "任务编号";
                taskGrid.Columns[1].HeaderText = "任务名称";
                taskGrid.Columns[2].HeaderText = "类型";
                taskGrid.Columns[3].HeaderText = "状态";
                taskGrid.Columns[4].HeaderText = "分配平台";
                taskGrid.Columns[5].HeaderText = "时间窗";
                taskGrid.Columns[0].FillWeight = 70;
                taskGrid.Columns[1].FillWeight = 140;
                taskGrid.Columns[1].DefaultCellStyle.WrapMode = DataGridViewTriState.True;
                taskGrid.Columns[2].FillWeight = 70;
                taskGrid.Columns[3].FillWeight = 70;
                taskGrid.Columns[5].FillWeight = 90;
                taskGrid.Columns[4].DefaultCellStyle.WrapMode = DataGridViewTriState.True;
                taskGrid.Columns[4].FillWeight = 230;
                taskGrid.Columns[4].MinimumWidth = 180;
                taskGrid.AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.AllCells;
            }
        }

        private Control BuildDesktopLegend()
        {
            FlowLayoutPanel legend = new WrappingLegendPanel();
            AddAgentLegend(legend, "UGV", "轮式车", Color.FromArgb(63, 111, 163));
            AddAgentLegend(legend, "TANK", "履带车", Color.FromArgb(138, 107, 61));
            AddAgentLegend(legend, "PLANE", "固定翼", Color.FromArgb(47, 143, 134));
            AddAgentLegend(legend, "WING", "飞翼", Color.FromArgb(118, 87, 168));
            AddLegend(legend, "◇", "任务点", Color.FromArgb(130, 156, 140));
            AddLegend(legend, "—", "运动轨迹", Color.FromArgb(79, 134, 184));
            AddLegend(legend, "■", "建筑", Color.FromArgb(185, 200, 214));
            AddLegend(legend, "■", "花坛", Color.FromArgb(153, 183, 140));
            AddLegend(legend, "■", "标识柱", Color.FromArgb(210, 179, 107));
            AddLegend(legend, "■", "围墙", Color.FromArgb(174, 180, 177));
            AddLegend(legend, "▭", "威胁区", Color.FromArgb(194, 65, 12));
            return legend;
        }

        private void AddLegend(FlowLayoutPanel panel, string marker, string text, Color color)
        {
            Label item = new Label
            {
                AutoSize = true,
                Text = marker + " " + text,
                ForeColor = color,
                Font = new Font(Font.FontFamily, 8.2f),
                Margin = new Padding(0, 0, 3, 0),
                MinimumSize = new Size(0,24),
                TextAlign = ContentAlignment.MiddleLeft
            };
            panel.Controls.Add(item);
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

        public bool SkipBackendForVerification;
        private void StartDesktopBackend()
        {
            if (SkipBackendForVerification) return;
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
                        SetTaskViewStatus("场景视图：后端启动失败。" + ex.Message);
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
            if (webView == null || IsDisposed || Disposing || webInitializing) return;
            if (webView.CoreWebView2 != null) { webView.CoreWebView2.Navigate(url + "/?desktop=1&build=20261111-chain12"); return; }
            webInitializing=true;
            var excluded=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var failedLeases=new List<WebViewProfileLease>();
            try
            {
                for(int attempt=0;attempt<3;attempt++)
                {
                    WebViewProfileLease candidate=WebViewProfileLease.Acquire(excluded);
                    excluded.Add(candidate.DirectoryPath);
                    try {
                        LogDesktop("地图浏览器缓存："+candidate.DirectoryPath);
                        Program.DesktopTrace("WebView2 pid="+System.Diagnostics.Process.GetCurrentProcess().Id+" profile="+candidate.DirectoryPath+" creating environment");
                        CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(null,candidate.DirectoryPath,null);
                        if(IsDisposed || Disposing || webView.IsDisposed){candidate.Dispose();return;}
                        await webView.EnsureCoreWebView2Async(environment);
                        Program.DesktopTrace("WebView2 pid="+System.Diagnostics.Process.GetCurrentProcess().Id+" controller ready");
                        if(IsDisposed || Disposing || webView.IsDisposed){candidate.Dispose();return;}
                        webProfile=candidate;
                        break;
                    }
                    catch(Exception ex) {
                        failedLeases.Add(candidate);
                        if(IsDisposed || Disposing)return;
                        bool recoverable=ex.HResult==unchecked((int)0x800700AA) || ex.HResult==unchecked((int)0x8007139F) || ex.HResult==unchecked((int)0x80070005);
                        if(!recoverable || attempt==2)throw;
                        LogDesktop("地图浏览器缓存占用或不可用（0x"+ex.HResult.ToString("X8")+"），切换独立缓存重试。 ");
                        webReady=false;
                        Control parent=webView.Parent;int order=parent.Controls.GetChildIndex(webView);
                        webView.Dispose();
                        webView=new WebView2 { Dock=DockStyle.Fill };
                        parent.Controls.Add(webView);parent.Controls.SetChildIndex(webView,order);
                        SetTaskViewStatus("场景视图：正在恢复地图浏览器…");
                    }
                    await Task.Delay(200);
                    if(IsDisposed || Disposing)return;
                }
                webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
                webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
                await webView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync("window.__nativeStartupErrors=[];window.addEventListener('error',function(e){window.__nativeStartupErrors.push(e.message||('资源加载失败：'+((e.target||{}).src||'')));},true);");
                if(IsDisposed || Disposing)return;
                webView.CoreWebView2.WebMessageReceived += delegate(object s, CoreWebView2WebMessageReceivedEventArgs e)
                {
                    HandleWebMessage(e.WebMessageAsJson);
                };
                webView.CoreWebView2.NavigationStarting += delegate { webNavigationVersion++;webReady=false; };
                webView.CoreWebView2.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e)
                {
                    Program.DesktopTrace("WebView2 navigation completed success="+e.IsSuccess+" error="+e.WebErrorStatus);
                    SetTaskViewStatus("场景视图：页面已载入，等待数据…");
                    CheckScenePageStartup(webNavigationVersion);
                };
                webView.CoreWebView2.Navigate(url + "/?desktop=1&build=20261111-chain12");
                SetTaskViewStatus("场景视图：正在载入本地可视化页面…");
            }
            catch (Exception ex)
            {
                if(IsDisposed || Disposing)return;
                SetTaskViewStatus("场景视图：WebView2 初始化失败。" + ex.Message);
                LogDesktop("WebView2 初始化失败（0x"+ex.HResult.ToString("X8")+"）：" + ex.Message);
                Program.DesktopTrace("WebView2 initialization: "+ex);
            }
            finally { foreach(var failed in failedLeases)failed.Dispose();webInitializing=false; }
        }

        private async void CheckScenePageStartup(int version)
        {
            try {
                await Task.Delay(1000);
                if(IsDisposed || Disposing || version!=webNavigationVersion || webReady || webView.CoreWebView2==null)return;
                string ready=await webView.CoreWebView2.ExecuteScriptAsync("!!(window.MarlDesktop && window.MarlDesktop.ready)");
                if(IsDisposed || Disposing || version!=webNavigationVersion || webReady)return;
                if(ready=="true") { HandleWebMessage("{\"type\":\"ready\"}");return; }
                string errors=await webView.CoreWebView2.ExecuteScriptAsync("JSON.stringify(window.__nativeStartupErrors||[])");
                if(IsDisposed || Disposing || version!=webNavigationVersion || webReady)return;
                Program.DesktopTrace("WebView2 page startup resources: "+errors);
                if(webPageRecoveryAttempts++<2) {
                    LogDesktop("地图页面资源未完整载入，正在重试（"+webPageRecoveryAttempts+"/2）。");
                    SetTaskViewStatus("场景视图：正在重新载入地图资源…");
                    webView.CoreWebView2.Reload();
                } else {
                    SetTaskViewStatus("场景视图：地图资源载入失败，请查看运行日志。");
                    LogDesktop("地图资源载入失败："+errors);
                }
            }catch(Exception ex){if(!IsDisposed && !Disposing)LogDesktop("检查地图载入状态失败："+ex.Message);}
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
                if (HandleSceneUiMessage(type, message)) return;
                if (type == "ready")
                {
                    webReady = true;
                    webPageRecoveryAttempts=0;
                    if (desktopRun == null) SetTaskViewStatus("场景视图：已连接本地可视化页面");
                    else UpdateSceneRunSummary();
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
                    SyncSceneClock(state);
                }
            }
            catch (Exception ex)
            {
                LogDesktop("页面消息解析失败：" + ex.Message);
            }
        }

        private void RefreshCatalogFromBackend(bool reopenSelected = false)
        {
            if (desktopApi == null)
            {
                SetTaskViewStatus("场景视图：本地后端尚未连接。");
                return;
            }
            Task.Run(delegate
            {
                try
                {
                    DesktopCatalog catalog = desktopApi.GetCatalog();
                    Ui(delegate { ApplyCatalog(catalog); if (reopenSelected) OpenSelectedScenarioDemo(); });
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
                if (pair.Key.StartsWith("interop_")) scenarioBox.Items.Add(pair.Key);
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
                    ListViewItem item = new ListViewItem(NativeHistoryColumns(run));
                    item.Tag = run.Id;
                    history.Items.Add(item);
                }
                history.EndUpdate();
            }
            RefreshNativeHistoryFilter();
            if (desktopRun == null) SetTaskViewStatus("场景视图：已载入 " + catalog.Runs.Count + " 条运行记录；点“运行”生成新记录。");
            else UpdateSceneRunSummary();
            if (!nativeSuppressAutoDemo && desktopRunId == "" && catalog.Runs.Count > 0)
            {
                OpenSelectedScenarioDemo();
            }
        }

        private int nativeDemoVersion;
        private async void OpenSelectedScenarioDemo()
        {
            if (desktopCatalog == null || nativeRunning) { status.Text = "请等待后端连接或当前运行结束。"; return; }
            int version = ++nativeDemoVersion;
            string scenario = SelectedScenario;
            SetNativeWorkState("正在检查演示输入…", true);
            try {
                string id = await Task.Run(delegate { return desktopApi.GetDemoRun(scenario); });
                if (IsDisposed || version != nativeDemoVersion || SelectedScenario != scenario) return;
                if (!string.IsNullOrEmpty(id)) { SetNativeWorkState("正在载入演示…", true); LoadRunAsync(id); }
                else {
                    Dictionary<string, object> doc = await Task.Run(delegate { return desktopApi.GetConfiguration(scenario, null); });
                    if (IsDisposed || version != nativeDemoVersion || SelectedScenario != scenario) return;
                    StartNativeDraft((Dictionary<string, object>)doc["draft"]);
                }
            } catch (Exception ex) { SetNativeWorkState("演示打开失败", false); NativeIssue("演示打开失败", ex); }
        }

        public void PrepareLiveVerification(string runId = null)
        {
            // A fixed run must not be replaced by the catalog's convenience default.
            if (!string.IsNullOrEmpty(runId))
            {
                nativeSuppressAutoDemo = true;
                suppressFullEventLoad = true;
            }
        }

        public bool LoadRunForVerification(string runId)
        {
            if (desktopApi == null || desktopCatalog == null ||
                string.IsNullOrEmpty(runId)) return false;
            LoadRunAsync(runId);
            return true;
        }

        public string CurrentRunIdForVerification { get { return desktopRunId; } }

        private void LoadRunAsync(string runId)
        {
            if (desktopApi == null || string.IsNullOrEmpty(runId)) return;
            int version = ++desktopLoadVersion;
            SetTaskViewStatus("场景视图：正在载入运行 " + runId + "…");
            Task.Run(delegate
            {
                try
                {
                    DesktopRunView run = desktopApi.GetRun(runId, null);
                    Ui(delegate { if (version == desktopLoadVersion) ApplyRun(run); });
                }
                catch (Exception ex)
                {
                    Ui(delegate { if (version != desktopLoadVersion) return; SetNativeWorkState("结果载入失败", false); SetTaskViewStatus("场景视图：运行载入失败。" + ex.Message); LogDesktop("运行载入失败：" + ex.Message); });
                }
            });
        }

        private void ApplyRun(DesktopRunView run)
        {
            desktopRun = run;
            desktopRunId = run.Id;
            sceneTaskProgress.Clear();
            if (taskGrid != null)
            {
                taskGrid.Rows.Clear();
                foreach (DesktopTask task in run.Tasks)
                {
                    string window = "—";
                    if (task.Window != null && task.Window.Length >= 2)
                        window = task.Window[0].ToString("0") + "–" + task.Window[1].ToString("0") + " s";
                    taskGrid.Rows.Add(task.Id, task.Label, TaskTypeCode(task),
                        StatusText(string.IsNullOrEmpty(task.StatusAt) ? task.Status : task.StatusAt),
                        task.Assigned.Count == 0 ? "等待分配" : string.Join(" · ", task.Assigned.ToArray()),
                        window);
                }
            }
            if (platformGrid != null)
            {
                RefreshNativePlatforms(run);
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
            UpdateSceneRunSummary();
            if (status != null) status.Text = "已载入真实运行 " + run.Id + "（" + run.End.ToString("0.0") + " s）";
            ApplyNativeRun(run);
            UpdateReconRecordNotice();
            SetNativeWorkState("结果已载入 · " + run.Done + "/" + run.Total, false);
            double startAt = 0;
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
            root.Text = run.Scenario + " · 真实运行";
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
                var used = ParticipatingPlatforms(run);
                platformsNode.Text = "平台 (本轮使用 " + used.Count + ")";
                platformsNode.Nodes.Clear();
                foreach (DesktopPlatform platform in used)
                {
                    platformsNode.Nodes.Add(new TreeNode(platform.Id + " " + platform.Kind +
                        (string.IsNullOrEmpty(platform.Job) ? "" : " · " + platform.Job)) { Tag = "desktop:platform:" + platform.Id });
                }
                platformsNode.Expand();
            }
        }

        private void SelectDesktopTask(string taskId, bool notifyRenderer = true)
        {
            if (notifyRenderer) nativeSelectedPlatformId = "";
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
                double percent = SceneTaskPercent(task.Id, task.Work > 0 ? Math.Max(0, Math.Min(100, task.Progress / task.Work * 100)) : 0);
                properties.SelectedObject = new TaskProperties
                {
                    Id = task.Id,
                    Name = task.Label,
                    Type = TaskTypeCode(task),
                    Area = "真实运行 · " + desktopRunId,
                    Start = start,
                    End = end,
                    Travel = "—",
                    Members = task.Assigned.Count == 0 ? "等待分配" : string.Join(" · ", task.Assigned.ToArray()),
                    Position = position,
                    Objective = ObjectiveDisplayName(desktopRun.Objective),
                    Phase = StatusText(string.IsNullOrEmpty(task.StatusAt) ? task.Status : task.StatusAt),
                    Progress = percent.ToString("0") + "%",
                    Source = "本地真实运行记录"
                };
                if (selectedTitle != null) selectedTitle.Text = "任务 " + task.Id + " · " + task.Label;
                if (taskProgress != null) taskProgress.Value = (int)Math.Round(percent);
            }
            if (taskGrid != null)
            {
                foreach (DataGridViewRow row in taskGrid.Rows)
                {
                    if (Convert.ToString(row.Cells[0].Value) == taskId)
                    {
                        row.Selected = true;
                        if (row.Visible) taskGrid.CurrentCell = row.Cells[0];
                        break;
                    }
                }
            }
            if (notifyRenderer) Bridge("selectTask(" + desktopJson.Serialize(taskId) + ")");
            if (status != null) status.Text = "已选择任务 " + task.Id + " · " + task.Label;
        }

        private void UpdateSceneRunSummary()
        {
            if (desktopRun == null) return;
            SetTaskViewStatus("本轮目标：" + ObjectiveDisplayName(desktopRun.Objective) + " · 运行 " + desktopRun.Id + " · " + desktopRun.Done + "/" + desktopRun.Total + " 完成 · " + desktopRun.End.ToString("0.0") + " s");
        }

        private static string ObjectiveDisplayName(string objective)
        {
            switch ((objective ?? "").Trim()) {
                case "makespan": case "timeliness": return "完工时间";
                case "energy": return "能耗";
                case "balanced": return "均衡";
                case "exposure": case "dispersion": return "暴露度";
                case "": return "未记录";
                default: return "未知（" + objective + "）";
            }
        }

        private static string StatusText(string status)
        {
            switch ((status ?? "").ToLowerInvariant())
            {
                case "succeeded": return "已完成";
                case "running": return "执行中";
                case "progress": return "执行中";
                case "idle": return "待命";
                case "cancelled": return "已取消";
                case "travel": return "机动中";
                case "return": return "返航中";
                case "returned": return "已返回出发点";
                case "failed": return "失败";
                case "timeout": return "超时";
                case "pending": return "待开始";
                default: return status ?? "";
            }
        }

        private bool documentsShowTaskView()
        {
            return Documents != null && taskViewTab != null && Documents.SelectedTab == taskViewTab;
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
                            SyncSceneClock(state);
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
            if (IsDisposed || Disposing) return;
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
            CaptureLiveVerification(directory, double.NaN);
        }

        public async Task CaptureReplayVerification(string directory, double captureTime)
        {
            Directory.CreateDirectory(directory);
            if (!webReady || desktopRun == null)
                throw new InvalidOperationException("场景渲染器或真实运行尚未就绪。");
            OpenTaskView();
            await Task.Delay(900);
            if (WindowState != FormWindowState.Normal) WindowState = FormWindowState.Normal;
            Size = new Size(1500, 940);
            TopMost = true;
            SetForegroundWindow(Handle);
            Activate();
            BringToFront();
            Application.DoEvents();
            await Task.Delay(900);
            Application.DoEvents();
            Task<string> stateTask = webView.CoreWebView2.ExecuteScriptAsync(
                "(function(){var api=window.MarlDesktop;if(!api)return '{}';" +
                "api.pause();api.setTime(" +
                captureTime.ToString(CultureInfo.InvariantCulture) +
                ");api.fit('area');var s=api.getState();" +
                "return JSON.stringify({runId:s.runId,time:s.time," +
                "duration:s.duration,cameraBounds:s.cameraBounds,layers:s.layers});})()");
            if (await Task.WhenAny(stateTask, Task.Delay(6000)) != stateTask)
                throw new TimeoutException("场景视图状态请求超过 6 秒。");
            string state = await stateTask;
            File.WriteAllText(
                Path.Combine(directory, "replay-state.json"),
                state,
                new UTF8Encoding(false));
            await Task.Delay(500);
            Application.DoEvents();
            using (Bitmap windowBitmap = new Bitmap(Width, Height))
            using (Graphics windowGraphics = Graphics.FromImage(windowBitmap))
            {
                windowGraphics.CopyFromScreen(Location, Point.Empty, Size);
                windowBitmap.Save(
                    Path.Combine(directory, "replay-window.png"),
                    System.Drawing.Imaging.ImageFormat.Png);
            }
            Task<string> screenshotTask = webView.CoreWebView2.CallDevToolsProtocolMethodAsync(
                "Page.captureScreenshot",
                "{\"format\":\"png\",\"fromSurface\":true,\"captureBeyondViewport\":false}");
            if (await Task.WhenAny(screenshotTask, Task.Delay(10000)) != screenshotTask)
                throw new TimeoutException("场景视图截图请求超过 10 秒。");
            string screenshotJson = await screenshotTask;
            Dictionary<string, object> screenshotResult =
                desktopJson.Deserialize<Dictionary<string, object>>(screenshotJson);
            object screenshotDataValue;
            if (screenshotResult == null ||
                !screenshotResult.TryGetValue("data", out screenshotDataValue) ||
                screenshotDataValue == null)
                throw new InvalidOperationException("场景视图截图未返回图像数据。");
            try
            {
                File.WriteAllBytes(
                    Path.Combine(directory, "replay-frame.png"),
                    Convert.FromBase64String(Convert.ToString(screenshotDataValue)));
            }
            catch (FormatException ex)
            {
                throw new InvalidOperationException("场景视图截图数据格式无效。", ex);
            }
            TopMost = false;
        }

        public void CaptureLiveVerification(string directory, double captureTime)
        {
            Directory.CreateDirectory(directory);
            File.WriteAllText(Path.Combine(directory, "readiness.txt"), "web_ready=" + webReady + "\r\nrun=" + desktopRunId + "\r\n" + (taskViewStatus == null ? "" : taskViewStatus.Text) + "\r\n" + (log == null ? "" : log.Text));
            if (!webReady || desktopRun == null) throw new InvalidOperationException("场景渲染器或真实运行尚未就绪，不能记为验证通过。");
            Bridge("pause()");
            VerifyMapControls(directory);
            VerifyLayerMenus(directory);
            VerifyNativeWorkflow(directory);
            if (!double.IsNaN(captureTime))
            {
                OpenTaskView();
                WaitMapTask(webView.CoreWebView2.ExecuteScriptAsync(
                    "(function(){var api=window.MarlDesktop;if(!api)throw Error('Desktop bridge missing');" +
                    "api.pause();api.fit('all');api.setTime(" +
                    captureTime.ToString(CultureInfo.InvariantCulture) +
                    ");return JSON.stringify(api.getState());})()"));
                Application.DoEvents();
            }
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
            Documents.SelectedIndex = 0;
            Application.DoEvents();
            using (Bitmap bitmap = new Bitmap(Width, Height))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(Location, Point.Empty, Size);
                bitmap.Save(Path.Combine(directory, "live-task-properties.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
            Documents.SelectedIndex = 1;
            Application.DoEvents();
            using (Bitmap bitmap = new Bitmap(Width, Height))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(Location, Point.Empty, Size);
                bitmap.Save(Path.Combine(directory, "live-platforms.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
            Documents.SelectedTab = taskViewTab;
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
                        "JSON.stringify((function(){var c=document.querySelector('#ck-canvas');var s=document.querySelector('#scene');var r=c?c.getBoundingClientRect():null;var b=s?s.getBoundingClientRect():null;return {ck:r?[r.width,r.height]:null,scene:b?[b.width,b.height]:null,hostChildren:document.querySelector('#desktop-scene-host')?.children.length,hostCanvas:!!document.querySelector('#desktop-scene-host>canvas'),scroll:document.documentElement.scrollHeight>innerHeight,css:c?getComputedStyle(c).backgroundColor:null,page:getComputedStyle(document.body).backgroundColor};})())");
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
                "capture_time=" + (!double.IsNaN(captureTime) ? captureTime.ToString(CultureInfo.InvariantCulture) : "native-verification-end"),
                "tasks=" + (desktopRun == null ? 0 : desktopRun.Tasks.Count),
                "platforms=" + (desktopRun == null ? 0 : desktopRun.Platforms.Count),
                "native_tabs=" + Documents.TabPages.Count,
                "native_time=" + Time.ToString(CultureInfo.InvariantCulture),
                "native_playing=" + webPlaying,
                "task_view_status=" + (taskViewStatus == null ? "" : taskViewStatus.Text),
                "status=" + (status == null ? "" : status.Text),
                "bounds=" + Location.X + "," + Location.Y + "," + Width + "," + Height
            };
            File.WriteAllLines(Path.Combine(directory, "live-verification.txt"), lines, new UTF8Encoding(false));
            TopMost = false;
        }

        public bool ReadyForDesktopVerification { get { return webReady && desktopRun != null; } }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        private void ShowAboutDesktop()
        {
            MessageBox.Show(this,
                "多智能体协同规划系统\n本地桌面开发版\n\n" +
                "本软件用于展示规划中间层的任务规划、分配、执行与回放能力。\n" +
                "真实平台展示目标是接入下层 Gazebo，并在 UE5 中呈现；\n" +
                "当前版本为本地演示，不代表真实平台联调完成。\n\n" +
                "运行数据来自本机 planning_middle_demo 后端，原生场景视图\n" +
                "承载真实地图；配置、事件、文件和报告由原生控件承载。",
                "关于", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

}
