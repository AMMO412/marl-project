using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Web.Script.Serialization;

namespace MarlDesktopPreview
{
    public sealed partial class DesktopApi
    {
        private sealed class NativeHttpClient : WebClient
        {
            protected override WebRequest GetWebRequest(Uri address)
            {
                WebRequest request = base.GetWebRequest(address); request.Timeout = 30000;
                HttpWebRequest http = request as HttpWebRequest; if (http != null) http.ReadWriteTimeout = 30000;
                return request;
            }
        }
        private object WorkflowRequest(string path, object payload)
        {
            try { return json.DeserializeObject(payload == null ? Get(path) : Post(path, json.Serialize(payload))); }
            catch (WebException ex)
            {
                if (ex.Response != null)
                {
                    using (StreamReader reader = new StreamReader(ex.Response.GetResponseStream(), Encoding.UTF8))
                    {
                        Dictionary<string, object> error = json.DeserializeObject(reader.ReadToEnd()) as Dictionary<string, object>;
                        if (error != null && error.ContainsKey("error")) throw new InvalidOperationException(Convert.ToString(error["error"]), ex);
                    }
                }
                throw;
            }
        }
        public Dictionary<string, object> GetConfiguration(string scenario, string runId)
        {
            return (Dictionary<string, object>)WorkflowRequest("/api/desktop/config?scenario=" + Uri.EscapeDataString(scenario) + (string.IsNullOrEmpty(runId) ? "" : "&run=" + Uri.EscapeDataString(runId)), null);
        }
        public Dictionary<string, object> ValidateDraft(object draft) { return (Dictionary<string, object>)WorkflowRequest("/api/desktop/validate", draft); }
        public Dictionary<string, object> GetEditorMetadata(object message) { return (Dictionary<string, object>)WorkflowRequest("/api/desktop/editor-metadata", new Dictionary<string, object> { { "message", message } }); }
        public Dictionary<string, object> ApplyEditorTargets(object message, object targets) { return (Dictionary<string, object>)WorkflowRequest("/api/desktop/editor-targets", new Dictionary<string, object> { { "message", message }, { "targets", targets } }); }
        public Dictionary<string, object> PreviewTask(object payload) { return (Dictionary<string, object>)WorkflowRequest("/api/desktop/editor-preview", payload); }
        public Dictionary<string,object> RefreshPreset(object draft) { return (Dictionary<string,object>)WorkflowRequest("/api/desktop/refresh-preset",draft); }
        public Dictionary<string,object> StorageInfo() { return (Dictionary<string,object>)WorkflowRequest("/api/desktop/storage",null); }
        public Dictionary<string,object> DeleteRecord(string id) { return (Dictionary<string,object>)WorkflowRequest("/api/desktop/delete",new {id=id}); }
        public Dictionary<string,object> RestoreRecord(string token) { return (Dictionary<string,object>)WorkflowRequest("/api/desktop/restore",new {token=token}); }
        public string GetDemoRun(string scenario) { return Str((Dictionary<string, object>)WorkflowRequest("/api/desktop/demo?scenario=" + Uri.EscapeDataString(scenario), null), "id"); }
        public string StartDraft(object draft) { return Str((Dictionary<string, object>)WorkflowRequest("/api/desktop/runs", draft), "id"); }
        public object CompareScenario(string scenario) { return WorkflowRequest("/api/compare", new Dictionary<string, object> { { "scenario", scenario } }); }
        public object GetProjectSource(string key) { return WorkflowRequest("/api/source/" + Uri.EscapeDataString(key), null); }
        public List<DesktopEvent> GetAllEvents(string id)
        {
            Dictionary<string, object> response = (Dictionary<string, object>)WorkflowRequest("/api/desktop/events/" + Uri.EscapeDataString(id), null);
            List<DesktopEvent> events = new List<DesktopEvent>();
            foreach (object raw in AsList(Value(response, "events")))
            {
                Dictionary<string, object> row = AsDict(raw), detail = AsDict(Value(row, "event"));
                string label = Str(row, "label"); if (label.Length == 0) label = Str(detail, "kind");
                string job = Str(row, "job_id"); if (job.Length == 0) job = Str(detail, "job_id");
                events.Add(new DesktopEvent { Time = Dbl(row, "sim_s"), Kind = Str(row, "kind"), JobId = job, Label = label, Raw = row });
            }
            return events;
        }
        public Dictionary<string, object> GetDetails(string runId) { return (Dictionary<string, object>)WorkflowRequest("/api/desktop/details/" + Uri.EscapeDataString(runId), null); }
        public byte[] DownloadArtifact(string runId, string name)
        {
            using (WebClient client = new NativeHttpClient()) return client.DownloadData(BaseUrl + "/artifacts/" + Uri.EscapeDataString(runId) + "/" + Uri.EscapeDataString(name));
        }
        public static string Pretty(object value)
        {
            string source = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.Serialize(value);
            StringBuilder result = new StringBuilder(); int depth = 0; bool quoted = false, escaped = false;
            foreach (char c in source)
            {
                if (quoted) { result.Append(c); if (escaped) escaped = false; else if (c == '\\') escaped = true; else if (c == '"') quoted = false; continue; }
                if (c == '"') { quoted = true; result.Append(c); }
                else if (c == '{' || c == '[') { result.Append(c); depth++; result.AppendLine(); result.Append(' ', depth * 2); }
                else if (c == '}' || c == ']') { depth--; result.AppendLine(); result.Append(' ', depth * 2); result.Append(c); }
                else if (c == ',') { result.Append(c); result.AppendLine(); result.Append(' ', depth * 2); }
                else if (c == ':') result.Append(": "); else result.Append(c);
            }
            return result.ToString();
        }

        public object ParseNativeJson(string text)
        {
            return new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.DeserializeObject(text);
        }
    }

