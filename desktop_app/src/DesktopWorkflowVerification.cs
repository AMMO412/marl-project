using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private void VerifyNativeWorkflow(string directory)
        {
            Dictionary<string, object> evidence = new Dictionary<string, object>();
            if(string.Join(",",Documents.TabPages.Cast<TabPage>().Select(p=>p.Text))!="场景视图,平台列表,运行记录")throw new InvalidOperationException("页签未精简或顺序不正确");
            var tools=MainMenuStrip.Items.OfType<ToolStripMenuItem>().First(p=>p.Text.StartsWith("工具"));
            tools.DropDownItems.OfType<ToolStripMenuItem>().First(p=>p.Text=="运行记录").PerformClick();
            if(Documents.SelectedTab.Text!="运行记录")throw new InvalidOperationException("运行记录导航错位");
            Documents.SelectedIndex=1;
            if(Documents.SelectedTab.Text!="平台列表")throw new InvalidOperationException("平台导航错位");
            OpenTaskView(); evidence["threeTabsAndHistoryNavigation"]=true;
            Dictionary<string, object> scene = desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState()")) as Dictionary<string, object>;
            if (scene == null || Convert.ToString(scene["runId"]) != desktopRunId || Math.Abs(Convert.ToDouble(scene["duration"]) - desktopRun.End) > .1)
                throw new InvalidOperationException("场景轮次或全程时长与原生面板不一致");
            evidence["runIdentityAndFullDuration"] = true;
            Dictionary<string, object> config = desktopApi.GetConfiguration(SelectedScenario, desktopRunId);
            using (NativeRunConfiguration editor = new NativeRunConfiguration(desktopApi, desktopCatalog, config))
            {
                editor.ShowInTaskbar = false; editor.StartPosition = FormStartPosition.Manual; editor.Location = new Point(-16000, -16000); editor.Show(); Application.DoEvents();
                Dictionary<string, object> roundTrip = editor.ReadDraft();
                if (!Convert.ToBoolean(desktopApi.ValidateDraft(roundTrip)["valid"])) throw new InvalidOperationException("原生配置未通过后端契约校验");
                File.WriteAllText(Path.Combine(directory, "checked-desktop-draft.json"), DesktopApi.Pretty(roundTrip), new UTF8Encoding(false));
                object imported = desktopApi.ParseNativeJson(File.ReadAllText(Path.Combine(directory, "checked-desktop-draft.json"), Encoding.UTF8));
                if (!Convert.ToBoolean(desktopApi.ValidateDraft(imported)["valid"])) throw new InvalidOperationException("配置导出/导入不一致");
                evidence["nativeConfigurationRoundTrip"] = true;
                TextBox message = editor.Controls.Find("NativeMessageEditor", true)[0] as TextBox;
                string original = message.Text; message.Text = "{broken"; bool rejected = false;
                try { editor.ReadDraft(); } catch (ArgumentException) { rejected = true; }
                if (!rejected || message.Text != "{broken") throw new InvalidOperationException("无效 JSON 没有被拒绝或编辑内容丢失");
                message.Text = original; evidence["invalidJsonRetainsEditor"] = true;
                using (Bitmap bitmap = new Bitmap(editor.Width, editor.Height)) { editor.DrawToBitmap(bitmap, new Rectangle(0, 0, editor.Width, editor.Height)); bitmap.Save(Path.Combine(directory, "native-configuration.png"), ImageFormat.Png); }
                editor.DialogResult = DialogResult.OK; editor.Close();
            }
            nativeTaskSearch.Text = "__no_match__";
            if (taskGrid.Rows.Cast<DataGridViewRow>().Any(delegate(DataGridViewRow row) { return row.Visible; })) throw new InvalidOperationException("任务筛选无效");
            nativeTaskSearch.Clear(); evidence["taskFilter"] = true;
            nativePlatformSearch.Text = "__no_match__";
            if (platformGrid.Rows.Cast<DataGridViewRow>().Any(delegate(DataGridViewRow row) { return row.Visible; })) throw new InvalidOperationException("平台筛选无效");
            nativePlatformSearch.Clear(); evidence["platformFilter"] = true;
            nativeHistorySearch.Text = "__no_match__";
            if (history.Items.Count != 0) throw new InvalidOperationException("运行筛选无效");
            nativeHistorySearch.Clear(); evidence["runFilter"] = history.Items.Count > 0;
            nativeCurrentEvents.Checked = false; nativeEventSearch.Clear();
            if (nativeEvents.Rows.Count == 0) throw new InvalidOperationException("真实消息列表为空");
            nativeEventSearch.Text = "__no_match__"; if (nativeEvents.Rows.Count != 0) throw new InvalidOperationException("消息筛选无效");
            nativeEventSearch.Clear(); DesktopEvent first = nativeEvents.Rows[0].Tag as DesktopEvent;
            typeof(DataGridView).GetMethod("OnCellDoubleClick", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(nativeEvents, new object[] { new DataGridViewCellEventArgs(0, 0) });
            double at = Convert.ToDouble(desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.getState().time")));
            if (first == null || Math.Abs(at - first.Time) > .1) throw new InvalidOperationException("消息双击未定位到回放时刻");
            evidence["realEventSearchAndSeek"] = true;
            DesktopPlatform platform = desktopRun.Platforms[0]; SelectNativePlatform(platform.Id, true);
            if (!(properties.SelectedObject is NativePlatformProperties)) throw new InvalidOperationException("平台属性未显示");
            if (!Convert.ToBoolean(desktopJson.DeserializeObject(ReadMapScript("MarlDesktop.focusPlatform(" + desktopJson.Serialize(platform.Id) + ")")))) throw new InvalidOperationException("平台地图定位无效");
            evidence["platformPropertiesAndLocate"] = true;
            if (nativeFiles.Items.Count == 0) throw new InvalidOperationException("真实输出文件列表为空");
            byte[] artifact = desktopApi.DownloadArtifact(desktopRunId, "report.json");
            File.WriteAllBytes(Path.Combine(directory, "checked-report.json"), artifact);
            if (!(desktopApi.ParseNativeJson(Encoding.UTF8.GetString(artifact)) is Dictionary<string, object>)) throw new InvalidOperationException("报告下载/预览不是有效 JSON");
            Dictionary<string, object> details = desktopApi.GetDetails(desktopRunId);
            if (Convert.ToString(details["id"]) != desktopRunId) throw new InvalidOperationException("报告轮次不一致");
            evidence["realFileExportAndReport"] = true;
            ShowNativeDocument("运行报告", new Dictionary<string, object> { { "运行摘要", new Dictionary<string, object> { { "运行编号", desktopRunId }, { "证据来源", "本地运行；未验证外部平台" }, { "仿真时长 / s", desktopRun.End }, { "任务总数", desktopRun.Total } } }, { "完整报告", details["report"] }, { "输入与来源", details["manifest"] } }, Path.Combine(directory, "native-report.png"));
            object comparison = desktopApi.CompareScenario(SelectedScenario);
            ShowNativeComparisonTable((Dictionary<string, object>)comparison, Path.Combine(directory, "native-comparison.png"));
            evidence["nativeReportAndComparisonWindows"] = true;

            System.Threading.Tasks.Task screenshot = SaveNativeScreenshot(Path.Combine(directory, "native-exported-window.png"));
            DateTime deadline = DateTime.UtcNow.AddSeconds(6);
            while (!screenshot.IsCompleted && DateTime.UtcNow < deadline) { Application.DoEvents(); System.Threading.Thread.Sleep(15); }
            if (!screenshot.IsCompleted) throw new InvalidOperationException("原生窗口截图导出超时");
            screenshot.GetAwaiter().GetResult(); evidence["windowScreenshotExport"] = true;
            evidence["customInputSnapshotPresent"] = desktopRun.Files.Contains("input_message.json");
            evidence["run"] = desktopRunId;
            File.WriteAllText(Path.Combine(directory, "native-workflow-verification.json"), desktopJson.Serialize(evidence));
            nativeSelectedPlatformId = ""; nativeCurrentEvents.Checked = true;
            if (desktopRun.Tasks.Count > 0) SelectDesktopTask(desktopRun.Tasks[0].Id);
            ReadMapScript("MarlDesktop.pause();MarlDesktop.setTime(Math.min(80,MarlDesktop.getState().duration));MarlDesktop.fit('area')");
        }
    }
}
