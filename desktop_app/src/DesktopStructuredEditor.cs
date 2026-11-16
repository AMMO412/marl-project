using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    // Task-specific forms render the backend's five task catalogs while the
    // canonical draft remains the existing 4.1 message. Red targets are
    // written back through the backend so their storage mapping has one owner.
    internal sealed class NativeStructuredEditor : Form
    {
        private sealed class Choice
        {
            internal string Key, Label;
            public override string ToString() { return Label; }
        }

        private sealed class FieldRow
        {
            internal string Key, Kind, Label;
            internal bool Common, Existing, Required;
        }

        private readonly DesktopApi api;
        private Dictionary<string, object> message;
        private Dictionary<string, object> editor;
        private Dictionary<string, object> taskTypes;
        private Dictionary<string, object> targetSlots;
        private IList targets;
        private readonly TabControl tabs;
        private readonly DataGridView taskGrid;
        private readonly DataGridView parameterGrid;
        private readonly DataGridView targetGrid;
        private readonly ComboBox newTaskType;
        private readonly ComboBox targetSlot;
        private readonly Label note;
        private readonly Button save;
        private bool modified, applying;

        internal Dictionary<string, object> Draft { get; private set; }

        internal NativeStructuredEditor(
            DesktopApi api, Dictionary<string, object> draft, int initialTab)
        {
            this.api = api;
            Draft = (Dictionary<string, object>)NativeInputData.Copy(draft);
            message = (Dictionary<string, object>)Draft["message"];
            if (message == null)
                throw new InvalidOperationException("当前场景没有可编辑的 4.1 任务消息。");

            editor = api.GetEditorMetadata(message);
            taskTypes = AsDict(editor, "task_types");
            targetSlots = AsDict(editor, "target_slots");
            targets = CopyList(editor, "targets");

            Text = "任务专用表单与红方目标";
            Font = new Font("Microsoft YaHei UI", 9f);
            BackColor = Color.White;
            Size = new Size(1120, 730);
            MinimumSize = new Size(900, 580);
            StartPosition = FormStartPosition.CenterParent;
            Name = "NativeStructuredEditor";

            tabs = new TabControl {
                Dock = DockStyle.Fill,
                Name = "NativeStructuredTabs",
                Padding = new Point(14, 6)
            };

            TabPage taskPage = new TabPage("任务专用表单") {
                BackColor = Color.White, Padding = new Padding(7)
            };
            var content = new TableLayoutPanel {
                Dock = DockStyle.Fill,
                ColumnCount = 2,
                RowCount = 1,
                Padding = new Padding(0)
            };
            content.ColumnStyles.Add(new ColumnStyle(
                SizeType.Absolute, 370));
            content.ColumnStyles.Add(new ColumnStyle(
                SizeType.Percent, 100));
            content.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            var taskPanel = new Panel { Dock = DockStyle.Fill };
            var detailPanel = new Panel { Dock = DockStyle.Fill };
            content.Controls.Add(taskPanel, 0, 0);
            content.Controls.Add(detailPanel, 1, 0);

            var taskBar = new FlowLayoutPanel {
                Dock = DockStyle.Top, Height = 43, Padding = new Padding(2)
            };
            newTaskType = new ComboBox {
                Name = "NativeStructuredNewTaskType",
                Width = 142,
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            foreach (string key in TaskTypeOrder())
            {
                Dictionary<string, object> spec = AsDict(taskTypes, key);
                newTaskType.Items.Add(new Choice {
                    Key = key, Label = Str(spec, "label")
                });
            }
            if (newTaskType.Items.Count > 0) newTaskType.SelectedIndex = 0;
            taskBar.Controls.Add(newTaskType);
            taskBar.Controls.Add(EditorButton(
                "新增任务", "NativeStructuredTaskAdd", delegate { AddTask(); }));

            taskGrid = Grid("NativeStructuredTasks");
            taskGrid.ReadOnly = true;
            taskGrid.Columns.Add("id", "编号");
            taskGrid.Columns.Add("type", "类型");
            taskGrid.Columns.Add("priority", "优先级");
            taskGrid.Columns["id"].MinimumWidth = 130;
            taskGrid.Columns["type"].MinimumWidth = 100;
            taskGrid.Columns["priority"].MinimumWidth = 65;
            taskGrid.Columns["type"].FillWeight = 52;
            taskGrid.Columns["priority"].FillWeight = 34;
            taskGrid.CellDoubleClick += delegate(object sender,
                                                  DataGridViewCellEventArgs e) {
                if (e.RowIndex < 0) return;
                EditTaskTargetGeometry();
            };
            taskGrid.SelectionChanged += delegate {
                if (!applying) {
                    RefreshTaskDetails();
                    RefreshTargetSlotChoices();
                    RefreshTargetRows();
                }
            };

            var taskActions = new FlowLayoutPanel {
                Dock = DockStyle.Bottom, Height = 88, Padding = new Padding(2)
            };
            taskActions.Controls.Add(EditorButton(
                "编辑目标几何", "NativeStructuredTaskGeometry",
                delegate { EditTaskTargetGeometry(); }));
            taskActions.Controls.Add(EditorButton(
                "复制任务", "NativeStructuredTaskCopy",
                delegate { DuplicateTask(); }));
            taskActions.Controls.Add(EditorButton(
                "删除任务", "NativeStructuredTaskDelete",
                delegate { DeleteTask(); }));
            taskActions.Controls.Add(EditorButton(
                "推荐地图位置", "NativeStructuredTaskRecommend",
                async delegate { await PreviewTaskAsync(true); }));
            taskActions.Controls.Add(EditorButton(
                "任务试算", "NativeStructuredTaskPreview",
                async delegate { await PreviewTaskAsync(false); }));
            taskPanel.Controls.Add(taskGrid);
            taskPanel.Controls.Add(taskActions);
            taskPanel.Controls.Add(taskBar);

            var parameterBar = new FlowLayoutPanel {
                Dock = DockStyle.Top, Height = 43, Padding = new Padding(2)
            };
            parameterBar.Controls.Add(EditorButton(
                "编辑字段", "NativeStructuredParameterEdit",
                delegate { EditSelectedParameter(); }));
            parameterBar.Controls.Add(EditorButton(
                "移除可选参数", "NativeStructuredParameterRemove",
                delegate { RemoveSelectedParameter(); }));
            parameterBar.Controls.Add(new Label {
                Text = "双击目录字段可编辑；未设置的目录字段会从模板加入。",
                AutoSize = true,
                ForeColor = Color.SlateGray,
                Margin = new Padding(8, 8, 0, 0)
            });

            parameterGrid = Grid("NativeStructuredParameters");
            parameterGrid.ReadOnly = true;
            parameterGrid.Columns.Add("field", "字段");
            parameterGrid.Columns.Add("value", "当前值");
            parameterGrid.Columns.Add("kind", "类型");
            parameterGrid.Columns.Add("source", "来源");
            parameterGrid.Columns[0].FillWeight = 34;
            parameterGrid.Columns[1].FillWeight = 48;
            parameterGrid.Columns[2].FillWeight = 14;
            parameterGrid.Columns[3].FillWeight = 16;
            parameterGrid.CellDoubleClick += delegate(object sender,
                                                      DataGridViewCellEventArgs e) {
                if (e.RowIndex >= 0) EditSelectedParameter();
            };
            detailPanel.Controls.Add(parameterGrid);
            detailPanel.Controls.Add(parameterBar);

            taskPage.Controls.Add(content);
            tabs.TabPages.Add(taskPage);

            TabPage targetPage = new TabPage("红方目标") {
                BackColor = Color.White, Padding = new Padding(7)
            };
            var targetBar = new FlowLayoutPanel {
                Dock = DockStyle.Top, Height = 47, Padding = new Padding(2)
            };
            targetSlot = new ComboBox {
                Name = "NativeStructuredTargetSlot",
                Width = 185,
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            targetBar.Controls.Add(new Label {
                Text = "新增用途", AutoSize = true,
                Margin = new Padding(0, 9, 4, 0)
            });
            targetBar.Controls.Add(targetSlot);
            targetBar.Controls.Add(EditorButton(
                "新增目标", "NativeStructuredTargetAdd",
                delegate { AddTarget(); }));
            targetBar.Controls.Add(EditorButton(
                "编辑目标", "NativeStructuredTargetEdit",
                delegate { EditSelectedTarget(); }));
            targetBar.Controls.Add(EditorButton(
                "删除目标", "NativeStructuredTargetDelete",
                delegate { DeleteSelectedTarget(); }));
            targetGrid = Grid("NativeStructuredTargets");
            targetGrid.ReadOnly = true;
            targetGrid.Columns.Add("slot", "用途");
            targetGrid.Columns.Add("task", "所属任务");
            targetGrid.Columns.Add("target_id", "目标编号");
            targetGrid.Columns.Add("start", "起点 / 突击点");
            targetGrid.Columns.Add("goal", "终点");
            targetGrid.Columns.Add("detail", "其他字段");
            targetGrid.Columns["slot"].FillWeight = 15;
            targetGrid.Columns["task"].FillWeight = 13;
            targetGrid.Columns["target_id"].FillWeight = 18;
            targetGrid.Columns["start"].FillWeight = 18;
            targetGrid.Columns["goal"].FillWeight = 18;
            targetGrid.Columns["detail"].FillWeight = 34;
            targetGrid.CellDoubleClick += delegate(object sender,
                                                   DataGridViewCellEventArgs e) {
                if (e.RowIndex >= 0) EditSelectedTarget();
            };
            targetPage.Controls.Add(targetGrid);
            targetPage.Controls.Add(targetBar);
            targetPage.Controls.Add(new Label {
                Dock = DockStyle.Bottom,
                Height = 48,
                Padding = new Padding(8),
                ForeColor = Color.SlateGray,
                Text = "目标仍按现有 4.1 参数保存。突击目标来自任务几何，不能删除；删除其他目标会在保存时停用对应参数。"
            });
            tabs.TabPages.Add(targetPage);

            note = new Label {
                Name = "NativeStructuredNote",
                Dock = DockStyle.Bottom,
                Height = 46,
                Padding = new Padding(10),
                ForeColor = Color.SlateGray,
                Text = "编辑本轮输入草稿；保存后创建新的完整运行，原记录和模板不变。"
            };
            var bottom = new FlowLayoutPanel {
                Dock = DockStyle.Bottom,
                Height = 49,
                Padding = new Padding(8),
                FlowDirection = FlowDirection.RightToLeft,
                BackColor = Color.FromArgb(246, 249, 253)
            };
            var cancel = MainWindow.StandardButton("取消", 80);
            cancel.DialogResult = DialogResult.Cancel;
            save = MainWindow.StandardButton("检查并应用", 112);
            save.Name = "NativeStructuredSave";
            save.Click += async delegate { await SaveAsync(); };
            bottom.Controls.Add(cancel);
            bottom.Controls.Add(save);
            Controls.Add(tabs);
            Controls.Add(note);
            Controls.Add(bottom);
            CancelButton = cancel;

            FormClosing += delegate(object sender, FormClosingEventArgs e) {
                if (modified && DialogResult != DialogResult.OK
                    && MessageBox.Show(
                        this, "放弃专用表单中的修改？", "尚未应用",
                        MessageBoxButtons.YesNo, MessageBoxIcon.Question)
                       != DialogResult.Yes)
                {
                    e.Cancel = true;
                    DialogResult = DialogResult.None;
                }
            };

            RefreshTaskList(null);
            RefreshTargetSlotChoices();
            RefreshTargetRows();
            tabs.SelectedIndex = initialTab == 1 ? 1 : 0;
        }

        private static string[] TaskTypeOrder()
        {
            return new string[] {
                "T-RCN", "T-SEC", "T-PTL", "T-HLD", "T-ASL"
            };
        }

        private static string[] TargetSlotOrder()
        {
            return new string[] {
                "tracking", "observation", "relay", "intruder", "assault"
            };
        }

        private static DataGridView Grid(string name)
        {
            DataGridView grid = NativeInputData.Grid(name);
            grid.ReadOnly = true;
            grid.AutoGenerateColumns = false;
            grid.ColumnHeadersHeight = 34;
            return grid;
        }

        private static Button EditorButton(
            string text, string name, EventHandler action)
        {
            Button button = MainWindow.StandardButton(text, 104);
            button.Name = name;
            button.Click += action;
            return button;
        }

        private IList Tasks
        {
            get { return (IList)message["tasks"]; }
        }

        private Dictionary<string, object> SelectedTask
        {
            get
            {
                if (taskGrid.CurrentRow == null) return null;
                int index = taskGrid.CurrentRow.Index;
                return index >= 0 && index < Tasks.Count
                    ? Tasks[index] as Dictionary<string, object> : null;
            }
        }

        private void MarkModified()
        {
            if (!applying) modified = true;
        }

        private void RefreshTaskList(string selectId)
        {
            applying = true;
            taskGrid.Rows.Clear();
            int selected = -1;
            for (int i = 0; i < Tasks.Count; i++)
            {
                Dictionary<string, object> task =
                    Tasks[i] as Dictionary<string, object>;
                if (task == null) continue;
                int row = taskGrid.Rows.Add(
                    Str(task, "task_id"),
                    Str(task, "task_type"),
                    Str(task, "priority"));
                taskGrid.Rows[row].Tag = task;
                if (selectId != null
                    && Str(task, "task_id") == selectId) selected = row;
            }
            if (taskGrid.Rows.Count > 0)
            {
                if (selected < 0)
                    selected = Math.Min(
                        taskGrid.CurrentRow == null ? 0
                            : taskGrid.CurrentRow.Index,
                        taskGrid.Rows.Count - 1);
                taskGrid.CurrentCell = taskGrid.Rows[selected].Cells[0];
            }
            tabs.TabPages[0].Text = "任务专用表单 (" + Tasks.Count + ")";
            applying = false;
            RefreshTaskDetails();
        }

        private void RefreshTaskDetails()
        {
            parameterGrid.Rows.Clear();
            Dictionary<string, object> task = SelectedTask;
            if (task == null) return;
            string type = Str(task, "task_type");

            AddCommonRow(task, "任务编号", "@task_id", "text", true);
            AddCommonRow(task, "优先级", "@priority", "number", true);
            AddCommonRow(task, "时间窗开始（秒）", "@window_start", "number", true);
            AddCommonRow(task, "时间窗结束（秒）", "@window_end", "number", true);
            AddCommonRow(task, "最少平台数", "@min_units", "number", true);
            AddCommonRow(task, "最多平台数", "@max_units", "number", false);
            AddCommonRow(task, "任务说明", "@description", "text", false);
            AddCommonRow(task, "前置任务", "depends_on", "string_list", false);
            AddCommonRow(task, "目标几何", "target", "object", true);
            AddCommonRow(task, "能力要求", "required_capabilities", "object", true);
            AddCommonRow(task, "允许拆分", "allow_split", "bool", false);
            AddCommonRow(task, "额外约束", "constraints", "object", false);

            Dictionary<string, object> typeSpec = AsDict(taskTypes, type);
            IList catalog = Value(typeSpec, "params") as IList;
            Dictionary<string, object> parameters = AsDict(task, "params");
            var catalogKeys = new HashSet<string>(StringComparer.Ordinal);
            if (catalog != null)
            {
                foreach (object raw in catalog)
                {
                    Dictionary<string, object> entry =
                        raw as Dictionary<string, object>;
                    if (entry == null) continue;
                    string key = Str(entry, "key");
                    if (key.Length == 0) continue;
                    catalogKeys.Add(key);
                    bool exists = parameters.ContainsKey(key);
                    int row = parameterGrid.Rows.Add(
                        Str(entry, "label") + " (" + key + ")",
                        exists ? Summary(parameters[key]) : "未设置（双击加入）",
                        Str(entry, "kind"),
                        exists ? "任务参数" : "可选目录");
                    parameterGrid.Rows[row].Tag = new FieldRow {
                        Key = key,
                        Kind = Str(entry, "kind"),
                        Label = Str(entry, "label"),
                        Common = false,
                        Existing = exists,
                        Required = false
                    };
                }
            }

            var targetKeys = new HashSet<string>(StringComparer.Ordinal) {
                "tracking_target", "observation_target", "relay_target",
                "intruders", "target_id", "object_label"
            };
            foreach (KeyValuePair<string, object> pair in parameters)
            {
                if (catalogKeys.Contains(pair.Key)
                    || targetKeys.Contains(pair.Key)) continue;
                int row = parameterGrid.Rows.Add(
                    NativeInputData.Label(pair.Key),
                    Summary(pair.Value),
                    NativeKind(pair.Value),
                    "扩展参数");
                parameterGrid.Rows[row].Tag = new FieldRow {
                    Key = pair.Key,
                    Kind = NativeKind(pair.Value),
                    Label = NativeInputData.Label(pair.Key),
                    Common = false,
                    Existing = true,
                    Required = false
                };
            }

            tabs.TabPages[0].Text =
                "任务专用表单 · " + type + " · " + Str(task, "task_id");
        }

        private void AddCommonRow(
            Dictionary<string, object> task, string label,
            string key, string kind, bool required)
        {
            object value = CommonValue(task, key);
            int row = parameterGrid.Rows.Add(
                label, Summary(value), kind, "任务公共字段");
            parameterGrid.Rows[row].Tag = new FieldRow {
                Key = key,
                Kind = kind,
                Label = label,
                Common = true,
                Existing = value != null,
                Required = required
            };
        }

        private void EditSelectedParameter()
        {
            try
            {
                if (parameterGrid.CurrentRow == null) return;
                FieldRow spec =
                    parameterGrid.CurrentRow.Tag as FieldRow;
                Dictionary<string, object> task = SelectedTask;
                if (spec == null || task == null) return;
                object current;
                if (spec.Common)
                {
                    current = CommonValue(task, spec.Key);
                }
                else
                {
                    Dictionary<string, object> parameters =
                        AsDict(task, "params");
                    if (!parameters.ContainsKey(spec.Key))
                    {
                        current = CatalogTemplate(
                            Str(task, "task_type"), spec.Key);
                        if (current == Missing.Value)
                            throw new InvalidOperationException(
                                "找不到该参数的默认模板。");
                    }
                    else current = parameters[spec.Key];
                }

                object edited;
                if (!EditValue(this, spec.Kind, spec.Label, current,
                               out edited)) return;
                string oldTaskId = Str(task, "task_id");
                if (spec.Common)
                    SetCommonValue(task, spec.Key, edited);
                else
                    AsDict(task, "params")[spec.Key] =
                        NativeInputData.Copy(edited);
                MarkModified();
                string taskId = Str(task, "task_id");
                if (spec.Key == "@task_id")
                {
                    RenameTargetReferences(oldTaskId, taskId);
                }
                RefreshTaskList(taskId);
            }
            catch (Exception ex)
            {
                ShowError("字段未修改：" + ex.Message);
            }
        }

        private object CatalogTemplate(string taskType, string key)
        {
            Dictionary<string, object> type = AsDict(taskTypes, taskType);
            IList catalog = Value(type, "params") as IList;
            if (catalog != null)
            {
                foreach (object raw in catalog)
                {
                    Dictionary<string, object> entry =
                        raw as Dictionary<string, object>;
                    if (entry != null && Str(entry, "key") == key
                        && entry.ContainsKey("template"))
                    {
                        object template = NativeInputData.Copy(
                            entry["template"]);
                        IList templateList = template as IList;
                        if (templateList != null && templateList.Count == 0
                            && entry.ContainsKey("item"))
                            templateList.Add(NativeInputData.Copy(
                                entry["item"]));
                        return template;
                    }
                }
            }
            return Missing.Value;
        }

        private static bool EditValue(
            IWin32Window owner, string kind, string label,
            object current, out object edited)
        {
            edited = null;
            if (kind == "point")
                return NativeEditorValueDialog.EditPoint(
                    owner, label, current, out edited);
            if (kind == "number" || kind == "text" || kind == "bool")
                return NativeEditorValueDialog.EditScalar(
                    owner, label, kind, current, out edited);

            bool empty = current == null
                         || current is IList && ((IList)current).Count == 0
                         || current is Dictionary<string, object>
                            && ((Dictionary<string, object>)current).Count == 0;
            if (empty)
                return NativeEditorValueDialog.EditJson(
                    owner, label, current, out edited);
            using (NativeFieldEditor dialog =
                   new NativeFieldEditor(current, "编辑 · " + label))
            {
                if (dialog.ShowDialog(owner) != DialogResult.OK)
                    return false;
                edited = NativeInputData.Copy(dialog.Value);
                return true;
            }
        }

        private void RemoveSelectedParameter()
        {
            if (parameterGrid.CurrentRow == null) return;
            FieldRow spec = parameterGrid.CurrentRow.Tag as FieldRow;
            Dictionary<string, object> task = SelectedTask;
            if (spec == null || task == null || spec.Common
                || spec.Required) return;
            Dictionary<string, object> parameters = AsDict(task, "params");
            if (!parameters.ContainsKey(spec.Key))
            {
                note.Text = "该目录参数尚未设置。";
                return;
            }
            if (MessageBox.Show(
                    this, "移除参数 " + spec.Label + "？",
                    "移除任务参数", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) != DialogResult.Yes) return;
            parameters.Remove(spec.Key);
            MarkModified();
            RefreshTaskDetails();
        }

        private object CommonValue(
            Dictionary<string, object> task, string key)
        {
            switch (key)
            {
                case "@task_id": return task.ContainsKey("task_id")
                    ? task["task_id"] : "";
                case "@priority": return task.ContainsKey("priority")
                    ? task["priority"] : 1;
                case "@window_start":
                    return AsDict(task, "window").ContainsKey("start_s")
                        ? AsDict(task, "window")["start_s"] : 0;
                case "@window_end":
                    return AsDict(task, "window").ContainsKey("end_s")
                        ? AsDict(task, "window")["end_s"] : 1;
                case "@min_units": return task.ContainsKey("min_units")
                    ? task["min_units"] : 1;
                case "@max_units": return task.ContainsKey("max_units")
                    ? task["max_units"] : null;
                case "@description": return task.ContainsKey("description")
                    ? task["description"] : "";
                default:
                    return task.ContainsKey(key) ? task[key] : null;
            }
        }

        private void SetCommonValue(
            Dictionary<string, object> task, string key, object value)
        {
            switch (key)
            {
                case "@window_start":
                    AsDict(task, "window")["start_s"] = value;
                    break;
                case "@window_end":
                    AsDict(task, "window")["end_s"] = value;
                    break;
                case "@task_id":
                    task["task_id"] = value;
                    break;
                case "@priority":
                case "@min_units":
                case "@max_units":
                case "@description":
                    task[key.Substring(1)] = value;
                    break;
                default:
                    task[key] = NativeInputData.Copy(value);
                    break;
            }
        }

        private void RenameTargetReferences(string oldId, string newId)
        {
            foreach (object raw in targets)
            {
                Dictionary<string, object> target =
                    raw as Dictionary<string, object>;
                if (target != null && Str(target, "task_id") == oldId)
                    target["task_id"] = newId;
            }
            foreach (object raw in Tasks)
            {
                Dictionary<string, object> task =
                    raw as Dictionary<string, object>;
                if (task == null) continue;
                object dependenciesRaw;
                if (!task.TryGetValue("depends_on", out dependenciesRaw))
                    continue;
                IList dependencies = dependenciesRaw as IList;
                if (dependencies == null) continue;
                for (int i = 0; i < dependencies.Count; i++)
                    if (Convert.ToString(
                            dependencies[i], CultureInfo.InvariantCulture)
                        == oldId)
                        dependencies[i] = newId;
            }
        }

        private void AddTask()
        {
            Choice choice = newTaskType.SelectedItem as Choice;
            if (choice == null) return;
            Dictionary<string, object> typeSpec =
                AsDict(taskTypes, choice.Key);
            Dictionary<string, object> demo =
                AsDict(typeSpec, "demo");
            string taskId = UniqueTaskId(choice.Key);
            if (demo.Count > 0)
            {
                Dictionary<string, object> copied =
                    (Dictionary<string, object>)NativeInputData.Copy(demo);
                copied["task_id"] = taskId;
                if (copied.ContainsKey("description"))
                    copied["description"] = Str(typeSpec, "label")
                        + "（模板新建）";
                Tasks.Add(copied);
                MarkModified();
                RefreshTaskList(taskId);
                return;
            }
            Dictionary<string, object> defaults =
                AsDict(typeSpec, "defaults");
            Dictionary<string, object> task =
                new Dictionary<string, object> {
                    { "task_id", taskId },
                    { "task_type", choice.Key },
                    { "priority", defaults.ContainsKey("priority")
                        ? NativeInputData.Copy(defaults["priority"]) : 3 },
                    { "target", NativeInputData.Copy(
                        Value(typeSpec, "target")) },
                    { "window", new Dictionary<string, object> {
                        { "start_s", 0 }, { "end_s", 300 } } },
                    { "required_capabilities",
                        new Dictionary<string, object>() },
                    { "min_units", defaults.ContainsKey("min_units")
                        ? NativeInputData.Copy(defaults["min_units"]) : 1 },
                    { "max_units", defaults.ContainsKey("max_units")
                        ? NativeInputData.Copy(defaults["max_units"]) : 1 },
                    { "params", defaults.ContainsKey("params")
                        ? NativeInputData.Copy(defaults["params"])
                        : new Dictionary<string, object>() },
                    { "description", Str(typeSpec, "label")
                        + "（专用表单新建）" }
                };
            Tasks.Add(task);
            MarkModified();
            RefreshTaskList(taskId);
        }

        private async System.Threading.Tasks.Task PreviewTaskAsync(
            bool recommend)
        {
            Dictionary<string, object> task = SelectedTask;
            if (task == null) return;
            try
            {
                save.Enabled = false;
                tabs.Enabled = false;
                note.ForeColor = Color.SlateGray;
                note.Text = recommend
                    ? "正在推荐不与其他任务冲突的地图位置…"
                    : "正在试算平台席位、时间和可选平台…";
                Dictionary<string, object> source =
                    (Dictionary<string, object>)NativeInputData.Copy(message);
                IList targetCopy =
                    (IList)NativeInputData.Copy(targets);
                Dictionary<string, object> applied =
                    await System.Threading.Tasks.Task.Run(delegate {
                        return api.ApplyEditorTargets(source, targetCopy);
                    });
                if (IsDisposed) return;
                Dictionary<string, object> request =
                    new Dictionary<string, object> {
                        { "message", applied["message"] },
                        { "formation", Draft["formation"] },
                        { "task_id", Str(task, "task_id") },
                        { "recommend", recommend },
                        { "now", 0 },
                        { "occupied", new List<object>() },
                        { "completed", new List<object>() },
                        { "objective", Str((Dictionary<string, object>)Draft["request"], "objective") },
                        { "max_ticks", Value(
                            (Dictionary<string, object>)Draft["request"],
                            "max_ticks") }
                    };
                Dictionary<string, object> preview =
                    await System.Threading.Tasks.Task.Run(delegate {
                        return api.PreviewTask(request);
                    });
                if (IsDisposed) return;
                string error = Str(preview, "error");
                if (error.Length > 0)
                    throw new InvalidOperationException(error);
                IList slots = Value(preview, "slots") as IList;
                string assignment = slots == null ? ""
                    : string.Join("；", slots.Cast<object>().Select(
                        delegate(object raw) {
                            Dictionary<string, object> slot =
                                raw as Dictionary<string, object>;
                            return Str(slot, "role") + "="
                                + (Str(slot, "unit_id").Length > 0
                                    ? Str(slot, "unit_id") : "自动分配");
                        }).ToArray());
                if (!recommend && slots != null) EditSeatAssignments(task, slots);
                if (recommend)
                {
                    ApplyPreview(task, preview);
                    MarkModified();
                    RefreshTaskList(Str(task, "task_id"));
                    RefreshTargetSlotChoices();
                    RefreshTargetRows();
                }
                note.ForeColor = Color.DarkGreen;
                note.Text = (recommend ? "已应用地图推荐位置。" : "试算通过。")
                    + (assignment.Length > 0 ? " 席位：" + assignment : "")
                    + " 修改席位后请再次试算；保存前会进行完整校验。";
            }
            catch (Exception ex)
            {
                if (!IsDisposed)
                {
                    note.ForeColor = Color.Firebrick;
                    note.Text = "试算未通过：" + ex.Message;
                    MessageBox.Show(this, ex.Message, "任务试算",
                                    MessageBoxButtons.OK,
                                    MessageBoxIcon.Warning);
                }
            }
            finally
            {
                if (!IsDisposed) {
                    save.Enabled = true;
                    tabs.Enabled = true;
                }
            }
        }

        private void EditSeatAssignments(Dictionary<string, object> task, IList slots)
        {
            using (Form dialog = new Form())
            {
                dialog.Text = "任务席位与平台选择";
                dialog.Size = new Size(650, 430);
                dialog.StartPosition = FormStartPosition.CenterParent;
                var grid = new DataGridView { Dock = DockStyle.Fill,
                    AllowUserToAddRows = false, AllowUserToDeleteRows = false,
                    AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill };
                grid.Columns.Add("role", "任务席位");
                grid.Columns[0].ReadOnly = true;
                grid.Columns.Add(new DataGridViewComboBoxColumn {
                    Name = "unit", HeaderText = "自动 / 平台类别 / 具体平台" });
                var parameters = AsDict(task, "params");
                var pins = AsDict(parameters, "_slot_units");
                foreach (object raw in slots)
                {
                    var slot = raw as Dictionary<string, object>;
                    int index = grid.Rows.Add(Str(slot, "role"));
                    var row = grid.Rows[index];
                    row.Tag = Str(slot, "key");
                    var cell = (DataGridViewComboBoxCell)row.Cells[1];
                    cell.Items.Add("自动");
                    foreach (string kind in new [] { "UGV", "TANK", "PLANE", "WING" })
                        cell.Items.Add("类别：" + kind);
                    IList eligible = Value(slot, "eligible") as IList;
                    if (eligible != null) foreach (object unit in eligible)
                        cell.Items.Add(Convert.ToString(unit));
                    object pin = Value(pins, Str(slot, "key"));
                    var category = pin as Dictionary<string, object>;
                    string selected = category != null ? "类别：" + Str(category, "platform_class")
                        : pin == null ? "自动" : Convert.ToString(pin);
                    if (!cell.Items.Contains(selected)) cell.Items.Add(selected);
                    cell.Value = selected;
                }
                var apply = new Button { Text = "应用席位选择", Dock = DockStyle.Bottom,
                    Height = 38, DialogResult = DialogResult.OK };
                dialog.Controls.Add(grid);
                dialog.Controls.Add(apply);
                dialog.AcceptButton = apply;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                grid.EndEdit();
                var choices = new Dictionary<string, object>();
                foreach (DataGridViewRow row in grid.Rows)
                {
                    string selection = Convert.ToString(row.Cells[1].Value);
                    if (selection == "自动") continue;
                    choices[Convert.ToString(row.Tag)] = selection.StartsWith("类别：")
                        ? (object)new Dictionary<string, object> {
                            { "platform_class", selection.Substring(3) } }
                        : selection;
                }
                parameters["_slot_units"] = choices;
                task["params"] = parameters;
                MarkModified();
                RefreshTaskDetails();
            }
        }

        private void ApplyPreview(
            Dictionary<string, object> task,
            Dictionary<string, object> preview)
        {
            Dictionary<string, object> target =
                Value(preview, "target") as Dictionary<string, object>;
            if (target != null)
                task["target"] = NativeInputData.Copy(target);
            Dictionary<string, object> geometry =
                Value(preview, "geometry_params") as Dictionary<string, object>;
            if (geometry != null && geometry.Count > 0)
            {
                Dictionary<string, object> parameters =
                    task.ContainsKey("params")
                    ? task["params"] as Dictionary<string, object> : null;
                if (parameters == null)
                    parameters = new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in geometry)
                    parameters[pair.Key] = NativeInputData.Copy(pair.Value);
                task["params"] = parameters;
            }
            string taskId = Str(task, "task_id");
            IList previewTargets = Value(preview, "targets") as IList;
            if (previewTargets == null) return;
            for (int i = targets.Count - 1; i >= 0; i--)
            {
                Dictionary<string, object> item =
                    targets[i] as Dictionary<string, object>;
                if (item != null && Str(item, "task_id") == taskId)
                    targets.RemoveAt(i);
            }
            foreach (object raw in previewTargets)
                targets.Add(NativeInputData.Copy(raw));
        }

        private string UniqueTaskId(string taskType)
        {
            string stem = "NEW-" + taskType.Replace("T-", "");
            int number = 1;
            while (Tasks.Cast<object>().Any(delegate(object raw) {
                Dictionary<string, object> task =
                    raw as Dictionary<string, object>;
                return task != null && Str(task, "task_id")
                    == stem + "-" + number;
            })) number++;
            return stem + "-" + number;
        }

        private void DuplicateTask()
        {
            Dictionary<string, object> source = SelectedTask;
            if (source == null) return;
            Dictionary<string, object> copy =
                (Dictionary<string, object>)NativeInputData.Copy(source);
            string basis = Str(source, "task_id") + "-COPY";
            string id = basis;
            int number = 2;
            HashSet<string> ids = new HashSet<string>(
                Tasks.Cast<object>().Select(delegate(object raw) {
                    return Str(raw as Dictionary<string, object>, "task_id");
                }), StringComparer.Ordinal);
            while (ids.Contains(id)) id = basis + "-" + number++;
            copy["task_id"] = id;
            Tasks.Add(copy);
            MarkModified();
            RefreshTaskList(id);
        }

        private void DeleteTask()
        {
            Dictionary<string, object> task = SelectedTask;
            if (task == null) return;
            string id = Str(task, "task_id");
            if (MessageBox.Show(
                    this, "删除任务 " + id + "？保存时仍须至少保留一项任务。",
                    "删除任务", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning) != DialogResult.Yes) return;
            Tasks.Remove(task);
            for (int i = targets.Count - 1; i >= 0; i--)
            {
                Dictionary<string, object> target =
                    targets[i] as Dictionary<string, object>;
                if (target != null && Str(target, "task_id") == id)
                    targets.RemoveAt(i);
            }
            MarkModified();
            RefreshTaskList(null);
            RefreshTargetSlotChoices();
            RefreshTargetRows();
        }

        private void EditTaskTargetGeometry()
        {
            Dictionary<string, object> task = SelectedTask;
            if (task == null) return;
            using (NativeFieldEditor dialog = new NativeFieldEditor(
                       task["target"], "编辑任务目标几何 · "
                       + Str(task, "task_id")))
            {
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    task["target"] =
                        (Dictionary<string, object>)NativeInputData.Copy(
                            dialog.Value);
                    MarkModified();
                    RefreshTaskDetails();
                }
            }
        }

        private void RefreshTargetSlotChoices()
        {
            targetSlot.Items.Clear();
            Dictionary<string, object> task = SelectedTask;
            if (task == null) return;
            string taskId = Str(task, "task_id");
            string taskType = Str(task, "task_type");
            foreach (string key in TargetSlotOrder())
            {
                Dictionary<string, object> spec = AsDict(targetSlots, key);
                IList applies = Value(spec, "task_types") as IList;
                if (applies == null || !applies.Cast<object>().Any(
                        value => Convert.ToString(
                            value, CultureInfo.InvariantCulture) == taskType))
                    continue;
                bool multi = Convert.ToBoolean(
                    Value(spec, "multi"), CultureInfo.InvariantCulture);
                if (!multi && targets.Cast<object>().Any(delegate(object raw) {
                        Dictionary<string, object> item =
                            raw as Dictionary<string, object>;
                        return item != null && Str(item, "slot") == key
                            && Str(item, "task_id") == taskId;
                    }))
                    continue;
                targetSlot.Items.Add(new Choice {
                    Key = key, Label = Str(spec, "label")
                });
            }
            if (targetSlot.Items.Count > 0) targetSlot.SelectedIndex = 0;
        }

        private void AddTarget()
        {
            Choice choice = targetSlot.SelectedItem as Choice;
            Dictionary<string, object> task = SelectedTask;
            if (choice == null || task == null) return;
            Dictionary<string, object> spec = AsDict(targetSlots, choice.Key);
            Dictionary<string, object> entry =
                new Dictionary<string, object> {
                    { "slot", choice.Key },
                    { "task_id", Str(task, "task_id") }
                };
            Dictionary<string, object> defaults = AsDict(spec, "defaults");
            foreach (KeyValuePair<string, object> pair in defaults)
                entry[pair.Key] = NativeInputData.Copy(pair.Value);
            IList fields = Value(spec, "fields") as IList;
            if (fields != null)
            {
                foreach (object rawField in fields)
                {
                    Dictionary<string, object> field =
                        rawField as Dictionary<string, object>;
                    if (field == null) continue;
                    string key = Str(field, "key");
                    if (entry.ContainsKey(key)) continue;
                    entry[key] = Str(field, "kind") == "point"
                        ? (object)new List<object> { 0, 0 }
                        : Str(field, "kind") == "bool"
                        ? (object)false : Str(field, "kind") == "number"
                        ? (object)0 : "";
                }
            }
            if (choice.Key == "target_id"|| entry.ContainsKey("target_id")
                && Convert.ToString(entry["target_id"]) == "")
                entry["target_id"] = "RED-" + (targets.Count + 1);
            if (choice.Key == "assault")
            {
                entry["kind"] = "point";
                if (!entry.ContainsKey("object_label"))
                    entry["object_label"] = "新建突击目标";
                Dictionary<string, object> geometry =
                    AsDict(task, "target");
                if (geometry.ContainsKey("point"))
                    entry["point"] = NativeInputData.Copy(geometry["point"]);
            }
            Dictionary<string, object> edited = EditTarget(entry);
            if (edited == null) return;
            targets.Add(edited);
            MarkModified();
            RefreshTargetSlotChoices();
            RefreshTargetRows();
        }

        private void EditSelectedTarget()
        {
            if (targetGrid.CurrentRow == null) return;
            Dictionary<string, object> old =
                targetGrid.CurrentRow.Tag as Dictionary<string, object>;
            if (old == null) return;
            Dictionary<string, object> edited = EditTarget(old);
            if (edited == null) return;
            int index = targets.IndexOf(old);
            if (index >= 0) targets[index] = edited;
            MarkModified();
            RefreshTargetRows();
        }

        private Dictionary<string, object> EditTarget(
            Dictionary<string, object> target)
        {
            string slot = Str(target, "slot");
            Dictionary<string, object> spec = AsDict(targetSlots, slot);
            using (NativeTargetDialog dialog = new NativeTargetDialog(
                       spec, target))
            {
                return dialog.ShowDialog(this) == DialogResult.OK
                    ? dialog.Value : null;
            }
        }

        private void DeleteSelectedTarget()
        {
            if (targetGrid.CurrentRow == null) return;
            Dictionary<string, object> target =
                targetGrid.CurrentRow.Tag as Dictionary<string, object>;
            if (target == null) return;
            string slot = Str(target, "slot");
            Dictionary<string, object> spec = AsDict(targetSlots, slot);
            if (!Convert.ToBoolean(
                    Value(spec, "deletable"), CultureInfo.InvariantCulture))
            {
                ShowError(Str(spec, "label") + "由任务几何决定，不能删除。"
                          + "请编辑任务的目标几何。");
                return;
            }
            if (MessageBox.Show(
                    this, "删除该" + Str(spec, "label") + "？保存后会停用对应参数。",
                    "删除红方目标", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) != DialogResult.Yes) return;
            targets.Remove(target);
            MarkModified();
            RefreshTargetSlotChoices();
            RefreshTargetRows();
        }

        private void RefreshTargetRows()
        {
            targetGrid.Rows.Clear();
            foreach (object raw in targets)
            {
                Dictionary<string, object> target =
                    raw as Dictionary<string, object>;
                if (target == null) continue;
                string slot = Str(target, "slot");
                Dictionary<string, object> spec = AsDict(targetSlots, slot);
                object start = target.ContainsKey("start")
                    ? target["start"] : target.ContainsKey("point")
                    ? target["point"] : null;
                object goal = target.ContainsKey("goal")
                    ? target["goal"] : null;
                var extra = new List<string>();
                foreach (KeyValuePair<string, object> pair in target)
                {
                    if (pair.Key == "slot" || pair.Key == "task_id"
                        || pair.Key == "kind" || pair.Key == "target_id"
                        || pair.Key == "object_label" || pair.Key == "start"
                        || pair.Key == "goal" || pair.Key == "point")
                        continue;
                    extra.Add(pair.Key + "=" + Summary(pair.Value));
                }
                string targetId = Str(target, "target_id");
                if (targetId.Length == 0) targetId = Str(target, "object_label");
                int row = targetGrid.Rows.Add(
                    Str(spec, "label"), Str(target, "task_id"), targetId,
                    Summary(start), Summary(goal), string.Join("；", extra));
                targetGrid.Rows[row].Tag = target;
            }
        }

        private async System.Threading.Tasks.Task SaveAsync()
        {
            try
            {
                save.Enabled = false;
                tabs.Enabled = false;
                note.ForeColor = Color.SlateGray;
                note.Text = "正在写回红方目标并校验五类任务、平台与依赖关系…";
                Dictionary<string, object> source =
                    (Dictionary<string, object>)NativeInputData.Copy(message);
                IList targetCopy =
                    (IList)NativeInputData.Copy(targets);
                Dictionary<string, object> applied =
                    await System.Threading.Tasks.Task.Run(delegate {
                        return api.ApplyEditorTargets(source, targetCopy);
                    });
                if (IsDisposed) return;
                message = (Dictionary<string, object>)applied["message"];
                Draft["message"] = message;
                Dictionary<string, object> checkedDraft =
                    await System.Threading.Tasks.Task.Run(delegate {
                        return api.ValidateDraft(
                            (Dictionary<string, object>)
                            NativeInputData.Copy(Draft));
                    });
                if (IsDisposed) return;
                Draft = (Dictionary<string, object>)checkedDraft["draft"];
                modified = false;
                DialogResult = DialogResult.OK;
                Close();
            }
            catch (Exception ex)
            {
                if (!IsDisposed)
                {
                    note.ForeColor = Color.Firebrick;
                    note.Text = "检查未通过，修改保留：" + ex.Message;
                }
            }
            finally
            {
                if (!IsDisposed)
                {
                    save.Enabled = true;
                    tabs.Enabled = true;
                }
            }
        }

        private void ShowError(string text)
        {
            note.ForeColor = Color.Firebrick;
            note.Text = text;
            MessageBox.Show(this, text, "任务专用表单",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        private static string Summary(object value)
        {
            if (value == null) return "未设置";
            return NativeInputData.Summary(value);
        }

        private static string NativeKind(object value)
        {
            if (value is IList) return "point_list";
            if (value is Dictionary<string, object>) return "object";
            if (value is bool) return "bool";
            if (value is string) return "text";
            if (value == null) return "text";
            return "number";
        }

        private static Dictionary<string, object> AsDict(
            Dictionary<string, object> parent, string key)
        {
            return Value(parent, key) as Dictionary<string, object>
                ?? new Dictionary<string, object>();
        }

        private static object Value(
            Dictionary<string, object> parent, string key)
        {
            object value;
            return parent != null && parent.TryGetValue(key, out value)
                ? value : null;
        }

        private static string Str(
            Dictionary<string, object> parent, string key)
        {
            object value = Value(parent, key);
            return value == null ? "" : Convert.ToString(
                value, CultureInfo.InvariantCulture);
        }

        private static IList CopyList(
            Dictionary<string, object> parent, string key)
        {
            IList source = Value(parent, key) as IList;
            return source == null
                ? new List<object>()
                : (IList)NativeInputData.Copy(source);
        }
    }

    internal sealed class NativeEditorValueDialog : Form
    {
        private readonly string kind;
        private readonly TextBox text;
        private readonly ComboBox boolean;
        private readonly Label error;
        internal object Value { get; private set; }

        private NativeEditorValueDialog(
            string label, string kind, object current, bool json)
        {
            this.kind = kind;
            Text = "编辑 · " + label;
            Font = new Font("Microsoft YaHei UI", 9f);
            BackColor = Color.White;
            Size = new Size(json ? 700 : 520, json ? 480 : 170);
            MinimumSize = new Size(420, 145);
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;

            Label caption = new Label {
                Text = label, Dock = DockStyle.Top, Height = 36,
                Padding = new Padding(10, 8, 0, 0)
            };
            text = new TextBox {
                Dock = DockStyle.Fill, Multiline = json,
                ScrollBars = json ? ScrollBars.Both : ScrollBars.None,
                WordWrap = false, Font = json
                    ? new Font("Consolas", 10f) : Font,
                Text = current == null ? "" : kind == "point" || json
                    || current is IList
                    || current is Dictionary<string, object>
                    ? (kind == "point"
                        ? NativeInputData.Json.Serialize(current)
                        : DesktopApi.Pretty(current))
                    : Convert.ToString(current, CultureInfo.InvariantCulture)
            };
            boolean = new ComboBox {
                Dock = DockStyle.Top, DropDownStyle = ComboBoxStyle.DropDownList
            };
            boolean.Items.AddRange(new object[] { "true", "false" });
            boolean.SelectedItem = current is bool && (bool)current
                ? "true" : "false";
            error = new Label {
                Dock = DockStyle.Bottom, Height = 32, ForeColor = Color.Firebrick
            };
            FlowLayoutPanel buttons = new FlowLayoutPanel {
                Dock = DockStyle.Bottom, Height = 43,
                FlowDirection = FlowDirection.RightToLeft,
                Padding = new Padding(5)
            };
            Button cancel = MainWindow.StandardButton("取消", 76);
            cancel.DialogResult = DialogResult.Cancel;
            Button ok = MainWindow.StandardButton("确定", 76);
            ok.Name = "NativeEditorValueSave";
            ok.Click += delegate {
                try
                {
                    Value = ParseValue();
                    DialogResult = DialogResult.OK;
                    Close();
                }
                catch (Exception ex)
                {
                    error.Text = ex.Message;
                }
            };
            buttons.Controls.Add(cancel);
            buttons.Controls.Add(ok);
            Panel body = new Panel {
                Dock = DockStyle.Fill, Padding = new Padding(12)
            };
            if (kind == "bool") body.Controls.Add(boolean);
            else body.Controls.Add(text);
            Controls.Add(body);
            Controls.Add(error);
            Controls.Add(buttons);
            Controls.Add(caption);
            CancelButton = cancel;
        }

        private object ParseValue()
        {
            if (kind == "bool")
                return Convert.ToString(boolean.SelectedItem) == "true";
            string value = text.Text.Trim();
            if (kind == "text")
            {
                if (value == "null") return null;
                return text.Text;
            }
            if (kind == "number")
            {
                decimal parsed;
                if (!decimal.TryParse(value, NumberStyles.Float,
                                      CultureInfo.InvariantCulture, out parsed)
                    && !decimal.TryParse(value, NumberStyles.Float,
                                         CultureInfo.CurrentCulture, out parsed))
                    throw new FormatException("请输入有限数字。");
                double number = (double)parsed;
                if (double.IsNaN(number) || double.IsInfinity(number))
                    throw new FormatException("数字必须有限。");
                return number;
            }
            if (kind == "point")
            {
                double x, y;
                string cleaned = value.Trim('[', ']', ' ');
                string[] parts = cleaned.Split(new char[] { ',', ' ' },
                    StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length != 2
                    || !double.TryParse(parts[0], NumberStyles.Float,
                                        CultureInfo.InvariantCulture, out x)
                    && !double.TryParse(parts[0], NumberStyles.Float,
                                        CultureInfo.CurrentCulture, out x)
                    || !double.TryParse(parts[1], NumberStyles.Float,
                                        CultureInfo.InvariantCulture, out y)
                    && !double.TryParse(parts[1], NumberStyles.Float,
                                        CultureInfo.CurrentCulture, out y))
                    throw new FormatException("坐标格式应为 [x, y]。");
                if (double.IsNaN(x) || double.IsInfinity(x)
                    || double.IsNaN(y) || double.IsInfinity(y))
                    throw new FormatException("坐标必须是有限数。");
                return new List<object> { x, y };
            }
            object result = NativeInputData.Json.DeserializeObject(text.Text);
            if (result == null) throw new FormatException("JSON 不能为空。");
            return result;
        }

        internal static bool EditScalar(
            IWin32Window owner, string label, string kind,
            object current, out object edited)
        {
            using (NativeEditorValueDialog dialog =
                   new NativeEditorValueDialog(label, kind, current, false))
            {
                edited = dialog.ShowDialog(owner) == DialogResult.OK
                    ? dialog.Value : null;
                return dialog.DialogResult == DialogResult.OK;
            }
        }

        internal static bool EditPoint(
            IWin32Window owner, string label,
            object current, out object edited)
        {
            using (NativeEditorValueDialog dialog =
                   new NativeEditorValueDialog(label, "point", current, false))
            {
                edited = dialog.ShowDialog(owner) == DialogResult.OK
                    ? dialog.Value : null;
                return dialog.DialogResult == DialogResult.OK;
            }
        }

        internal static bool EditJson(
            IWin32Window owner, string label,
            object current, out object edited)
        {
            using (NativeEditorValueDialog dialog =
                   new NativeEditorValueDialog(
                       label, "json", current, true))
            {
                edited = dialog.ShowDialog(owner) == DialogResult.OK
                    ? dialog.Value : null;
                return dialog.DialogResult == DialogResult.OK;
            }
        }
    }

    internal sealed class NativeTargetDialog : Form
    {
        private sealed class ControlSpec
        {
            internal string Key, Kind;
            internal Control Input;
        }

        private readonly List<ControlSpec> fields =
            new List<ControlSpec>();
        private readonly Dictionary<string, object> source;
        private readonly Label error;
        internal Dictionary<string, object> Value { get; private set; }

        internal NativeTargetDialog(
            Dictionary<string, object> slot,
            Dictionary<string, object> target)
        {
            source = (Dictionary<string, object>)NativeInputData.Copy(target);
            Text = "编辑 · " + Convert.ToString(
                slot.ContainsKey("label") ? slot["label"] : "红方目标");
            Font = new Font("Microsoft YaHei UI", 9f);
            BackColor = Color.White;
            Size = new Size(570, 520);
            MinimumSize = new Size(480, 390);
            StartPosition = FormStartPosition.CenterParent;

            Label heading = new Label {
                Dock = DockStyle.Top, Height = 49,
                Padding = new Padding(12, 8, 0, 0),
                Text = Convert.ToString(
                    slot.ContainsKey("label") ? slot["label"] : "红方目标")
                    + "  ·  任务 " + Convert.ToString(
                        target.ContainsKey("task_id")
                        ? target["task_id"] : "")
            };
            TableLayoutPanel table = new TableLayoutPanel {
                Dock = DockStyle.Top,
                AutoSize = true,
                ColumnCount = 2,
                Padding = new Padding(12),
                ColumnStyles = {
                    new ColumnStyle(SizeType.Absolute, 145),
                    new ColumnStyle(SizeType.Percent, 100)
                }
            };
            IList specs = slot.ContainsKey("fields")
                ? slot["fields"] as IList : null;
            if (specs != null)
            {
                foreach (object raw in specs)
                {
                    Dictionary<string, object> field =
                        raw as Dictionary<string, object>;
                    if (field == null) continue;
                    string key = Convert.ToString(
                        field.ContainsKey("key") ? field["key"] : "");
                    string kind = Convert.ToString(
                        field.ContainsKey("kind") ? field["kind"] : "text");
                    string label = Convert.ToString(
                        field.ContainsKey("label") ? field["label"] : key);
                    table.RowStyles.Add(
                        new RowStyle(SizeType.Absolute, 43));
                    table.Controls.Add(new Label {
                        Text = label,
                        AutoSize = true,
                        Margin = new Padding(0, 8, 8, 0)
                    });
                    Control input = TargetInput(kind, target.ContainsKey(key)
                        ? target[key] : null);
                    input.Dock = DockStyle.Fill;
                    input.Margin = new Padding(0, 4, 0, 0);
                    table.Controls.Add(input);
                    fields.Add(new ControlSpec {
                        Key = key, Kind = kind, Input = input
                    });
                }
            }
            Panel scroll = new Panel {
                Dock = DockStyle.Fill, AutoScroll = true
            };
            scroll.Controls.Add(table);
            error = new Label {
                Dock = DockStyle.Bottom, Height = 46,
                Padding = new Padding(8), ForeColor = Color.Firebrick
            };
            FlowLayoutPanel buttons = new FlowLayoutPanel {
                Dock = DockStyle.Bottom, Height = 46,
                FlowDirection = FlowDirection.RightToLeft,
                Padding = new Padding(8)
            };
            Button cancel = MainWindow.StandardButton("取消", 76);
            cancel.DialogResult = DialogResult.Cancel;
            Button ok = MainWindow.StandardButton("应用目标", 92);
            ok.Name = "NativeTargetDialogSave";
            ok.Click += delegate {
                try
                {
                    Value = Commit();
                    DialogResult = DialogResult.OK;
                    Close();
                }
                catch (Exception ex) { error.Text = ex.Message; }
            };
            buttons.Controls.Add(cancel);
            buttons.Controls.Add(ok);
            Controls.Add(scroll);
            Controls.Add(error);
            Controls.Add(buttons);
            Controls.Add(heading);
            CancelButton = cancel;
        }

        private static Control TargetInput(string kind, object value)
        {
            if (kind == "bool")
            {
                ComboBox combo = new ComboBox {
                    DropDownStyle = ComboBoxStyle.DropDownList
                };
                combo.Items.AddRange(new object[] { "true", "false" });
                combo.SelectedItem = value is bool && (bool)value
                    ? "true" : "false";
                return combo;
            }
            TextBox text = new TextBox {
                Text = value == null ? "" : kind == "point"
                    || value is IList
                    || value is Dictionary<string, object>
                    ? (kind == "point"
                        ? NativeInputData.Json.Serialize(value)
                        : DesktopApi.Pretty(value))
                    : Convert.ToString(value, CultureInfo.InvariantCulture)
            };
            return text;
        }

        private Dictionary<string, object> Commit()
        {
            Dictionary<string, object> result =
                (Dictionary<string, object>)NativeInputData.Copy(source);
            foreach (ControlSpec field in fields)
            {
                if (field.Kind == "bool")
                {
                    result[field.Key] = Convert.ToString(
                        ((ComboBox)field.Input).SelectedItem) == "true";
                    continue;
                }
                string text = ((TextBox)field.Input).Text.Trim();
                if (field.Kind == "text") result[field.Key] = text;
                else if (field.Kind == "number")
                {
                    double number;
                    if (!double.TryParse(text, NumberStyles.Float,
                                         CultureInfo.InvariantCulture,
                                         out number)
                        && !double.TryParse(text, NumberStyles.Float,
                                            CultureInfo.CurrentCulture,
                                            out number))
                        throw new FormatException("请输入有效数字：" + field.Key);
                    if (number < 0 && field.Key != "t_start_s")
                        throw new FormatException(
                            "该数值不能为负：" + field.Key);
                    result[field.Key] = number;
                }
                else if (field.Kind == "point")
                {
                    string cleaned = text.Trim('[', ']', ' ');
                    string[] parts = cleaned.Split(
                        new char[] { ',', ' ' },
                        StringSplitOptions.RemoveEmptyEntries);
                    double x, y;
                    if (parts.Length != 2
                        || !double.TryParse(parts[0], NumberStyles.Float,
                                            CultureInfo.InvariantCulture,
                                            out x)
                        && !double.TryParse(parts[0], NumberStyles.Float,
                                            CultureInfo.CurrentCulture,
                                            out x)
                        || !double.TryParse(parts[1], NumberStyles.Float,
                                            CultureInfo.InvariantCulture,
                                            out y)
                        && !double.TryParse(parts[1], NumberStyles.Float,
                                            CultureInfo.CurrentCulture,
                                            out y))
                        throw new FormatException(
                            "坐标格式应为 [x, y]：" + field.Key);
                    result[field.Key] = new List<object> { x, y };
                }
                else result[field.Key] = NativeInputData.Json
                    .DeserializeObject(text);
            }
            return result;
        }
    }
}
