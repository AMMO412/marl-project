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

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private Dictionary<string, object> nativeDraft;
        private string nativeDraftSourceRunId;
        private enum NativeConfigurationMode { CurrentScene, NewScene, Draft, CopyRun }
        private string nativeSelectedPlatformId = "";
        private bool nativeRunning, nativeConfigurationLoading, nativeRunPreparing;
        private bool suppressFullEventLoad;
        private ToolStripStatusLabel nativeWorkStatus;
        private ToolStripProgressBar nativeWorkProgress;
        private System.Windows.Forms.Timer nativeWorkTimer;
        private DateTime nativeWorkStarted;
        private void SetNativeWorkState(string text, bool busy)
        {
            if (IsDisposed || Disposing || nativeWorkStatus == null) return;
            if (nativeWorkTimer != null) { nativeWorkTimer.Stop(); nativeWorkTimer.Dispose(); nativeWorkTimer = null; }
            nativeWorkStatus.Text = text;
            nativeWorkStatus.ForeColor = busy ? Color.FromArgb(31,111,195) : Color.FromArgb(47,130,96);
            nativeWorkProgress.Visible = busy;
            if (busy) {
                nativeWorkStarted = DateTime.UtcNow;
                nativeWorkTimer = new System.Windows.Forms.Timer { Interval = 500 };
                nativeWorkTimer.Tick += delegate { nativeWorkStatus.Text = text + " · " + (DateTime.UtcNow-nativeWorkStarted).TotalSeconds.ToString("0") + " s"; };
                nativeWorkTimer.Start();
            }
        }
        private DataGridView nativeEvents;
        private ListView nativeFiles;
        private TextBox nativeEventSearch, nativeTaskSearch, nativePlatformSearch, nativeHistorySearch;
        private CheckBox nativeCurrentEvents;
        private readonly List<DesktopEvent> nativeAllEvents = new List<DesktopEvent>();
        private string lastNativeEventKey = "";

        private string SelectedScenario { get { return scenarioBox == null || scenarioBox.SelectedItem == null ? "interop_containment" : Convert.ToString(scenarioBox.SelectedItem); } }
        private void NativeIssue(string operation, Exception ex)
        {
            if (IsDisposed || Disposing) return;
            LogDesktop(operation + "：" + ex.Message); status.Text = operation + "：" + ex.Message;
            MessageBox.Show(this, ex.Message, operation, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        private bool HasNativeBackend()
        { if (desktopApi != null) return true; status.Text = "后端尚未连接，请查看运行日志。"; return false; }

        private async Task<Dictionary<string, object>> ReadNativeConfiguration(NativeConfigurationMode mode, string copyRunId = null)
        {
            string runId = mode == NativeConfigurationMode.CurrentScene || mode == NativeConfigurationMode.CopyRun
                ? (copyRunId ?? (desktopRun == null ? null : desktopRun.Id)) : null;
            string key = !string.IsNullOrEmpty(runId) && desktopRun != null && desktopRun.Id == runId
                ? desktopRun.Scenario : SelectedScenario;
            bool useDraft = nativeDraft != null && (mode == NativeConfigurationMode.Draft ||
                (mode == NativeConfigurationMode.CurrentScene && nativeDraftSourceRunId == runId &&
                 Convert.ToString(((Dictionary<string, object>)nativeDraft["request"])["scenario"]) == key));
            Dictionary<string, object> doc;
            if (useDraft)
                doc = new Dictionary<string, object> {
                    { "draft", desktopJson.DeserializeObject(desktopJson.Serialize(nativeDraft)) },
                    { "input_source", "desktop_draft" },
                    { "note", "已应用的待运行草稿；修改用于新运行，已载入的回放记录保持原样。" } };
            else doc = await Task.Run(delegate { return desktopApi.GetConfiguration(key, runId); });
            doc["run_id"] = mode == NativeConfigurationMode.Draft ? nativeDraftSourceRunId : runId;
            return doc;
        }

        private async void ShowNativeConfiguration(NativeConfigurationMode mode, string copyRunId = null)
        {
            if (!HasNativeBackend() || nativeConfigurationLoading) return;
            nativeConfigurationLoading = true;
            try
            {
                status.Text = "读取运行配置…";
                Dictionary<string, object> doc = await ReadNativeConfiguration(mode, copyRunId);
                if (IsDisposed) return;
                using (NativeRunConfiguration dialog = new NativeRunConfiguration(desktopApi, desktopCatalog, doc))
                {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return;
                    nativeDraft = dialog.Draft;
                    nativeDraftSourceRunId = dialog.SourceRunId;
                    if (string.IsNullOrEmpty(nativeDraftSourceRunId)) nativeDraftSourceRunId = null;
                    scenarioBox.SelectedItem = Convert.ToString(((Dictionary<string, object>)nativeDraft["request"])["scenario"]);
                    status.Text = "配置已应用；原运行未改变。";
                    if (dialog.RunRequested) StartNativeDraft(nativeDraft);
                }
            }
            catch (Exception ex) { NativeIssue("读取配置失败", ex); }
            finally { nativeConfigurationLoading = false; }
        }

        private async void ImportNativeConfiguration()
        {
            if (!HasNativeBackend()) return;
            using (OpenFileDialog open = new OpenFileDialog { Filter = "桌面运行配置 (*.json)|*.json", Title = "导入桌面配置" })
            {
                if (open.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    if (new FileInfo(open.FileName).Length > 1024 * 1024) throw new InvalidOperationException("配置超过 1 MB 限制。");
                    object input = new JavaScriptSerializer { MaxJsonLength = 1024 * 1024 }.DeserializeObject(File.ReadAllText(open.FileName, Encoding.UTF8));
                    Dictionary<string, object> checkedInput = await Task.Run(delegate { return desktopApi.ValidateDraft(input); });
                    nativeDraft = (Dictionary<string, object>)checkedInput["draft"];
                    nativeDraftSourceRunId = null;
                    scenarioBox.SelectedItem = Convert.ToString(((Dictionary<string, object>)nativeDraft["request"])["scenario"]);
                    ShowNativeConfiguration(NativeConfigurationMode.Draft);
                }
                catch (Exception ex) { NativeIssue("导入配置失败", ex); }
            }
        }
        private async void ExportNativeConfiguration()
        {
            if (!HasNativeBackend()) return;
            try
            {
                object draft = nativeDraft; string key = SelectedScenario;
                if (draft == null || Convert.ToString(((Dictionary<string, object>)nativeDraft["request"])["scenario"]) != key) { Dictionary<string, object> doc = await Task.Run(delegate { return desktopApi.GetConfiguration(key, null); }); draft = doc["draft"]; }
                using (SaveFileDialog save = new SaveFileDialog { Filter = "桌面运行配置 (*.json)|*.json", FileName = "desktop-config.json" }) if (save.ShowDialog(this) == DialogResult.OK) File.WriteAllText(save.FileName, DesktopApi.Pretty(draft), new UTF8Encoding(false));
            }
            catch (Exception ex) { NativeIssue("导出配置失败", ex); }
        }
        private async void CheckNativeInput()
        {
            if (!HasNativeBackend()) return;
            try
            {
                object draft = nativeDraft; string key = SelectedScenario;
                if (draft == null || Convert.ToString(((Dictionary<string, object>)nativeDraft["request"])["scenario"]) != key) { Dictionary<string, object> doc = await Task.Run(delegate { return desktopApi.GetConfiguration(key, null); }); draft = doc["draft"]; }
                Dictionary<string, object> response = await Task.Run(delegate { return desktopApi.ValidateDraft(draft); });
                ShowNativeDocument("输入校验结果", new Dictionary<string, object> { { "契约检查通过（尚未执行）", response } });
            }
            catch (Exception ex) { NativeIssue("输入检查未通过", ex); }
        }
        private async void RunSelectedScenario()
        {
            if (!HasNativeBackend() || nativeRunning || nativeRunPreparing) return;
            nativeRunPreparing = true; SetNativeWorkState("正在读取任务配置…", true);
            try
            {
                Dictionary<string, object> draft = nativeDraft; string key = SelectedScenario;
                if (draft == null || Convert.ToString(((Dictionary<string, object>)draft["request"])["scenario"]) != key)
                { Dictionary<string, object> doc = await Task.Run(delegate { return desktopApi.GetConfiguration(key, null); }); draft = (Dictionary<string, object>)doc["draft"]; }
                StartNativeDraft(draft);
            }
            catch (Exception ex) { SetNativeWorkState("启动失败", false); NativeIssue("启动失败", ex); }
            finally { nativeRunPreparing = false; }
        }
        private async void StartNativeDraft(Dictionary<string, object> input)
        {
            if (nativeRunning) { status.Text = "已有运行正在进行，请等待结束。"; return; }
            nativeRunning = true; desktopRunButton.Enabled = false; scenarioBox.Enabled = false;
            SetNativeWorkState("正在校验并创建任务…", true);
            // Freeze the draft before returning to the UI; edits affect future runs only.
            object snapshot = desktopJson.DeserializeObject(desktopJson.Serialize(input));
            try
            {
                Dictionary<string,object> refreshed = await Task.Run(delegate { return desktopApi.RefreshPreset(snapshot); });
                snapshot=refreshed["draft"];
                if(Convert.ToBoolean(refreshed["refreshed"]) || (refreshed.ContainsKey("task_randomized") && Convert.ToBoolean(refreshed["task_randomized"]))) { nativeDraft=(Dictionary<string,object>)snapshot;LogDesktop(Convert.ToString(refreshed["note"])); }
                string id = await Task.Run(delegate { return desktopApi.StartDraft(snapshot); });
                SetNativeWorkState("规划与仿真中…", true);
                status.Text = "后台运行中：" + id + "；可继续查看已有记录。"; LogDesktop("新运行已创建：" + id);
                for (int i = 0; i < 180 && !IsDisposed; i++)
                {
                    await Task.Delay(1000);
                    DesktopCatalog catalog = await Task.Run(delegate { return desktopApi.GetCatalog(); });
                    if (IsDisposed) return;
                    DesktopRunSummary created = catalog.Runs.FirstOrDefault(delegate(DesktopRunSummary row) { return row.Id == id; });
                    if (created != null && !catalog.ProcessRunning) { ApplyCatalog(catalog); SetNativeWorkState("运行已完成，正在载入结果…", true); LoadRunAsync(id); return; }
                    if (catalog.ProcessId == id && catalog.ProcessState == "error")
                    {
                        byte[] bytes = await Task.Run(delegate { return desktopApi.DownloadArtifact(id, "worker.log"); });
                        ShowNativeDocument("后台运行失败 · " + id, new Dictionary<string, object> { { "worker.log", Encoding.UTF8.GetString(bytes) } });
                        throw new InvalidOperationException("后台运行失败，已保留输入和日志：" + id);
                    }
                }
                SetNativeWorkState("运行耗时较长，请查看日志", false);
                status.Text = "运行仍未返回完整记录。请刷新运行目录并查看日志，勿重复启动。";
            }
            catch (Exception ex) { SetNativeWorkState("运行失败，请查看日志", false); NativeIssue("运行失败", ex); }
            finally { nativeRunning = false; if (!IsDisposed) { desktopRunButton.Enabled = true; scenarioBox.Enabled = true; } }
        }

        private Control BuildNativeOutput()
        {
            TabControl tabs = new TabControl { Name="NativeOutputTabs", Dock = DockStyle.Fill, Padding = new Point(13, 5) };
            TabPage logs = NewTab("运行日志"), events = NewTab("消息列表"), files = NewTab("输出文件");
            log = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, WordWrap = false, BorderStyle = BorderStyle.None, BackColor = Color.White, ForeColor = Color.FromArgb(83, 108, 138), Font = new Font("Consolas", 9f), Text = "正在连接本地后端…\r\n" }; logs.Controls.Add(log);
            nativeEvents = NewGrid(); foreach (string name in new string[] { "时刻 / s", "事件", "对象", "说明" }) nativeEvents.Columns.Add(name, name);
            nativeEvents.CellDoubleClick += delegate(object sender, DataGridViewCellEventArgs e) { if (e.RowIndex < 0) return; DesktopEvent item = nativeEvents.Rows[e.RowIndex].Tag as DesktopEvent; if (item == null) return; SetPlaying(false); OpenTaskView(); SetTime(item.Time); if (desktopRun != null && desktopRun.FindTask(item.JobId) != null) SelectDesktopTask(item.JobId); };
            Panel filter = new Panel { Dock = DockStyle.Top, Height = 30, Padding = new Padding(5, 3, 5, 2) };
            nativeEventSearch = new TextBox { Width = 240, Dock = DockStyle.Left }; nativeCurrentEvents = new CheckBox { Dock = DockStyle.Right, Width = 165, Text = "仅当前时刻之前", Checked = true };
            nativeEventSearch.TextChanged += delegate { RefreshNativeEvents(); }; nativeCurrentEvents.CheckedChanged += delegate { RefreshNativeEvents(); }; filter.Controls.Add(nativeEventSearch); filter.Controls.Add(nativeCurrentEvents);
            events.Controls.Add(nativeEvents); events.Controls.Add(filter);
            nativeFiles = new ListView { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, MultiSelect = false, BorderStyle = BorderStyle.None, ShowItemToolTips=true }; nativeFiles.Columns.Add("文件名（双击预览）", 210); nativeFiles.Columns.Add("格式", 60); nativeFiles.Columns.Add("内容说明",400);
            nativeFiles.SizeChanged+=delegate {nativeFiles.Columns[2].Width=Math.Max(200,nativeFiles.ClientSize.Width-295);};
            nativeFiles.DoubleClick += delegate { PreviewNativeFile(); }; files.Controls.Add(nativeFiles);
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 35, Padding = new Padding(5, 3, 0, 0) };
            Button preview = StandardButton("预览", 65), save = StandardButton("另存为…", 90), report = StandardButton("运行报告", 90), chain = StandardButton("全链路追溯", 108);
            Button agentTasks=StandardButton("单平台任务明细",130);agentTasks.Name="OpenAgentTaskDetails";agentTasks.Click+=delegate {PreviewNativeArtifact("agent_tasks.md");};actions.Controls.Add(agentTasks);
            chain.Name = "NativeOpenChainTrace";
            CheckBox allArtifacts=new CheckBox {Name="ShowAllArtifacts",Text="显示全部",Width=86,Height=25};
            allArtifacts.CheckedChanged+=delegate {showAllArtifacts=allArtifacts.Checked;if(desktopRun!=null)RefreshNativeFiles(desktopRun);};
            preview.Click += delegate { PreviewNativeFile(); }; save.Click += delegate { SaveNativeFile(); }; report.Click += delegate { ShowNativeReport(); }; chain.Click += delegate { ShowNativeChain(); }; actions.Controls.AddRange(new Control[] { preview, save, report, chain, allArtifacts }); files.Controls.Add(actions);
            tabs.TabPages.AddRange(new TabPage[] { logs, events, files }); return tabs;
        }
        private void InitializeNativeInteractions()
        {
            nativeTaskSearch = AddNativeSearch(taskGrid.Parent, "输入编号、名称、状态筛选任务"); nativeTaskSearch.TextChanged += delegate { FilterNativeGrid(taskGrid, nativeTaskSearch.Text); };
            nativePlatformSearch = AddNativeSearch(platformGrid.Parent, "输入编号、类型、任务筛选平台"); nativePlatformSearch.TextChanged += delegate { FilterNativeGrid(platformGrid, nativePlatformSearch.Text); };
            taskGrid.CellClick += delegate(object sender, DataGridViewCellEventArgs e) { if (e.RowIndex >= 0 && desktopRun != null) SelectDesktopTask(Convert.ToString(taskGrid.Rows[e.RowIndex].Cells[0].Value)); };
            platformGrid.CellClick += delegate(object sender, DataGridViewCellEventArgs e) { if (e.RowIndex >= 0) SelectNativePlatform(Convert.ToString(platformGrid.Rows[e.RowIndex].Cells[0].Value), false); };
            platformGrid.CellDoubleClick += delegate(object sender, DataGridViewCellEventArgs e) { if (e.RowIndex >= 0) SelectNativePlatform(Convert.ToString(platformGrid.Rows[e.RowIndex].Cells[0].Value), true); };
            nativeHistorySearch = AddNativeSearch(history.Parent, "筛选运行编号、场景、优化目标或状态"); nativeHistorySearch.TextChanged += delegate { RefreshNativeHistoryFilter(); };
            Panel oldActions = history.Parent.Controls.OfType<Panel>().FirstOrDefault(delegate(Panel panel) { return panel.Dock == DockStyle.Bottom; });
            if (oldActions != null)
            {
                while (oldActions.Controls.Count > 0) oldActions.Controls[0].Dispose();
                FlowLayoutPanel row = new FlowLayoutPanel { Dock = DockStyle.Fill };
                Button load = StandardButton("打开回放", 90), clone = StandardButton("复制配置…", 100), report = StandardButton("运行报告", 90), chain = StandardButton("全链路追溯", 108);
                chain.Name = "HistoryOpenChainTrace";
                load.Click += delegate { LoadSelectedNativeRun(); }; clone.Click += delegate { if (history.SelectedItems.Count == 0) return; ShowNativeConfiguration(NativeConfigurationMode.CopyRun, Convert.ToString(history.SelectedItems[0].Tag)); };
                report.Click += delegate { if (history.SelectedItems.Count > 0) ShowNativeReport(Convert.ToString(history.SelectedItems[0].Tag)); };
                chain.Click += delegate { if (history.SelectedItems.Count > 0) ShowNativeChain(Convert.ToString(history.SelectedItems[0].Tag)); }; row.Controls.AddRange(new Control[] { load, clone, report, chain });
                Button delete=StandardButton("删除记录",90), undo=StandardButton("恢复上次删除",110), folder=StandardButton("打开存储目录",110);delete.Name="DeleteRunRecord";undo.Name="RestoreRunRecord";folder.Name="OpenRecordsFolder";
                delete.Click+=delegate { DeleteSelectedRecord(); };undo.Click+=delegate { RestoreLastRecord(); };folder.Click+=delegate { OpenRecordsFolder(); };
                row.Controls.AddRange(new Control[]{delete,undo,folder});oldActions.Controls.Add(row);
                Button compareRuns=StandardButton("同场景目标对比",130);compareRuns.Name="CompareSavedRuns";
                compareRuns.Click+=delegate {ShowNativeRunComparison();};row.Controls.Add(compareRuns);
                row.Controls.SetChildIndex(compareRuns,0);oldActions.Height=80;
            }
        }
        private TextBox AddNativeSearch(Control parent, string hint)
        {
            Panel row = new Panel { Dock = DockStyle.Top, Height = 32, Padding = new Padding(6, 4, 6, 3), BackColor = Color.FromArgb(248, 251, 254) };
            Label label = new Label { Text = "筛选", Dock = DockStyle.Left, Width = 36, TextAlign = ContentAlignment.MiddleLeft }; TextBox search = new TextBox { Dock = DockStyle.Fill };
            new ToolTip().SetToolTip(search, hint); row.Controls.Add(search); row.Controls.Add(label); parent.Controls.Add(row); return search;
        }
        private static void FilterNativeGrid(DataGridView grid, string text)
        {
            string needle = text.Trim().ToLowerInvariant(); grid.CurrentCell = null;
            foreach (DataGridViewRow row in grid.Rows) row.Visible = needle.Length == 0 || row.Cells.Cast<DataGridViewCell>().Any(delegate(DataGridViewCell cell) { return Convert.ToString(cell.Value).ToLowerInvariant().Contains(needle); });
        }
        private void RefreshNativeHistoryFilter()
        {
            if (desktopCatalog == null || nativeHistorySearch == null) return;
            string needle = nativeHistorySearch.Text.Trim().ToLowerInvariant();
            history.BeginUpdate(); history.Items.Clear();
            foreach (DesktopRunSummary run in desktopCatalog.Runs)
            {
                string[] columns = NativeHistoryColumns(run);
                if (!(string.Join(" ", columns)+" "+run.Objective).ToLowerInvariant().Contains(needle)) continue;
                ListViewItem item = new ListViewItem(columns) { Tag = run.Id }; history.Items.Add(item); if (run.Id == desktopRunId) item.Selected = true;
            }
            history.EndUpdate();
        }
        private string[] NativeHistoryColumns(DesktopRunSummary run)
        {
            string label;if(!desktopCatalog.Scenarios.TryGetValue(run.Scenario??"",out label))label=run.Scenario;
            return new[]{run.Id,label,ObjectiveDisplayName(run.Objective),
                "逐步运动"+(run.Behavior?" · 到位行为":""),run.Done+"/"+run.Total};
        }
        private void ApplyNativeRun(DesktopRunView run)
        {
            Time = run.At; PlaybackEnd = run.End;
            refreshing = true; timeline.Maximum = Math.Max(1, (int)Math.Ceiling(run.End * 10)); timeline.Value = Math.Min(timeline.Maximum, (int)Math.Round(Time * 10)); refreshing = false;
            clock.Text = Time.ToString("0.0") + " / " + PlaybackEnd.ToString("0.0") + " s";
            UpdateAircraftAltitude();
            nativeSelectedPlatformId = "";
            nativeAllEvents.Clear(); nativeAllEvents.AddRange(run.Events);
            RefreshNativeFiles(run);
            if (nativeFiles.Items.Count > 0) nativeFiles.Items[0].Selected = true;
            string label; if (desktopCatalog == null || !desktopCatalog.Scenarios.TryGetValue(run.Scenario, out label)) label = run.Scenario;
            Text = "多智能体协同规划系统 — " + label;
            tree.Nodes[0].Text = label; tree.Nodes[0].ToolTipText = run.Id;
            if (scenarioBox != null && scenarioBox.Items.Contains(run.Scenario))
                scenarioBox.SelectedItem = run.Scenario;
            nativeTaskSearch.Text = nativePlatformSearch.Text = "";
            RefreshNativeEvents();
            if (!suppressFullEventLoad) LoadAllNativeEvents(run.Id);
        }
        private void RefreshNativeEvents()
        {
            if (nativeEvents == null || nativeEventSearch == null) return;
            string needle = nativeEventSearch.Text.Trim().ToLowerInvariant();
            List<DesktopEvent> visible = nativeAllEvents.Where(delegate(DesktopEvent item) {
                if (nativeCurrentEvents.Checked && item.Time > Time + .001) return false;
                return (EventTitle(item.Kind) + " " + item.JobId + " " + item.Label + " " + item.Kind + " " + item.Time.ToString(CultureInfo.InvariantCulture)).ToLowerInvariant().Contains(needle);
            }).ToList();
            string key = desktopRunId + "|" + needle + "|" + string.Join(";", visible.Select(delegate(DesktopEvent item) { return item.Time.ToString(CultureInfo.InvariantCulture) + item.Kind + item.JobId; }).ToArray());
            if (key == lastNativeEventKey) return;
            lastNativeEventKey = key;
            int first = nativeEvents.FirstDisplayedScrollingRowIndex;
            nativeEvents.Rows.Clear();
            foreach (DesktopEvent item in visible)
            {
                int row = nativeEvents.Rows.Add(item.Time.ToString("0.0"), EventTitle(item.Kind), item.JobId, string.IsNullOrEmpty(item.Label) ? item.Kind : item.Label); nativeEvents.Rows[row].Tag = item;
            }
            if (first >= 0 && first < nativeEvents.Rows.Count) nativeEvents.FirstDisplayedScrollingRowIndex = first;
        }
        private async void LoadAllNativeEvents(string id)
        {
            try { List<DesktopEvent> events = await Task.Run(delegate { return desktopApi.GetAllEvents(id); }); if (IsDisposed || desktopRunId != id) return; nativeAllEvents.Clear(); nativeAllEvents.AddRange(events); lastNativeEventKey = ""; RefreshNativeEvents(); }
            catch (Exception ex) { LogDesktop("读取完整事件失败：" + ex.Message); }
        }
        private void ShowNativeEventDetail()
        {
            if (nativeEvents.CurrentRow == null) { status.Text = "请先在消息列表选择事件。"; return; }
            DesktopEvent item = nativeEvents.CurrentRow.Tag as DesktopEvent;
            if (item != null) ShowNativeDocument("事件详情 · " + item.Time.ToString("0.0") + " s", new Dictionary<string, object> { { "真实事件记录", item.Raw ?? (object)new { time = item.Time, kind = item.Kind, job = item.JobId, label = item.Label } } });
        }
        private static string EventTitle(string kind)
        {
            switch (kind) { case "plan_emitted": return "规划生成"; case "job_dispatched": return "任务下发"; case "job_succeeded": return "任务完成"; case "job_failed": return "任务失败"; case "job_requeued": return "任务重新排队"; case "member_lost": return "成员失联"; case "timeout": return "超时"; case "behavior_event": return "行为事件"; case "feedback_applied": return "执行反馈"; default: return kind; }
        }
        private void LoadSelectedNativeRun() { if (history.SelectedItems.Count > 0) LoadRunAsync(Convert.ToString(history.SelectedItems[0].Tag)); }
        private void SelectNativePlatform(string id, bool locate)
        {
            if (desktopRun == null) return; DesktopPlatform platform = desktopRun.Platforms.FirstOrDefault(delegate(DesktopPlatform p) { return p.Id == id; }); if (platform == null) return;
            nativeSelectedPlatformId = id;
            selectedTitle.Text = platform.Id + " · " + platform.Kind;
            properties.SelectedObject = new NativePlatformProperties { Id = platform.Id, Kind = platform.Kind, Job = platform.Job, State = PlatformStateText(platform), Position = platform.Position == null ? "—" : string.Join(", ", platform.Position.Select(delegate(double n) { return n.ToString("0.00"); }).ToArray()), Altitude = platform.Z, Heading = platform.Yaw, Battery = platform.Battery, Objective = ObjectiveDisplayName(desktopRun.Objective) };
            if (locate) { OpenTaskView(); Bridge("focusPlatform(" + desktopJson.Serialize(id) + ")"); }
        }
        private void CycleNativeTask()
        { if (desktopRun == null || desktopRun.Tasks.Count == 0) return; int i = desktopRun.Tasks.FindIndex(delegate(DesktopTask t) { return t.Id == desktopTaskId; }); SelectDesktopTask(desktopRun.Tasks[(i + 1) % desktopRun.Tasks.Count].Id); }
        private void CopyNativeTask()
        { if (desktopRun == null) return; DesktopTask t = desktopRun.FindTask(desktopTaskId); if (t == null) return; try { Clipboard.SetText(t.Id + " · " + t.Label + "\r\n分配平台：" + string.Join(", ", t.Assigned.ToArray()) + "\r\n来源：" + desktopRunId); status.Text = "任务信息已复制。"; } catch (Exception ex) { NativeIssue("复制失败", ex); } }

        private void PreviewNativeFile()
        {
            if (nativeFiles.SelectedItems.Count == 0 || desktopRun == null) return;
            PreviewNativeArtifact(nativeFiles.SelectedItems[0].Text);
        }
        private async void PreviewNativeArtifact(string name)
        {
            if(desktopRun==null){status.Text="请先载入运行记录。";return;}
            if(!desktopRun.Files.Contains(name)){status.Text="本轮没有保存该文件："+name;return;}
            string id=desktopRunId;
            if (name == "chain_viewer.html") { ShowNativeChain(id); return; }
            if (name == "trajectory.html" || name == "behavior_demo.html") { OpenTaskView(); status.Text = "同轮轨迹已在场景视图中打开。"; return; }
            if (name == "report.html") { ShowNativeReport(id); return; }
            try { byte[] bytes = await Task.Run(delegate { return desktopApi.DownloadArtifact(id, name); }); string text = Encoding.UTF8.GetString(bytes, 0, Math.Min(bytes.Length, 1024 * 1024)); if (bytes.Length > 1024 * 1024) text += "\r\n\r\n预览截取前 1 MB；另存为可导出完整文件。"; ShowNativeDocument(name + " · " + id, new Dictionary<string, object> { { name, text } }); }
            catch (Exception ex) { NativeIssue("预览失败", ex); }
        }
        private async void SaveNativeFile()
        {
            if (nativeFiles.SelectedItems.Count == 0 || desktopRun == null) return; string name = nativeFiles.SelectedItems[0].Text, id = desktopRunId;
            using (SaveFileDialog save = new SaveFileDialog { FileName = name, Filter = "所有文件 (*.*)|*.*" })
            { if (save.ShowDialog(this) != DialogResult.OK) return; try { byte[] bytes = await Task.Run(delegate { return desktopApi.DownloadArtifact(id, name); }); File.WriteAllBytes(save.FileName, bytes); status.Text = "已导出 " + name; } catch (Exception ex) { NativeIssue("文件导出失败", ex); } }
        }
        private async void ShowNativeReport(string id = null)
        {
            if (!HasNativeBackend()) return; if (string.IsNullOrEmpty(id)) id = desktopRunId; if (string.IsNullOrEmpty(id)) return;
            try
            {
                Dictionary<string, object> details = await Task.Run(delegate { return desktopApi.GetDetails(id); });
                Dictionary<string, object> report = (Dictionary<string, object>)details["report"];
                Dictionary<string, object> summary = new Dictionary<string, object> { { "运行编号", id }, { "证据来源", "本地模拟记录；不表示外部平台验收" } };
                string[] keys = { "done", "settled", "all_succeeded", "limit_reached", "simulated_until_s", "objective", "mode", "motion", "used_energy", "retries", "timeouts" };
                string[] labels = { "完成任务数", "已结算", "全部成功", "达到仿真上限", "仿真时长 / s", "规划目标", "运行模式", "运动模式", "模型能耗", "重试次数", "超时次数" };
                for (int i = 0; i < keys.Length; i++) { object value; summary[labels[i]] = report.TryGetValue(keys[i], out value) ? value : "未记录"; }
                object agentText;
                if (!details.TryGetValue("agent_tasks_text", out agentText)) agentText = "本轮未记录单平台计划明细。";
                object bound;details.TryGetValue("execution_plan",out bound);
                object reference;details.TryGetValue("reference_plan",out reference);
                object chain;details.TryGetValue("chain_summary",out chain);
                Dictionary<string, object> sections = new Dictionary<string, object> { { "单平台任务与约束", agentText }, { "运行摘要", summary }, { "完整报告", report }, { "输入与来源", details["manifest"] }, { bound==null?"历史静态参考":"实际下发计划", bound??details["plan"] }, { "独立静态参考（未下发）", reference } };
                if (chain != null) sections["全链路校验摘要"] = chain;
                ShowNativeDocument("运行报告 · " + id, sections);
            }
            catch (Exception ex) { NativeIssue("读取报告失败", ex); }
        }
        private async void ShowNativeChain(string id = null)
        {
            if (!HasNativeBackend()) return;
            if (string.IsNullOrEmpty(id)) id = desktopRunId;
            if (string.IsNullOrEmpty(id)) { status.Text = "请先选择一条运行记录。"; return; }
            try
            {
                Dictionary<string, object> details = await Task.Run(delegate { return desktopApi.GetDetails(id); });
                object summary;
                if (!details.TryGetValue("chain_summary", out summary) || summary == null)
                {
                    status.Text = "该运行没有全链路归档；请重新运行生成。";
                    return;
                }
                DesktopChainViewer.Open(this, desktopApi.BaseUrl, id);
                status.Text = "已打开全链路追溯：" + id;
            }
            catch (Exception ex) { NativeIssue("打开全链路追溯失败", ex); }
        }
        private async void ShowNativeComparison()
        {
            if (!HasNativeBackend()) return; string key = SelectedScenario;
            try { object result = await Task.Run(delegate { return desktopApi.CompareScenario(key); }); ShowNativeComparisonTable(result as Dictionary<string, object>); }
            catch (Exception ex) { NativeIssue("读取目标对照失败", ex); }
        }
        private void ShowNativeComparisonTable(Dictionary<string, object> data, string capturePath = null)
        {
            if (data == null) throw new InvalidOperationException("对照结果格式无效");
            using (Form dialog = new Form { Text = "场景模板目标对照 · 仅计划层", Size = new Size(1040, 520), MinimumSize = new Size(800, 400), StartPosition = FormStartPosition.CenterParent, Font = Font, BackColor = Color.White })
            {
                DataGridView table = NewGrid();
                string[] keys = { "label", "assigned", "total", "makespan_s", "total_energy", "total_exposure", "detection_probability", "runtime_ms" };
                string[] headers = { "目标", "分配数", "总数", "计划完工 / s", "计划能耗", "计划暴露量", "被侦察到的概率", "计算耗时 / ms" };
                foreach (string header in headers) table.Columns.Add(header, header);
                object results; if (!data.TryGetValue("results", out results)) throw new InvalidOperationException("对照结果缺少结果行");
                foreach (object entry in (object[])results)
                {
                    Dictionary<string, object> row = entry as Dictionary<string, object>; object[] cells = new object[keys.Length];
                    for (int i = 0; i < keys.Length; i++) { object value; cells[i] = row != null && row.TryGetValue(keys[i], out value) ? value : "—"; }
                    table.Rows.Add(cells);
                }
                Label note = new Label { Dock = DockStyle.Top, Height = 55, Padding = new Padding(10), Text = "对照使用当前所选场景模板原始输入，不包含编辑草稿。结果来自已有规划器，仅证明计划层差异；尚未执行，也不代表外部平台效果。", ForeColor = Color.SlateGray };
                FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 42, Padding = new Padding(7) };
                Button copy = StandardButton("复制表格", 90), save = StandardButton("导出 CSV…", 100), close = StandardButton("关闭", 75);
                Func<string, string> cell = delegate(string value) { return "\"" + value.Replace("\"", "\"\"") + "\""; };
                Func<string> csv = delegate { List<string> lines = new List<string> { string.Join(",", headers.Select(cell).ToArray()) }; foreach (DataGridViewRow row in table.Rows) lines.Add(string.Join(",", row.Cells.Cast<DataGridViewCell>().Select(delegate(DataGridViewCell c) { return cell(Convert.ToString(c.Value, CultureInfo.InvariantCulture)); }).ToArray())); return string.Join("\r\n", lines.ToArray()); };
                copy.Click += delegate { try { Clipboard.SetText(csv()); } catch (Exception ex) { NativeIssue("复制失败", ex); } };
                save.Click += delegate { using (SaveFileDialog target = new SaveFileDialog { Filter = "CSV (*.csv)|*.csv", FileName = "template-objective-comparison.csv" }) if (target.ShowDialog(dialog) == DialogResult.OK) { try { File.WriteAllText(target.FileName, csv(), new UTF8Encoding(true)); } catch (Exception ex) { NativeIssue("导出失败", ex); } } };
                close.DialogResult = DialogResult.Cancel; actions.Controls.AddRange(new Control[] { copy, save, close }); dialog.Controls.Add(table); dialog.Controls.Add(note); dialog.Controls.Add(actions); dialog.CancelButton = close; PresentNativeForm(dialog, capturePath);
            }
        }
        private void ShowNativeDocument(string title, Dictionary<string, object> pages, string capturePath = null)
        {
            if (IsDisposed || Disposing) return;
            using (Form dialog = new Form { Text = title, Size = new Size(880, 650), MinimumSize = new Size(600, 400), Font = Font, BackColor = Color.White, StartPosition = FormStartPosition.CenterParent })
            {
                TabControl tabs = new TabControl { Dock = DockStyle.Fill };
                foreach (KeyValuePair<string, object> pair in pages)
                {
                    TabPage page = NewTab(pair.Key);
                    if (pair.Key == "运行摘要" && pair.Value is Dictionary<string, object>)
                    {
                        ListView summary = new ListView { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true, BorderStyle = BorderStyle.None };
                        summary.Columns.Add("项目", 200); summary.Columns.Add("结果 / 来源", 570);
                        foreach (KeyValuePair<string, object> row in (Dictionary<string, object>)pair.Value) summary.Items.Add(new ListViewItem(new string[] { row.Key, Convert.ToString(row.Value) }));
                        page.Controls.Add(summary);
                    }
                    else { page.Controls.Add(NativeDocumentView.Create(pair.Key,pair.Value)); }
                    tabs.TabPages.Add(page);
                }
                FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 43, Padding = new Padding(8) }; Button copy = StandardButton("复制当前页", 100), save = StandardButton("另存当前页…", 115), close = StandardButton("关闭", 75);
                copy.Click += delegate { try { Clipboard.SetText(NativeDocumentText(tabs.SelectedTab)); } catch (Exception ex) { NativeIssue("复制失败", ex); } };
                save.Click += delegate { using (SaveFileDialog target = new SaveFileDialog { Filter = "文本 (*.txt)|*.txt", FileName = "report.txt" }) if (target.ShowDialog(dialog) == DialogResult.OK) { try { File.WriteAllText(target.FileName, NativeDocumentText(tabs.SelectedTab), new UTF8Encoding(false)); } catch (Exception ex) { NativeIssue("保存失败", ex); } } };
                close.DialogResult = DialogResult.Cancel; actions.Controls.AddRange(new Control[] { copy, save, close }); dialog.Controls.Add(tabs); dialog.Controls.Add(actions); dialog.CancelButton = close; PresentNativeForm(dialog, capturePath);
            }
        }
        private void PresentNativeForm(Form dialog, string capturePath)
        {
            if (capturePath == null) { dialog.ShowDialog(this); return; }
            dialog.ShowInTaskbar = false; dialog.StartPosition = FormStartPosition.Manual; dialog.Location = new Point(-16000, -16000); dialog.Show(); Application.DoEvents();
            using (Bitmap image = new Bitmap(dialog.Width, dialog.Height)) { dialog.DrawToBitmap(image, new Rectangle(0, 0, dialog.Width, dialog.Height)); image.Save(capturePath, System.Drawing.Imaging.ImageFormat.Png); }
            dialog.Close();
        }
        private static string NativeDocumentText(TabPage page)
        {
            var readers=page.Controls.Find("NativeDocumentReading",true);if(readers.Length>0)return readers[0].Text;
            TextBox text = page.Controls[0] as TextBox; if (text != null) return text.Text;
            ListView list = page.Controls[0] as ListView;
            return list == null ? "" : string.Join("\r\n", list.Items.Cast<ListViewItem>().Select(delegate(ListViewItem item) { return item.Text + "\t" + item.SubItems[1].Text; }).ToArray());
        }
        private void ClearNativePlaceholders()
        {
            altitudeRunId = ""; altitudeSamples.Clear(); altitudeAircraft.Items.Clear();
            altitudeChart.Samples = new List<AltitudeSample>(); altitudeChart.Invalidate(); altitudeReading.Text = "尚未载入运行记录";
            taskGrid.Rows.Clear(); platformGrid.Rows.Clear(); history.Items.Clear(); properties.SelectedObject = null; selectedTitle.Text = "等待选择真实任务或平台"; taskProgress.Value = 0; nativeAllEvents.Clear(); RefreshNativeEvents();
            Time = 0; PlaybackEnd = 0; timeline.Value = 0; clock.Text = "未载入回放"; timeStatus.Text = "回放 —"; status.Text = "正在连接本地后端…";
            if (tree.Nodes.Count > 0) foreach (TreeNode node in tree.Nodes[0].Nodes)
            { if (node.Text.StartsWith("任务")) { node.Nodes.Clear(); node.Text = "任务（等待数据）"; } if (node.Text.StartsWith("平台")) { node.Nodes.Clear(); node.Text = "平台（等待数据）"; } }
        }
        private async void ShowNativeProjectHelp()
        {
            if (!HasNativeBackend()) return;
            try
            {
                object entry = await Task.Run(delegate { return desktopApi.GetProjectSource("entry"); });
                object protocol = await Task.Run(delegate { return desktopApi.GetProjectSource("interop_readme"); });
                Dictionary<string, object> a = (Dictionary<string, object>)entry, b = (Dictionary<string, object>)protocol;
                ShowNativeDocument("项目与接口说明", new Dictionary<string, object> { { "项目入口", a["text"] }, { "融合接口与边界", b["text"] } });
            }
            catch (Exception ex) { NativeIssue("读取说明失败", ex); }
        }
    }

    public sealed class NativePlatformProperties
    {
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("本轮优化目标")] public string Objective { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("平台编号")] public string Id { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("平台类型")] public string Kind { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("当前任务")] public string Job { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("回放状态")] public string State { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("回放位置")] public string Position { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("高度")] public double Altitude { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("航向（弧度）")] public double Heading { get; set; }
        [System.ComponentModel.ReadOnly(true), System.ComponentModel.DisplayName("模型电量")] public double? Battery { get; set; }
    }
}
