using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    // Edit a copy of the input document. Unknown fields and collection order survive.
    internal static class NativeInputData
    {
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 };
        internal static object Copy(object value) { return Normalize(Json.DeserializeObject(Json.Serialize(value))); }
        private static object Normalize(object value)
        {
            var map = value as Dictionary<string, object>;
            if (map != null) return map.ToDictionary(p => p.Key, p => Normalize(p.Value));
            var list = value as IList;
            if (list != null) return list.Cast<object>().Select(Normalize).ToList();
            return value;
        }
        internal static string Text(Dictionary<string, object> row, string key) { return row.ContainsKey(key) ? Convert.ToString(row[key], CultureInfo.InvariantCulture) : ""; }
        internal static string Label(string key)
        {
            string label;
            return Labels.TryGetValue(key, out label) ? label + " (" + key + ")" : key;
        }
        private static readonly Dictionary<string, string> Labels = new Dictionary<string, string> {
            {"task_id","任务编号"},{"task_type","任务类别"},{"description","说明"},{"priority","优先级"},
            {"target","目标几何"},{"area","区域顶点"},{"point","单点"},{"key_point","关键点"},
            {"defense_area","区域顶点"},{"patrol_area","巡逻区域"},{"route","路线点"},{"target_list","点列表"},
            {"window","时间窗"},{"start_s","开始时间 / 秒"},{"end_s","结束时间 / 秒"},
            {"min_units","最少平台数"},{"max_units","最多平台数"},{"params","其他参数"},
            {"depends_on","前置任务"},{"prerequisites","前置任务"},{"duration_s","时长 / 秒"},
            {"unit_id","平台编号"},{"robot_id","机器人编号"},{"platform_class","平台类别"},{"platform_type","平台型号"},
            {"position","初始位置"},{"x","X 坐标"},{"y","Y 坐标"},{"z","Z 坐标"},{"altitude_m","高度 / 米"},
            {"heading_rad","航向 / 弧度"},{"status","状态"},{"speed_mps","速度 / 米每秒"},
            {"endurance_s","续航 / 秒"},{"vertical_speed_mps","垂直速度 / 米每秒"},
            {"capabilities","平台能力"},{"required_capabilities","能力要求"},{"constraints","约束"},
            {"allow_split","允许拆分"},{"groups","编组"},{"battery","电量"}
        };
        internal static string Summary(object value)
        {
            var map = value as Dictionary<string, object>; if (map != null) return "对象 · " + map.Count + " 项（双击展开）";
            var list = value as IList; if (list != null) return list.Count>0 && list.Count<=6 && list.Cast<object>().All(v=>!(v is IList)&&!(v is Dictionary<string,object>)) ? Json.Serialize(list)+"（双击展开）" : "列表 · " + list.Count + " 项（双击展开）";
            return value == null ? "null" : value is bool ? ((bool)value ? "true" : "false") : Convert.ToString(value, CultureInfo.InvariantCulture);
        }
        internal static DataGridView Grid(string name)
        {
            return new DataGridView { Name=name, Dock=DockStyle.Fill, BackgroundColor=Color.White, BorderStyle=BorderStyle.None,
                AllowUserToAddRows=false, AllowUserToDeleteRows=false, RowHeadersVisible=false, MultiSelect=false,
                SelectionMode=DataGridViewSelectionMode.FullRowSelect, AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill,
                AutoGenerateColumns=false, RowTemplate={Height=29}, EnableHeadersVisualStyles=false,
                ColumnHeadersDefaultCellStyle=new DataGridViewCellStyle { BackColor=Color.FromArgb(233,241,251), ForeColor=Color.FromArgb(32,77,132) } };
        }
    }

    // A native hierarchical field editor, shared by tasks, platforms and coordinate lists.
    internal sealed class NativeFieldEditor : Form
    {
        private readonly TreeView tree;
        private readonly DataGridView grid;
        private readonly Label error;
        private object current;
        private bool loading;
        internal object Value { get; private set; }
        private sealed class Cell { internal object Key, Original; }
        internal NativeFieldEditor(object value, string title)
        {
            Value=NativeInputData.Copy(value); Text=title; Font=new Font("Microsoft YaHei UI",9f); BackColor=Color.White;
            Size=new Size(910,640); MinimumSize=new Size(730,480); StartPosition=FormStartPosition.CenterParent;
            var split=new SplitContainer { Dock=DockStyle.Fill, Size=new Size(880,510), SplitterDistance=250, FixedPanel=FixedPanel.Panel1, Panel1MinSize=180, Panel2MinSize=400 };
            tree=new TreeView { Name="NativeFieldTree", Dock=DockStyle.Fill, HideSelection=false, BorderStyle=BorderStyle.FixedSingle };
            grid=NativeInputData.Grid("NativeFieldGrid"); grid.SelectionMode=DataGridViewSelectionMode.CellSelect;
            grid.Columns.Add(new DataGridViewTextBoxColumn { Name="key",HeaderText="字段 / 条目",ReadOnly=true,FillWeight=65,MinimumWidth=160 });
            grid.Columns.Add(new DataGridViewTextBoxColumn { Name="value",HeaderText="值",FillWeight=75,MinimumWidth=150 });
            grid.Columns.Add(new DataGridViewTextBoxColumn { Name="type",HeaderText="类型",ReadOnly=true,FillWeight=20,MinimumWidth=45 });
            split.Panel1.Controls.Add(tree); split.Panel2.Controls.Add(grid);
            var bar=new FlowLayoutPanel { Dock=DockStyle.Bottom, Height=43, Padding=new Padding(6) };
            var append=MainWindow.StandardButton("复制列表条目",115); append.Name="NativeFieldDuplicate";
            var remove=MainWindow.StandardButton("删除列表条目",115); remove.Name="NativeFieldRemove";
            bar.Controls.AddRange(new Control[]{append,remove}); split.Panel2.Controls.Add(bar);
            error=new Label { Dock=DockStyle.Bottom, Height=45, Padding=new Padding(9), ForeColor=Color.Firebrick };
            var bottom=new FlowLayoutPanel { Dock=DockStyle.Bottom, Height=48, FlowDirection=FlowDirection.RightToLeft,Padding=new Padding(8),BackColor=Color.FromArgb(246,249,253) };
            var cancel=MainWindow.StandardButton("取消",80); cancel.DialogResult=DialogResult.Cancel;
            var save=MainWindow.StandardButton("保存条目",95); save.Name="NativeFieldSave";
            bottom.Controls.AddRange(new Control[]{cancel,save}); Controls.Add(split); Controls.Add(error); Controls.Add(bottom);
            Controls.Add(new Label { Dock=DockStyle.Top, Height=47, Padding=new Padding(12), ForeColor=Color.SlateGray,
                Text="在右侧直接修改数值与文字；双击对象或列表展开。坐标按原顺序保存。布尔值可从下拉框选择；空值可填数字、true / false 或 null。" });
            CancelButton=cancel; save.Click+=delegate { if(Commit()){DialogResult=DialogResult.OK;Close();} };
            tree.BeforeSelect+=delegate(object sender,TreeViewCancelEventArgs e){ if(!loading&&!Commit())e.Cancel=true; };
            tree.AfterSelect+=delegate { ShowFields(tree.SelectedNode.Tag); };
            grid.CellDoubleClick+=delegate(object sender,DataGridViewCellEventArgs e){
                if(e.RowIndex<0||!Commit())return; var cell=(Cell)grid.Rows[e.RowIndex].Tag;
                object child=Get(current,cell.Key); if(!(child is IList)&&!(child is Dictionary<string,object>))return;
                foreach(TreeNode node in tree.SelectedNode.Nodes)if(object.ReferenceEquals(node.Tag,child)){tree.SelectedNode=node;node.Expand();break;}
            };
            append.Click+=delegate { var list=current as IList;if(list==null){error.Text="请先在左侧选择一个列表，例如区域顶点。";return;}if(!Commit())return;
                if(list.Count==0){error.Text="空列表请通过 JSON 编辑页填写首项，再使用表格编辑。";return;}
                int index=grid.CurrentCell==null?list.Count-1:grid.CurrentCell.RowIndex;list.Add(NativeInputData.Copy(list[index]));RefreshCurrent(); };
            remove.Click+=delegate { var list=current as IList;if(list==null||grid.CurrentCell==null){error.Text="请先选择列表内的条目。";return;}if(!Commit())return;list.RemoveAt(grid.CurrentCell.RowIndex);RefreshCurrent(); };
            var root=new TreeNode("条目字段") { Tag=Value }; AddChildren(root,Value);tree.Nodes.Add(root);tree.SelectedNode=root;root.Expand();
        }
        private static object Get(object container,object key) { var map=container as Dictionary<string,object>;return map!=null?map[(string)key]:((IList)container)[(int)key]; }
        private static void Set(object container,object key,object value) { var map=container as Dictionary<string,object>;if(map!=null)map[(string)key]=value;else((IList)container)[(int)key]=value; }
        private void AddChildren(TreeNode node,object value)
        {
            var map=value as Dictionary<string,object>;var list=value as IList;
            IEnumerable<KeyValuePair<object,object>> items=map!=null?map.Select(p=>new KeyValuePair<object,object>(p.Key,p.Value)):
                list!=null?list.Cast<object>().Select((v,i)=>new KeyValuePair<object,object>(i,v)):Enumerable.Empty<KeyValuePair<object,object>>();
            foreach(var item in items)if(item.Value is IList||item.Value is Dictionary<string,object>){
                var child=new TreeNode(item.Key is int?"第 "+((int)item.Key+1)+" 项":NativeInputData.Label((string)item.Key)){Tag=item.Value};AddChildren(child,item.Value);node.Nodes.Add(child);
            }
        }
        private void ShowFields(object value)
        {
            loading=true;current=value;grid.Rows.Clear();error.Text="";
            var map=value as Dictionary<string,object>;var list=value as IList;
            IEnumerable<KeyValuePair<object,object>> items=map!=null?map.Select(p=>new KeyValuePair<object,object>(p.Key,p.Value)):
                list!=null?list.Cast<object>().Select((v,i)=>new KeyValuePair<object,object>(i,v)):Enumerable.Empty<KeyValuePair<object,object>>();
            foreach(var p in items){ bool nested=p.Value is IList||p.Value is Dictionary<string,object>;
                string kind=nested?"展开":p.Value==null?"空":p.Value is bool?"布尔":p.Value is string?"文字":"数字";
                int n=grid.Rows.Add(p.Key is int?"第 "+((int)p.Key+1)+" 项":NativeInputData.Label((string)p.Key),NativeInputData.Summary(p.Value),kind);
                grid.Rows[n].Tag=new Cell { Key=p.Key,Original=p.Value };grid.Rows[n].Cells[1].ReadOnly=nested;
                if(nested)grid.Rows[n].DefaultCellStyle.ForeColor=Color.FromArgb(36,104,182);
                string field=p.Key as string;string[] choices=p.Value is bool?new[]{"true","false"}:field=="status"?new[]{"READY","OFFLINE","BUSY","DAMAGED","LOST"}:null;
                if(choices!=null){var combo=new DataGridViewComboBoxCell { DisplayStyle=DataGridViewComboBoxDisplayStyle.DropDownButton };combo.Items.AddRange(choices);string selected=NativeInputData.Summary(p.Value);if(!combo.Items.Contains(selected))combo.Items.Add(selected);combo.Value=selected;grid.Rows[n].Cells[1]=combo;}
            } loading=false;
        }
        private void RefreshCurrent(){TreeNode node=tree.SelectedNode;node.Nodes.Clear();AddChildren(node,current);ShowFields(current);node.Expand();}
        private bool Commit()
        {
            if(loading||current==null)return true;grid.EndEdit();var updates=new List<KeyValuePair<object,object>>();
            try {foreach(DataGridViewRow row in grid.Rows){var cell=(Cell)row.Tag;if(cell.Original is IList||cell.Original is Dictionary<string,object>)continue;
                string text=Convert.ToString(row.Cells[1].Value);if(text==NativeInputData.Summary(cell.Original))continue;object parsed;
                if(cell.Original is string)parsed=text;else {
                    parsed=NativeInputData.Json.DeserializeObject(text);
                    if(parsed is IList||parsed is Dictionary<string,object>)throw new FormatException("此处需要标量。");
                    if(cell.Original is bool&&!(parsed is bool))throw new FormatException("布尔值需要 true 或 false。");
                    if(cell.Original!=null&&!(cell.Original is bool)&&(parsed==null||parsed is bool||parsed is string))throw new FormatException("需要有效数字。");
                    if(parsed is double && (double.IsNaN((double)parsed)||double.IsInfinity((double)parsed)))throw new FormatException("数字必须有限。");
                }updates.Add(new KeyValuePair<object,object>(cell.Key,parsed));
            }
            foreach(var p in updates)Set(current,p.Key,p.Value);
            foreach(DataGridViewRow row in grid.Rows){var cell=(Cell)row.Tag;cell.Original=Get(current,cell.Key);}error.Text="";return true;
            }catch(Exception ex){error.Text="未保存："+ex.Message;return false;}
        }
    }

    internal sealed class NativeInputEditor : Form
    {
        internal Dictionary<string,object> Draft {get;private set;}
        private readonly DesktopApi api;
        private readonly TabControl tabs;
        private readonly Label note;
        private readonly Button save;
        private readonly Stack<string> undo=new Stack<string>();
        private readonly List<DataGridView> grids=new List<DataGridView>();
        private bool modified;
        internal NativeInputEditor(DesktopApi api,Dictionary<string,object> draft,bool platforms)
        {
            this.api=api;Draft=(Dictionary<string,object>)NativeInputData.Copy(draft);
            Text="任务与平台 · 表格编辑";Font=new Font("Microsoft YaHei UI",9f);BackColor=Color.White;
            Size=new Size(930,640);MinimumSize=new Size(760,470);StartPosition=FormStartPosition.CenterParent;
            tabs=new TabControl {Dock=DockStyle.Fill,Name="NativeInputTabs"};AddPage(false);AddPage(true);
            note=new Label {Dock=DockStyle.Bottom,Height=49,Padding=new Padding(10),ForeColor=Color.SlateGray,
                Text="编辑的是本轮输入草稿。双击条目编辑字段；平台可标记为停用。应用后创建新的完整运行，原记录保留。"};
            var bottom=new FlowLayoutPanel {Dock=DockStyle.Bottom,Height=48,Padding=new Padding(8),FlowDirection=FlowDirection.RightToLeft,BackColor=Color.FromArgb(246,249,253)};
            var cancel=MainWindow.StandardButton("取消",80);cancel.DialogResult=DialogResult.Cancel;
            save=MainWindow.StandardButton("检查并应用",110);save.Name="NativeInputsSave";save.Click+=async delegate {await SaveAsync();};
            bottom.Controls.AddRange(new Control[]{cancel,save});Controls.Add(tabs);Controls.Add(note);Controls.Add(bottom);CancelButton=cancel;
            tabs.SelectedIndex=platforms?1:0;RefreshRows();
            FormClosing+=delegate(object sender,FormClosingEventArgs e){if(modified&&DialogResult!=DialogResult.OK&&MessageBox.Show(this,"放弃本次表格编辑的修改？","尚未应用",MessageBoxButtons.YesNo)!=DialogResult.Yes){e.Cancel=true;DialogResult=DialogResult.None;}};
        }
        private IList Rows(bool platforms)
        {
            var document=(Dictionary<string,object>)Draft[platforms?"formation":"message"];
            if(platforms&&document.ContainsKey("formation"))document=(Dictionary<string,object>)document["formation"];
            return (IList)document[platforms?"units":"tasks"];
        }
        private void Remember(){undo.Push(NativeInputData.Json.Serialize(Draft));modified=true;}
        private void AddPage(bool platforms)
        {
            var page=new TabPage(platforms?"平台列表":"任务列表"){BackColor=Color.White,Padding=new Padding(8)};
            var grid=NativeInputData.Grid(platforms?"NativeInputUnits":"NativeInputTasks");grid.ReadOnly=true;
            foreach(string name in new[]{"编号","类别",platforms?"状态":"优先级",platforms?"初始位置":"时间窗"})grid.Columns.Add(name,name);
            var bar=new FlowLayoutPanel{Dock=DockStyle.Top,Height=43};
            Action<string,string,Action> button=(text,name,action)=>{var b=MainWindow.StandardButton(text,105);b.Name=name;b.Click+=delegate{try{action();}catch(Exception ex){note.Text=ex.Message;note.ForeColor=Color.Firebrick;}};bar.Controls.Add(b);};
            button("编辑条目","NativeInputsEdit",()=>Edit(platforms,grid));
            button("复制为新条目","NativeInputsDuplicate",()=>Duplicate(platforms,grid));
            if(platforms)button("启用 / 停用","NativeInputsToggle",()=>{var selected=Selected(platforms,grid);Remember();selected["status"]=NativeInputData.Text(selected,"status")=="OFFLINE"?"READY":"OFFLINE";RefreshRows();});
            button("移除条目","NativeInputsRemove",()=>{if(grid.CurrentRow==null)return;Remember();Rows(platforms).RemoveAt(grid.CurrentRow.Index);RefreshRows();});
            button("撤销上次修改","NativeInputsUndo",()=>{if(undo.Count==0)return;Draft=(Dictionary<string,object>)NativeInputData.Copy(NativeInputData.Json.DeserializeObject(undo.Pop()));modified=undo.Count>0;RefreshRows();});
            grid.CellDoubleClick+=delegate(object sender,DataGridViewCellEventArgs e){if(e.RowIndex>=0)Edit(platforms,grid);};
            page.Controls.Add(grid);page.Controls.Add(bar);tabs.TabPages.Add(page);grids.Add(grid);
        }
        private Dictionary<string,object> Selected(bool platforms,DataGridView grid)
        {if(grid.CurrentRow==null)throw new InvalidOperationException("请先选择一条记录。");return (Dictionary<string,object>)Rows(platforms)[grid.CurrentRow.Index];}
        private void Edit(bool platforms,DataGridView grid)
        {
            var selected=Selected(platforms,grid);int index=grid.CurrentRow.Index;
            using(var editor=new NativeFieldEditor(selected,platforms?"编辑平台输入":"编辑任务输入"))if(editor.ShowDialog(this)==DialogResult.OK){Remember();Rows(platforms)[index]=editor.Value;RefreshRows();grids[platforms?1:0].CurrentCell=grids[platforms?1:0].Rows[index].Cells[0];}
        }
        private void Duplicate(bool platforms,DataGridView grid)
        {
            var copy=(Dictionary<string,object>)NativeInputData.Copy(Selected(platforms,grid));var rows=Rows(platforms);
            string idKey=platforms?"unit_id":"task_id",basis=NativeInputData.Text(copy,idKey)+"_copy",id=basis;int n=2;
            while(rows.Cast<Dictionary<string,object>>().Any(r=>NativeInputData.Text(r,idKey)==id))id=basis+n++;
            copy[idKey]=id;
            if(platforms){int robot=0;int old;int.TryParse(NativeInputData.Text(copy,"robot_id"),out old);string kind=NativeInputData.Text(copy,"platform_class");int low=kind=="UGV"?1:kind=="TANK"?21:kind=="PLANE"?31:kind=="WING"?41:old<=20?1:old<=30?21:old<=40?31:41;int high=low==1?20:low+9;
                var used=new HashSet<string>(rows.Cast<Dictionary<string,object>>().Select(r=>NativeInputData.Text(r,"robot_id")));
                for(int r=low;r<=high;r++)if(!used.Contains(r.ToString(CultureInfo.InvariantCulture))){robot=r;break;}
                if(robot==0)throw new InvalidOperationException("该类别的机器人编号已用满。可编辑现有平台或停用平台；不能创建重复编号。");copy["robot_id"]=robot;
            }
            using(var editor=new NativeFieldEditor(copy,platforms?"新增平台 · 复制输入":"新增任务 · 复制输入"))if(editor.ShowDialog(this)==DialogResult.OK){Remember();rows.Add(editor.Value);RefreshRows();grid.CurrentCell=grid.Rows[grid.Rows.Count-1].Cells[0];}
        }
        private void RefreshRows()
        {
            for(int i=0;i<grids.Count;i++){var grid=grids[i];int selected=grid.CurrentRow==null?0:grid.CurrentRow.Index;grid.Rows.Clear();
                foreach(Dictionary<string,object> row in Rows(i==1))grid.Rows.Add(NativeInputData.Text(row,i==1?"unit_id":"task_id"),NativeInputData.Text(row,i==1?"platform_class":"task_type"),NativeInputData.Text(row,i==1?"status":"priority"),NativeInputData.Json.Serialize(row.ContainsKey(i==1?"position":"window")?row[i==1?"position":"window"]:null));
                if(grid.Rows.Count>0)grid.CurrentCell=grid.Rows[Math.Min(selected,grid.Rows.Count-1)].Cells[0];tabs.TabPages[i].Text=(i==1?"平台列表":"任务列表")+" ("+grid.Rows.Count+")";
            }
        }
        private async Task SaveAsync()
        {
            try {save.Enabled=false;tabs.Enabled=false;note.ForeColor=Color.SlateGray;note.Text="正在检查任务、平台编号、依赖关系与输入契约…";
                await Task.Run(()=>api.ValidateDraft(Draft));if(IsDisposed)return;DialogResult=DialogResult.OK;Close();
            }catch(Exception ex){if(!IsDisposed){note.ForeColor=Color.Firebrick;note.Text="检查未通过，修改保留："+ex.Message;}}
            finally {if(!IsDisposed){save.Enabled=true;tabs.Enabled=true;}}
        }
    }
}