    public sealed class NativeRunConfiguration : System.Windows.Forms.Form
    {
        private readonly DesktopApi api;
        private readonly DesktopCatalog catalog;
        private readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 };
        private System.Windows.Forms.ComboBox scenario, mode, objective, motion, map;
        private System.Windows.Forms.NumericUpDown ticks, taskSeed;
        private System.Windows.Forms.CheckBox avoid, behavior, randomizeTasks;
        private System.Windows.Forms.TextBox message, formation, result;
        private System.Windows.Forms.Button check, run, apply, addThreat, deleteThreat, duplicateThreat;
        private System.Windows.Forms.DataGridView threatGrid;
        private System.Windows.Forms.TabPage threatPage;
        private System.Windows.Forms.Label threatSummary;
        private Dictionary<string, object> document;
        private bool applying, dirty;
        private System.Windows.Forms.Label modeHelp;
        private System.Windows.Forms.Label sourceLabel;
        public Dictionary<string, object> Draft { get; private set; }
        public bool RunRequested { get; private set; }
        public string SourceRunId { get { return Convert.ToString(document.ContainsKey("run_id") ? document["run_id"] : null); } }
        private sealed class Choice { public string Key, Label; public override string ToString() { return Label; } }
        public NativeRunConfiguration(DesktopApi api, DesktopCatalog catalog, Dictionary<string, object> document)
        {
            this.api = api; this.catalog = catalog; this.document = document;
            Text = "运行配置与任务输入"; Font = new System.Drawing.Font("Microsoft YaHei UI", 9f); BackColor = System.Drawing.Color.White;
            Size = new System.Drawing.Size(850, 650); MinimumSize = new System.Drawing.Size(700, 540); StartPosition = System.Windows.Forms.FormStartPosition.CenterParent;
            System.Windows.Forms.TabControl tabs = new System.Windows.Forms.TabControl { Name = "NativeConfigurationTabs", Dock = System.Windows.Forms.DockStyle.Fill, Padding = new System.Drawing.Point(14, 6) };
            System.Windows.Forms.TabPage common = Page("运行参数"), tasks = Page("任务输入 · 4.1 JSON"), fleet = Page("编成表 · JSON"), validation = Page("校验与来源");
            threatPage = Page("威胁区");
            System.Windows.Forms.TableLayoutPanel table = new System.Windows.Forms.TableLayoutPanel { Dock = System.Windows.Forms.DockStyle.Top, Height = 500, Padding = new System.Windows.Forms.Padding(20), ColumnCount = 2, RowCount = 10 };
            table.ColumnStyles.Add(new System.Windows.Forms.ColumnStyle(System.Windows.Forms.SizeType.Absolute, 115)); table.ColumnStyles.Add(new System.Windows.Forms.ColumnStyle(System.Windows.Forms.SizeType.Percent, 100));
            scenario = Combo(); scenario.Name = "NativeScenarioChoice"; foreach (KeyValuePair<string, string> pair in catalog.Scenarios) scenario.Items.Add(new Choice { Key = pair.Key, Label = pair.Value + " (" + pair.Key + ")" });
            mode = Choices(new string[] { "normal", "failure", "timeout", "kill", "deviation" }, new string[] { "正常执行", "失败重试", "超时恢复", "成员失联", "进度偏差" });mode.Name="NativeDemoMode";
            objective = Choices(new string[] { "makespan", "energy", "balanced", "exposure" }, new string[] { "完工时间", "能耗", "均衡（时效/暴露/能耗 0.5/0.3/0.2）", "暴露度" });
            motion = Choices(new string[] { "real" }, new string[] { "逐步运动" }); motion.Enabled = false; motion.Name = "NativeMotionChoice";
            ticks = new System.Windows.Forms.NumericUpDown { Minimum = 10, Maximum = 700, Dock = System.Windows.Forms.DockStyle.Fill, Name = "NativeMaxTicks" };
            map = Combo(); map.Name = "NativeMapChoice"; if (catalog.Maps.Count > 0) foreach (DesktopMapItem item in catalog.Maps) map.Items.Add(new Choice { Key = item.Id, Label = item.Label }); else map.Items.Add(new Choice { Key = "residential", Label = "住宅街区" });
            taskSeed = new System.Windows.Forms.NumericUpDown { Minimum = 0, Maximum = 2147483647, Dock = System.Windows.Forms.DockStyle.Fill, Name = "NativeTaskSeed" };
            randomizeTasks = new System.Windows.Forms.CheckBox { Text = "每次运行在所选地图上重新生成任务点", AutoSize = true, Name = "NativeRandomizeTasks" };
            avoid = new System.Windows.Forms.CheckBox { Text = "启用静态地图避障", AutoSize = true }; behavior = new System.Windows.Forms.CheckBox { Text = "启用到位行为", AutoSize = true };
            System.Windows.Forms.Control[] fields = { scenario, mode, objective, motion, ticks, map, taskSeed, randomizeTasks, avoid, behavior };
            string[] labels = { "场景", "运行模式", "规划目标", "运动模式", "最大仿真步数", "场景地图", "随机种子", "任务落点", "静态避障", "到位行为" };
            for (int i = 0; i < fields.Length; i++) { table.RowStyles.Add(new System.Windows.Forms.RowStyle(System.Windows.Forms.SizeType.Absolute, 43)); table.Controls.Add(new System.Windows.Forms.Label { Text = labels[i], AutoSize = true, Margin = new System.Windows.Forms.Padding(0, 7, 0, 0) }, 0, i); fields[i].Margin = new System.Windows.Forms.Padding(0, 4, 0, 0); table.Controls.Add(fields[i], 1, i); }
            behavior.Name="NativeBehaviorEnabled";
            modeHelp=new System.Windows.Forms.Label { Name="NativeModeHelp",Dock=System.Windows.Forms.DockStyle.Bottom,Height=120,Padding=new System.Windows.Forms.Padding(20,4,20,4),ForeColor=System.Drawing.Color.SlateGray };
            common.AutoScroll=true;common.Controls.Add(modeHelp);common.Controls.Add(table);
            mode.SelectedIndexChanged+=delegate {UpdateModeHelp();};
            message = Editor(); formation = Editor(); result = Editor(); message.Name = "NativeMessageEditor"; formation.Name = "NativeFormationEditor"; result.ReadOnly = true; tasks.Controls.Add(message); fleet.Controls.Add(formation); validation.Controls.Add(result);
            AddInputEditorButton(tasks, false); AddInputEditorButton(fleet, true);
            BuildThreatPage(threatPage);
            tabs.TabPages.AddRange(new System.Windows.Forms.TabPage[] { common, tasks, fleet, threatPage, validation });
            System.Windows.Forms.FlowLayoutPanel buttons = new System.Windows.Forms.FlowLayoutPanel { Dock = System.Windows.Forms.DockStyle.Bottom, Height = 49, Padding = new System.Windows.Forms.Padding(10), FlowDirection = System.Windows.Forms.FlowDirection.RightToLeft, BackColor = System.Drawing.Color.FromArgb(246, 249, 253) };
            System.Windows.Forms.Button cancel = MainWindow.StandardButton("取消", 75); cancel.DialogResult = System.Windows.Forms.DialogResult.Cancel;
            run = MainWindow.StandardButton("校验并运行", 104); apply = MainWindow.StandardButton("应用配置", 90); check = MainWindow.StandardButton("检查输入", 90); System.Windows.Forms.Button export = MainWindow.StandardButton("导出草稿", 90);
            System.Windows.Forms.Button editInputs = MainWindow.StandardButton("任务与平台", 100); editInputs.Name = "NativeOpenInputEditor"; editInputs.Click += delegate { OpenInputEditor(false); };
            System.Windows.Forms.Button structuredInputs = MainWindow.StandardButton("专用表单", 88); structuredInputs.Name = "NativeOpenStructuredEditor"; structuredInputs.Click += delegate { OpenStructuredEditor(0); };
            sourceLabel = new System.Windows.Forms.Label { Name = "NativeConfigurationSource", Dock = System.Windows.Forms.DockStyle.Top, Height = 52, Padding = new System.Windows.Forms.Padding(12, 7, 12, 4), AutoEllipsis = true, BackColor = System.Drawing.Color.FromArgb(246, 249, 253) };
            buttons.Controls.AddRange(new System.Windows.Forms.Control[] { cancel, run, apply, check, export, editInputs, structuredInputs }); Controls.Add(tabs); Controls.Add(buttons); Controls.Add(sourceLabel); CancelButton = cancel;
            check.Click += async delegate { await ValidateAsync(false, false); tabs.SelectedTab = validation; };
            run.Click += async delegate { await ValidateAsync(true, true); }; apply.Click += async delegate { await ValidateAsync(true, false); };
            export.Click += delegate { try { object draft = ReadDraft(); using (System.Windows.Forms.SaveFileDialog save = new System.Windows.Forms.SaveFileDialog { Filter = "桌面配置 (*.json)|*.json", FileName = "desktop-draft.json" }) if (save.ShowDialog(this) == System.Windows.Forms.DialogResult.OK) File.WriteAllText(save.FileName, DesktopApi.Pretty(draft), new UTF8Encoding(false)); } catch (Exception ex) { ShowError(ex); } };
            scenario.SelectedIndexChanged += async delegate
            {
                if (applying || scenario.SelectedItem == null) return;
                if (dirty && System.Windows.Forms.MessageBox.Show(this, "切换场景会替换当前未应用的输入，是否继续？", "切换场景", System.Windows.Forms.MessageBoxButtons.YesNo) != System.Windows.Forms.DialogResult.Yes) { applying = true; SelectChoice(scenario, Convert.ToString(((Dictionary<string, object>)Draft["request"])["scenario"])); applying = false; return; }
                try { string key = ((Choice)scenario.SelectedItem).Key; Busy(true); Dictionary<string, object> loaded = await System.Threading.Tasks.Task.Run(delegate { return api.GetConfiguration(key, null); }); if (!IsDisposed) ApplyDocument(loaded); }
                catch (Exception ex) { if (!IsDisposed) { applying = true; SelectChoice(scenario, Convert.ToString(((Dictionary<string, object>)Draft["request"])["scenario"])); applying = false; ShowError(ex); } } finally { if (!IsDisposed) Busy(false); }
            };
            foreach (System.Windows.Forms.Control control in new System.Windows.Forms.Control[] { message, formation, mode, objective, motion, ticks, map, taskSeed, randomizeTasks, avoid, behavior }) control.TextChanged += delegate { if (!applying) dirty = true; };
            avoid.CheckedChanged += delegate { if (!applying) dirty = true; }; behavior.CheckedChanged += delegate { if (!applying) dirty = true; }; ticks.ValueChanged += delegate { if (!applying) dirty = true; };
            taskSeed.ValueChanged += delegate { if (!applying) dirty = true; }; randomizeTasks.CheckedChanged += delegate { if (!applying) dirty = true; };
            tabs.SelectedIndexChanged += delegate { if (!applying && tabs.SelectedTab == threatPage) RefreshThreatsFromJson(); };
            ApplyDocument(document);
            FormClosing += delegate(object sender, System.Windows.Forms.FormClosingEventArgs e)
            {
                if (!dirty || DialogResult == System.Windows.Forms.DialogResult.OK) return;
                if (System.Windows.Forms.MessageBox.Show(this, "有尚未应用的修改，关闭后将丢失。是否关闭？", "未应用的修改", System.Windows.Forms.MessageBoxButtons.YesNo, System.Windows.Forms.MessageBoxIcon.Question) == System.Windows.Forms.DialogResult.No)
                { e.Cancel = true; DialogResult = System.Windows.Forms.DialogResult.None; }
            };
        }
        private void AddInputEditorButton(System.Windows.Forms.TabPage page, bool platforms)
        {
            var toolbar = new System.Windows.Forms.FlowLayoutPanel { Dock=System.Windows.Forms.DockStyle.Top, Height=42, Padding=new System.Windows.Forms.Padding(3) };
            var button=MainWindow.StandardButton(platforms?"表格编辑平台":"表格编辑任务",125);button.Click+=delegate{OpenInputEditor(platforms);};
            toolbar.Controls.Add(button);
            if (!platforms) {
                var structured=MainWindow.StandardButton("任务专用表单",105);structured.Name="NativeOpenStructuredTasks";structured.Click+=delegate{OpenStructuredEditor(0);};toolbar.Controls.Add(structured);
                var targets=MainWindow.StandardButton("红方目标",88);targets.Name="NativeOpenStructuredTargets";targets.Click+=delegate{OpenStructuredEditor(1);};toolbar.Controls.Add(targets);
            }
            toolbar.Controls.Add(new System.Windows.Forms.Label { Text="字段、坐标列表可展开编辑；JSON、专用表单与表格使用同一份草稿。",AutoSize=true,Margin=new System.Windows.Forms.Padding(10,7,0,0),ForeColor=System.Drawing.Color.SlateGray });page.Controls.Add(toolbar);
        }
        private void BuildThreatPage(System.Windows.Forms.TabPage page)
        {
            threatGrid = new System.Windows.Forms.DataGridView
            {
                Name = "NativeThreatGrid",
                Dock = System.Windows.Forms.DockStyle.Fill,
                BackgroundColor = System.Drawing.Color.White,
                BorderStyle = System.Windows.Forms.BorderStyle.None,
                AllowUserToAddRows = false,
                AllowUserToDeleteRows = false,
                RowHeadersVisible = false,
                SelectionMode = System.Windows.Forms.DataGridViewSelectionMode.FullRowSelect,
                MultiSelect = false,
                AutoGenerateColumns = false,
                AutoSizeColumnsMode = System.Windows.Forms.DataGridViewAutoSizeColumnsMode.Fill,
                EnableHeadersVisualStyles = false,
                ColumnHeadersHeight = 34,
                GridColor = System.Drawing.Color.FromArgb(219, 229, 241),
                ColumnHeadersDefaultCellStyle = new System.Windows.Forms.DataGridViewCellStyle
                {
                    BackColor = System.Drawing.Color.FromArgb(233, 241, 251),
                    ForeColor = System.Drawing.Color.FromArgb(32, 77, 132),
                    SelectionBackColor = System.Drawing.Color.FromArgb(233, 241, 251),
                    SelectionForeColor = System.Drawing.Color.FromArgb(32, 77, 132)
                },
                DefaultCellStyle = new System.Windows.Forms.DataGridViewCellStyle
                {
                    BackColor = System.Drawing.Color.White,
                    ForeColor = System.Drawing.Color.FromArgb(70, 89, 112),
                    SelectionBackColor = System.Drawing.Color.FromArgb(220, 236, 253),
                    SelectionForeColor = System.Drawing.Color.FromArgb(31, 94, 163)
                }
            };
            threatGrid.Columns.Add(new System.Windows.Forms.DataGridViewTextBoxColumn { Name = "constraint_id", HeaderText = "威胁区编号", FillWeight = 22, MinimumWidth = 105 });
            var applies = new System.Windows.Forms.DataGridViewComboBoxColumn { Name = "applies_to", HeaderText = "作用对象", FillWeight = 16, MinimumWidth = 82, FlatStyle = System.Windows.Forms.FlatStyle.Flat };
            applies.Items.AddRange(new object[] { "对地", "对空", "空地" });
            threatGrid.Columns.Add(applies);
            threatGrid.Columns.Add(new System.Windows.Forms.DataGridViewTextBoxColumn { Name = "intensity", HeaderText = "强度", FillWeight = 12, MinimumWidth = 62 });
            threatGrid.Columns.Add(new System.Windows.Forms.DataGridViewTextBoxColumn { Name = "center_x", HeaderText = "中心 X", FillWeight = 14, MinimumWidth = 72 });
            threatGrid.Columns.Add(new System.Windows.Forms.DataGridViewTextBoxColumn { Name = "center_y", HeaderText = "中心 Y", FillWeight = 14, MinimumWidth = 72 });
            threatGrid.Columns.Add(new System.Windows.Forms.DataGridViewTextBoxColumn { Name = "width", HeaderText = "宽度", FillWeight = 12, MinimumWidth = 65 });
            threatGrid.Columns.Add(new System.Windows.Forms.DataGridViewTextBoxColumn { Name = "height", HeaderText = "高度", FillWeight = 12, MinimumWidth = 65 });
            threatGrid.CellValueChanged += delegate { if (!applying) { CommitThreatGridAfterEdit(); dirty = true; } };
            threatGrid.CurrentCellDirtyStateChanged += delegate
            {
                if (threatGrid.IsCurrentCellDirty && threatGrid.CurrentCell != null &&
                    threatGrid.CurrentCell.OwningColumn == threatGrid.Columns["applies_to"])
                    threatGrid.CommitEdit(System.Windows.Forms.DataGridViewDataErrorContexts.Commit);
            };
            threatGrid.DataError += delegate(object sender, System.Windows.Forms.DataGridViewDataErrorEventArgs e) { e.ThrowException = false; };

            var toolbar = new System.Windows.Forms.FlowLayoutPanel { Dock = System.Windows.Forms.DockStyle.Top, Height = 46, Padding = new System.Windows.Forms.Padding(3), BackColor = System.Drawing.Color.White };
            addThreat = MainWindow.StandardButton("新增威胁区", 105); addThreat.Name = "NativeThreatAdd"; addThreat.Click += delegate { AddThreatRow(); };
            deleteThreat = MainWindow.StandardButton("删除选中", 90); deleteThreat.Name = "NativeThreatDelete"; deleteThreat.Click += delegate { DeleteThreatRow(); };
            duplicateThreat = MainWindow.StandardButton("复制选中", 90); duplicateThreat.Name = "NativeThreatDuplicate"; duplicateThreat.Click += delegate { DuplicateThreatRow(); };
            var reload = MainWindow.StandardButton("从 JSON 刷新", 105); reload.Name = "NativeThreatReload"; reload.Click += delegate { RefreshThreatsFromJson(); };
            toolbar.Controls.AddRange(new System.Windows.Forms.Control[] { addThreat, deleteThreat, duplicateThreat, reload });
            threatSummary = new System.Windows.Forms.Label { Name = "NativeThreatSummary", Dock = System.Windows.Forms.DockStyle.Bottom, Height = 58, Padding = new System.Windows.Forms.Padding(10, 8, 10, 0), ForeColor = System.Drawing.Color.SlateGray, Text = "矩形威胁区；作用对象、强度、中心坐标和宽高会写回编成表 constraints。" };
            page.Controls.Add(threatGrid);
            page.Controls.Add(toolbar);
            page.Controls.Add(threatSummary);
        }
        private static object ThreatValue(System.Windows.Forms.DataGridViewRow row, string name)
        {
            return row.Cells[name].Value;
        }
        private static void SetThreatValue(System.Windows.Forms.DataGridViewRow row, string name, object value)
        {
            row.Cells[name].Value = value;
        }
        private static double ThreatNumber(object value, string label)
        {
            string text = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
            if (String.IsNullOrWhiteSpace(text))
                throw new InvalidOperationException(label + "不能为空。");
            double parsed;
            if (!double.TryParse(text, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out parsed) || double.IsNaN(parsed) || double.IsInfinity(parsed))
                throw new InvalidOperationException(label + "必须是有效数字。");
            return parsed;
        }
        private static string ThreatAppliesLabel(string value)
        {
            if (value == "air") return "对空";
            if (value == "all") return "空地";
            return "对地";
        }
        private static string ThreatAppliesToken(object value)
        {
            string text = Convert.ToString(value);
            if (text == "对空" || text == "air") return "air";
            if (text == "空地" || text == "all") return "all";
            if (text == "对地" || text == "ground") return "ground";
            throw new InvalidOperationException("作用对象必须是 对地 / 对空 / 空地。");
        }
        private void UpdateThreatSummary(int count, bool committed = false)
        {
            if (threatSummary == null) return;
            int ground = 0, air = 0;
            try
            {
                Dictionary<string, object> root = Draft["formation"] as Dictionary<string, object>;
                while (root != null && root.ContainsKey("formation") &&
                       root["formation"] is Dictionary<string, object>)
                    root = root["formation"] as Dictionary<string, object>;
                var units = root != null && root.ContainsKey("units")
                    ? root["units"] as System.Collections.IList : null;
                if (units != null)
                {
                    foreach (System.Windows.Forms.DataGridViewRow row in threatGrid.Rows)
                    {
                        string applies = ThreatAppliesToken(ThreatValue(row, "applies_to"));
                        double x = ThreatNumber(ThreatValue(row, "center_x"), "中心 X");
                        double y = ThreatNumber(ThreatValue(row, "center_y"), "中心 Y");
                        double width = ThreatNumber(ThreatValue(row, "width"), "宽度");
                        double height = ThreatNumber(ThreatValue(row, "height"), "高度");
                        foreach (object raw in units)
                        {
                            var unit = raw as Dictionary<string, object>;
                            if (unit == null) continue;
                            string platformClass = Convert.ToString(unit.ContainsKey("platform_class")
                                ? unit["platform_class"] : "").ToUpperInvariant();
                            bool isAir = platformClass == "PLANE" || platformClass == "WING";
                            if (applies == "ground" && isAir) continue;
                            if (applies == "air" && !isAir) continue;
                            object rawPosition = unit.ContainsKey("position") ? unit["position"] : null;
                            double px, py;
                            var position = rawPosition as Dictionary<string, object>;
                            if (position != null)
                            {
                                px = Convert.ToDouble(position.ContainsKey("x") ? position["x"] : 0.0,
                                                      System.Globalization.CultureInfo.InvariantCulture);
                                py = Convert.ToDouble(position.ContainsKey("y") ? position["y"] : 0.0,
                                                      System.Globalization.CultureInfo.InvariantCulture);
                            }
                            else
                            {
                                var point = rawPosition as System.Collections.IList;
                                if (point == null || point.Count < 2) continue;
                                px = Convert.ToDouble(point[0], System.Globalization.CultureInfo.InvariantCulture);
                                py = Convert.ToDouble(point[1], System.Globalization.CultureInfo.InvariantCulture);
                            }
                            if (px < x - width / 2.0 || px > x + width / 2.0 ||
                                py < y - height / 2.0 || py > y + height / 2.0) continue;
                            if (isAir) air++; else ground++;
                        }
                    }
                }
            }
            catch
            {
                // A partially edited row should stay editable. Contract
                // validation runs again before the user applies or starts.
            }
            string baseText = "共 " + count + " 块威胁区" +
                              (committed ? "，已写回编成表草稿。" : "。") +
                              "作用对象支持对地、对空、空地。";
            if (ground + air > 0)
            {
                threatSummary.ForeColor = System.Drawing.Color.FromArgb(174, 104, 26);
                threatSummary.Text = baseText + "\r\n配置允许运行：威胁区覆盖初始设备（对地 " +
                                     ground + " 台、对空 " + air +
                                     " 台）。初始暴露会计入统计，执行将逐步离开威胁区。";
            }
            else
            {
                threatSummary.ForeColor = System.Drawing.Color.SlateGray;
                threatSummary.Text = baseText + "\r\n当前威胁区未覆盖设备初始位置。";
            }
        }
        private static void ThreatBounds(Dictionary<string, object> item, out double x, out double y, out double width, out double height)
        {
            var area = item.ContainsKey("area") ? item["area"] : null;
            var areaMap = area as Dictionary<string, object>;
            var polygon = (areaMap != null && areaMap.ContainsKey("polygon") ? areaMap["polygon"] : area) as System.Collections.IList;
            if (polygon == null || polygon.Count < 3) throw new InvalidOperationException("已有威胁区缺少至少三个顶点，不能在矩形表格中编辑。");
            var points = new List<double[]>();
            foreach (object raw in polygon)
            {
                var point = raw as System.Collections.IList;
                if (point == null || point.Count < 2) throw new InvalidOperationException("威胁区顶点必须是 [X, Y]。");
                points.Add(new double[] { Convert.ToDouble(point[0], System.Globalization.CultureInfo.InvariantCulture), Convert.ToDouble(point[1], System.Globalization.CultureInfo.InvariantCulture) });
            }
            double x0 = points.Min(p => p[0]), x1 = points.Max(p => p[0]);
            double y0 = points.Min(p => p[1]), y1 = points.Max(p => p[1]);
            x = (x0 + x1) / 2.0; y = (y0 + y1) / 2.0;
            width = x1 - x0; height = y1 - y0;
        }
        private object ThreatConstraints(bool create)
        {
            Dictionary<string, object> root = Draft["formation"] as Dictionary<string, object>;
            if (root == null) return null;
            if (!root.ContainsKey("constraints") && root.ContainsKey("formation"))
            {
                var nested = root["formation"] as Dictionary<string, object>;
                if (nested != null && nested.ContainsKey("constraints")) root = nested;
            }
            if (!root.ContainsKey("constraints"))
            {
                if (!create) return null;
                root["constraints"] = new List<object>();
            }
            var constraints = root["constraints"] as System.Collections.IList;
            if (constraints != null && (constraints.IsFixedSize || constraints.IsReadOnly))
            {
                var mutable = new List<object>();
                foreach (object item in constraints) mutable.Add(item);
                root["constraints"] = mutable;
                return mutable;
            }
            return root["constraints"];
        }
        private void RefreshThreatsFromJson()
        {
            if (threatGrid == null || Draft == null) return;
            try
            {
                Dictionary<string, object> parsed = json.DeserializeObject(formation.Text) as Dictionary<string, object>;
                if (parsed == null) throw new InvalidOperationException("编成表 JSON 根节点必须是对象。");
                Draft["formation"] = parsed;
                var constraints = ThreatConstraints(false) as System.Collections.IList;
                applying = true;
                threatGrid.Rows.Clear();
                int count = 0;
                if (constraints != null)
                {
                    foreach (object raw in constraints)
                    {
                        var item = raw as Dictionary<string, object>;
                        if (item == null || Convert.ToString(item.ContainsKey("type") ? item["type"] : "") != "threat") continue;
                        double x, y, width, height;
                        ThreatBounds(item, out x, out y, out width, out height);
                        int index = threatGrid.Rows.Add(
                            Convert.ToString(item.ContainsKey("constraint_id") ? item["constraint_id"] : "THREAT-" + (count + 1)),
                            ThreatAppliesLabel(Convert.ToString(item.ContainsKey("applies_to") ? item["applies_to"] : "ground")),
                            item.ContainsKey("intensity") ? item["intensity"] : 1.0,
                            x, y, width, height);
                        threatGrid.Rows[index].Tag = item;
                        count++;
                    }
                }
                UpdateThreatSummary(count);
            }
            catch (Exception ex)
            {
                result.Text = "威胁区表格未刷新：" + ex.Message;
            }
            finally
            {
                applying = false;
            }
        }
        private void CommitThreatGridAfterEdit()
        {
            try
            {
                CommitThreatGrid();
            }
            catch (Exception ex)
            {
                threatSummary.ForeColor = System.Drawing.Color.FromArgb(174, 58, 46);
                threatSummary.Text = "编辑尚未完成：" + ex.Message + " 当前输入会保留，补全后自动写回；点击检查、应用或运行时将再次校验。";
            }
        }
        private void CommitThreatGrid()
        {
            if (threatGrid == null || Draft == null) return;
            if (!(Draft.ContainsKey("formation") && Draft["formation"] is Dictionary<string, object>)) return;
            threatGrid.EndEdit();
            var constraints = ThreatConstraints(true) as System.Collections.IList;
            if (constraints == null) throw new InvalidOperationException("编成表 constraints 必须是数组。");
            var rebuilt = new List<object>();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (object raw in constraints)
            {
                var item = raw as Dictionary<string, object>;
                if (item == null || Convert.ToString(item.ContainsKey("type") ? item["type"] : "") != "threat") rebuilt.Add(raw);
            }
            foreach (System.Windows.Forms.DataGridViewRow row in threatGrid.Rows)
            {
                string id = Convert.ToString(ThreatValue(row, "constraint_id")).Trim();
                if (id.Length == 0) throw new InvalidOperationException("威胁区编号不能为空。");
                if (!ids.Add(id)) throw new InvalidOperationException("威胁区编号不能重复：" + id);
                var item = row.Tag as Dictionary<string, object>;
                if (item == null) { item = new Dictionary<string, object>(); row.Tag = item; }
                double x = ThreatNumber(ThreatValue(row, "center_x"), "中心 X");
                double y = ThreatNumber(ThreatValue(row, "center_y"), "中心 Y");
                double width = ThreatNumber(ThreatValue(row, "width"), "宽度");
                double height = ThreatNumber(ThreatValue(row, "height"), "高度");
                double intensity = ThreatNumber(ThreatValue(row, "intensity"), "强度");
                if (width <= 0 || height <= 0) throw new InvalidOperationException("威胁区宽度和高度必须大于 0。");
                if (intensity < 0) throw new InvalidOperationException("威胁区强度不能为负。");
                item["constraint_id"] = id;
                item["type"] = "threat";
                item["applies_to"] = ThreatAppliesToken(ThreatValue(row, "applies_to"));
                item["intensity"] = intensity;
                item["area"] = new Dictionary<string, object>
                {
                    { "polygon", new List<object>
                        {
                            new List<object> { x - width / 2.0, y - height / 2.0 },
                            new List<object> { x + width / 2.0, y - height / 2.0 },
                            new List<object> { x + width / 2.0, y + height / 2.0 },
                            new List<object> { x - width / 2.0, y + height / 2.0 }
                        }
                    }
                };
                rebuilt.Add(item);
            }
            constraints.Clear();
            foreach (object item in rebuilt) constraints.Add(item);
            formation.Text = DesktopApi.Pretty(Draft["formation"]);
            UpdateThreatSummary(threatGrid.Rows.Count, true);
        }
        private void AddThreatRow()
        {
            try
            {
                RefreshThreatsFromJson();
                int number = 1;
                var ids = new HashSet<string>(StringComparer.Ordinal);
                foreach (System.Windows.Forms.DataGridViewRow row in threatGrid.Rows) ids.Add(Convert.ToString(ThreatValue(row, "constraint_id")));
                while (ids.Contains("THREAT-" + number)) number++;
                double x = 0.0, y = 0.0;
                if (threatGrid.Rows.Count > 0)
                {
                    var last = threatGrid.Rows[threatGrid.Rows.Count - 1];
                    x = ThreatNumber(ThreatValue(last, "center_x"), "中心 X") + ThreatNumber(ThreatValue(last, "width"), "宽度") + 10.0;
                    y = ThreatNumber(ThreatValue(last, "center_y"), "中心 Y");
                }
                applying = true;
                int index = threatGrid.Rows.Add("THREAT-" + number, "对地", 0.7, x, y, 20.0, 20.0);
                threatGrid.Rows[index].Tag = new Dictionary<string, object>();
                applying = false;
                threatGrid.CurrentCell = threatGrid.Rows[index].Cells["constraint_id"];
                CommitThreatGrid(); dirty = true;
            }
            catch (Exception ex) { result.Text = "新增威胁区失败：" + ex.Message; }
        }
        private void DeleteThreatRow()
        {
            try
            {
                if (threatGrid.CurrentRow == null) return;
                threatGrid.Rows.Remove(threatGrid.CurrentRow);
                CommitThreatGrid(); dirty = true;
            }
            catch (Exception ex) { result.Text = "删除威胁区失败：" + ex.Message; }
        }
        private void DuplicateThreatRow()
        {
            try
            {
                if (threatGrid.CurrentRow == null) return;
                var source = threatGrid.CurrentRow;
                string basis = Convert.ToString(ThreatValue(source, "constraint_id")) + "_copy", id = basis;
                var ids = new HashSet<string>(threatGrid.Rows.Cast<System.Windows.Forms.DataGridViewRow>().Select(row => Convert.ToString(ThreatValue(row, "constraint_id"))));
                int number = 2;
                while (ids.Contains(id)) id = basis + number++;
                applying = true;
                int index = threatGrid.Rows.Add(id, ThreatValue(source, "applies_to"), ThreatValue(source, "intensity"), ThreatValue(source, "center_x"), ThreatValue(source, "center_y"), ThreatValue(source, "width"), ThreatValue(source, "height"));
                threatGrid.Rows[index].Tag = new Dictionary<string, object>();
                applying = false;
                threatGrid.CurrentCell = threatGrid.Rows[index].Cells["constraint_id"];
                CommitThreatGrid(); dirty = true;
            }
            catch (Exception ex) { result.Text = "复制威胁区失败：" + ex.Message; }
        }
        private void OpenInputEditor(bool platforms)
        {
            try { using(var editor=new NativeInputEditor(api,ReadDraft(),platforms))if(editor.ShowDialog(this)==System.Windows.Forms.DialogResult.OK){
                message.Text=DesktopApi.Pretty(editor.Draft["message"]);formation.Text=DesktopApi.Pretty(editor.Draft["formation"]);dirty=true;
                result.Text="表格修改已检查并写入草稿；点击应用配置或校验并运行生效。原运行与模板保留。";
            }}catch(Exception ex){ShowError(ex);}
        }
        private void OpenStructuredEditor(int initialTab)
        {
            try {
                using(var editor=new NativeStructuredEditor(api,ReadDraft(),initialTab))
                    if(editor.ShowDialog(this)==System.Windows.Forms.DialogResult.OK){
                        message.Text=DesktopApi.Pretty(editor.Draft["message"]);
                        formation.Text=DesktopApi.Pretty(editor.Draft["formation"]);
                        dirty=true;
                        result.Text="任务专用表单与红方目标已检查并写入草稿；点击应用配置或校验并运行会创建新的完整运行。原运行与模板保留。";
                    }
            } catch(Exception ex){ShowError(ex);}
        }
        private static System.Windows.Forms.TabPage Page(string text) { return new System.Windows.Forms.TabPage(text) { BackColor = System.Drawing.Color.White, Padding = new System.Windows.Forms.Padding(6) }; }
        private static System.Windows.Forms.ComboBox Combo() { return new System.Windows.Forms.ComboBox { Dock = System.Windows.Forms.DockStyle.Fill, DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList }; }
        private static System.Windows.Forms.ComboBox Choices(string[] keys, string[] labels) { System.Windows.Forms.ComboBox combo = Combo(); for (int i = 0; i < keys.Length; i++) combo.Items.Add(new Choice { Key = keys[i], Label = labels[i] }); return combo; }
        private static System.Windows.Forms.TextBox Editor() { return new System.Windows.Forms.TextBox { Dock = System.Windows.Forms.DockStyle.Fill, Multiline = true, ScrollBars = System.Windows.Forms.ScrollBars.Both, WordWrap = false, AcceptsReturn = true, AcceptsTab = true, MaxLength = 1024 * 1024, Font = new System.Drawing.Font("Consolas", 10f), BorderStyle = System.Windows.Forms.BorderStyle.FixedSingle }; }
        private static void SelectChoice(System.Windows.Forms.ComboBox combo, string key) { foreach (Choice item in combo.Items) if (item.Key == key) { combo.SelectedItem = item; return; } }
        private void ApplyDocument(Dictionary<string, object> value)
        {
            applying = true; document = value; Draft = (Dictionary<string, object>)value["draft"]; Dictionary<string, object> request = (Dictionary<string, object>)Draft["request"];
            SelectChoice(scenario, Convert.ToString(request["scenario"])); SelectChoice(mode, Convert.ToString(request["mode"])); SelectChoice(objective, Convert.ToString(request["objective"])); SelectChoice(motion, Convert.ToString(request["motion"]));
            ticks.Value = Math.Min(700, Math.Max(10, Convert.ToDecimal(request["max_ticks"]))); avoid.Checked = Convert.ToBoolean(request["avoid"]); behavior.Checked = Convert.ToBoolean(request["behavior"]);
            SelectChoice(map, request.ContainsKey("map_id") ? Convert.ToString(request["map_id"]) : "residential");
            taskSeed.Value = Convert.ToDecimal(request.ContainsKey("task_seed") ? request["task_seed"] : 0);
            randomizeTasks.Checked = Convert.ToBoolean(request.ContainsKey("randomize_tasks") ? request["randomize_tasks"] : true);
            message.Text = DesktopApi.Pretty(Draft["message"]); formation.Text = DesktopApi.Pretty(Draft["formation"]);
            bool editable = Draft["message"] != null; message.ReadOnly = formation.ReadOnly = !editable;
            string source = Convert.ToString(value.ContainsKey("input_source") ? value["input_source"] : "import");
            string runId = Convert.ToString(value.ContainsKey("run_id") ? value["run_id"] : "");
            string sourceText = source == "run_snapshot" ? "运行记录保存的参数" : source == "desktop_draft" ? "已应用的待运行草稿" : source == "template" ? "新建场景模板" : source == "template_fallback" ? "历史记录缺少完整输入，任务与编成使用模板补充（非原始完整参数）" : "导入的配置";
            Text = "场景参数 · " + sourceText;
            sourceLabel.Text = sourceText + (runId.Length == 0 ? "" : "\r\n来源运行：" + runId);
            sourceLabel.ForeColor = source == "template_fallback" ? System.Drawing.Color.DarkOrange : System.Drawing.Color.FromArgb(53, 86, 117);
            result.Text = "输入来源：" + sourceText + (runId.Length == 0 ? "" : "\r\n来源运行：" + runId) + "\r\n" + Convert.ToString(value.ContainsKey("note") ? value["note"] : "") + "\r\n\r\n只支持当前注册的场景，统一逐步运动；JSON 无效时保留编辑内容。";
            if (editable) RefreshThreatsFromJson();
            UpdateModeHelp();applying = false; dirty = false;
        }
        private void UpdateModeHelp()
        {
            if(modeHelp==null||mode.SelectedItem==null||behavior==null)return;
            string key=((Choice)mode.SelectedItem).Key,description="";
            switch(key) {
                case "normal":description="正常执行：不额外注入故障；任务本身仍可能失败。";break;
                case "failure":description="失败重试：首任务首次下发后第 2 步失败，再按上限重试。";break;
                case "timeout":description="超时恢复：首任务首次停滞 1000 步，超时后取消，收到取消确认再重试。";break;
                case "kill":description="成员失联：从第 8 步起，仅让首任务一台已下发成员失联并重规划。";break;
                case "deviation":description="进度偏差：首个协同作业按 70% 速率推进，超过落后阈值后重规划，不保证自动修复。";break;
            }
            bool progress=key=="timeout"||key=="deviation";
            avoid.Checked=true;avoid.Enabled=false;
            behavior.Checked=!progress;behavior.Enabled=false;
            modeHelp.Text=description+"\r\n"+(progress?"此模式演示作业进度与消息闭环，已关闭到位行为；地图仍显示逐步运动。":"此模式保留到位后的任务行为。")+"\r\n配置修改应用到草稿后新建完整运行；回放时刻续算尚未移植。";
        }
        public Dictionary<string, object> ReadDraft()
        {
            CommitThreatGrid();
            Dictionary<string, object> request = new Dictionary<string, object>((Dictionary<string, object>)Draft["request"]);
            request["scenario"] = ((Choice)scenario.SelectedItem).Key; request["mode"] = ((Choice)mode.SelectedItem).Key; request["objective"] = ((Choice)objective.SelectedItem).Key; request["motion"] = "real"; request["max_ticks"] = (int)ticks.Value; request["avoid"] = avoid.Checked; request["behavior"] = behavior.Checked;
            request["map_id"] = ((Choice)map.SelectedItem).Key;
            request["task_seed"] = (int)taskSeed.Value;
            request["randomize_tasks"] = randomizeTasks.Checked;
            request["reseed_on_run"] = randomizeTasks.Checked;
            request["planner"] = request["scenario"].ToString().StartsWith("interop_") ? "interop" : "base";
            return new Dictionary<string, object> { { "request", request }, { "message", json.DeserializeObject(message.Text) }, { "formation", json.DeserializeObject(formation.Text) } };
        }
        private async System.Threading.Tasks.Task ValidateAsync(bool close, bool runRequested)
        {
            try { Dictionary<string, object> candidate = ReadDraft(); Busy(true); Dictionary<string, object> response = await System.Threading.Tasks.Task.Run(delegate { return api.ValidateDraft(candidate); }); if (IsDisposed) return; Draft = (Dictionary<string, object>)response["draft"]; result.Text = "输入契约校验通过。尚未执行，不代表任务可行性或效果已验证。\r\n\r\n有效运行参数：\r\n" + DesktopApi.Pretty(Draft["request"]) + "\r\n\r\n" + DesktopApi.Pretty(response["summary"]); if (close) { RunRequested = runRequested; DialogResult = System.Windows.Forms.DialogResult.OK; } }
            catch (Exception ex) { ShowError(ex); } finally { if (!IsDisposed) Busy(false); }
        }
        private void Busy(bool value) { run.Enabled = apply.Enabled = check.Enabled = scenario.Enabled = map.Enabled = taskSeed.Enabled = randomizeTasks.Enabled = addThreat.Enabled = deleteThreat.Enabled = duplicateThreat.Enabled = !value; UseWaitCursor = value; }
        private void ShowError(Exception ex) { if (IsDisposed) return; result.Text = "检查未通过，编辑内容保留：\r\n" + ex.Message; System.Windows.Forms.MessageBox.Show(this, ex.Message, "输入检查", System.Windows.Forms.MessageBoxButtons.OK, System.Windows.Forms.MessageBoxIcon.Warning); }
    }
}
