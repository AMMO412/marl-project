using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private async Task InspectConfigurationDialog(Action open, Dictionary<string, object> expected, string path, bool applyChange)
        {
            var completed = new TaskCompletionSource<bool>();
            DateTime deadline = DateTime.UtcNow.AddSeconds(30);
            using (var timer = new Timer { Interval = 100 })
            {
                timer.Tick += delegate {
                    var dialog = Application.OpenForms.Cast<Form>().OfType<NativeRunConfiguration>().FirstOrDefault();
                    if (dialog == null) { if (DateTime.UtcNow > deadline) { timer.Stop(); completed.TrySetException(new Exception("Configuration dialog did not open")); } return; }
                    timer.Stop();
                    try {
                        if (desktopJson.Serialize(dialog.ReadDraft()) != desktopJson.Serialize(expected["draft"])) throw new Exception("Displayed parameters differ from saved snapshot");
                        var source = (Label)dialog.Controls.Find("NativeConfigurationSource", true)[0];
                        string runId = Convert.ToString(expected["run_id"]);
                        if (runId.Length > 0 && !source.Text.Contains(runId)) throw new Exception("Source run is not visible");
                        using (var bitmap = new Bitmap(dialog.Width, dialog.Height)) { dialog.DrawToBitmap(bitmap, new Rectangle(Point.Empty, dialog.Size)); bitmap.Save(path); }
                        if (applyChange) {
                            var ticks = dialog.Controls.OfType<Control>().SelectMany(FlattenConfigurationControls).OfType<NumericUpDown>().Single(n => n.Name == "NativeMaxTicks");
                            ticks.Value = 121;
                            var apply = dialog.Controls.OfType<Control>().SelectMany(FlattenConfigurationControls).OfType<Button>().Single(b => b.Text == "应用配置");
                            dialog.FormClosed += delegate { completed.TrySetResult(true); };
                            apply.PerformClick();
                        } else { dialog.DialogResult = DialogResult.Cancel; dialog.Close(); completed.TrySetResult(true); }
                    } catch (Exception ex) { dialog.DialogResult = DialogResult.OK; dialog.Close(); completed.TrySetException(ex); }
                };
                timer.Start(); open(); await completed.Task;
            }
            while (nativeConfigurationLoading) await Task.Delay(25);
        }
        private static IEnumerable<Control> FlattenConfigurationControls(Control control)
        {
            yield return control;
            foreach (Control child in control.Controls) foreach (Control nested in FlattenConfigurationControls(child)) yield return nested;
        }
        public async Task VerifySceneConfiguration(string directory)
        {
            Directory.CreateDirectory(directory);
            DateTime deadline = DateTime.UtcNow.AddSeconds(75);
            while (desktopApi == null || desktopCatalog == null) { if (DateTime.UtcNow > deadline) throw new Exception("Configuration backend not ready"); await Task.Delay(200); }
            SetPlaying(false);
            Dictionary<string, object> saved = null, template = null;
            DesktopRunSummary selected = null;
            foreach (var row in desktopCatalog.Runs.Take(30)) {
                var snapshot = await Task.Run(() => desktopApi.GetConfiguration(row.Scenario, row.Id));
                var defaults = await Task.Run(() => desktopApi.GetConfiguration(row.Scenario, null));
                if (Convert.ToString(snapshot["input_source"]) == "run_snapshot" && desktopJson.Serialize(snapshot["draft"]) != desktopJson.Serialize(defaults["draft"])) { saved = snapshot; template = defaults; selected = row; break; }
            }
            if (selected == null) throw new Exception("Need a saved run with parameters distinct from template");
            desktopRun = await Task.Run(() => desktopApi.GetRun(selected.Id, 0)); desktopRunId = desktopRun.Id;
            // Deliberately leave the new-scene selector and a stale draft pointing elsewhere.
            scenarioBox.SelectedItem = desktopCatalog.Scenarios.Keys.First(k => k != selected.Scenario);
            nativeDraft = (Dictionary<string, object>)template["draft"]; nativeDraftSourceRunId = "another_run";
            var actual = await ReadNativeConfiguration(NativeConfigurationMode.CurrentScene);
            if (desktopJson.Serialize(actual["draft"]) != desktopJson.Serialize(saved["draft"])) throw new Exception("Current scene used template, selector, or unrelated draft");
            var toolbar = Controls.OfType<Control>().SelectMany(FlattenConfigurationControls).OfType<ToolStrip>().Where(t => !(t is MenuStrip)).First(t => t.Items.Cast<ToolStripItem>().Any(i => i.Text == "场景参数"));
            await InspectConfigurationDialog(() => toolbar.Items.Cast<ToolStripItem>().Single(i => i.Text == "场景参数").PerformClick(), actual, Path.Combine(directory, "current-scene-parameters.png"), true);
            if (nativeDraftSourceRunId != selected.Id || Convert.ToInt32(((Dictionary<string, object>)nativeDraft["request"])["max_ticks"]) != 121) throw new Exception("Applied draft lost its source");
            var pending = await ReadNativeConfiguration(NativeConfigurationMode.CurrentScene);
            if (Convert.ToString(pending["input_source"]) != "desktop_draft" || Convert.ToInt32(((Dictionary<string, object>)((Dictionary<string, object>)pending["draft"])["request"])["max_ticks"]) != 121) throw new Exception("Reopening lost applied edits");
            var editMenu = MainMenuStrip.Items.Cast<ToolStripMenuItem>().Single(i => i.Text.StartsWith("编辑"));
            await InspectConfigurationDialog(() => editMenu.DropDownItems.Cast<ToolStripItem>().Single(i => i.Text == "场景参数…").PerformClick(), pending, Path.Combine(directory, "pending-scene-parameters.png"), false);
            // A same-scenario history switch must not inherit edits from the previous run.
            var other = desktopCatalog.Runs.First(r => r.Scenario == selected.Scenario && r.Id != selected.Id);
            desktopRun = await Task.Run(() => desktopApi.GetRun(other.Id, 0)); desktopRunId = other.Id;
            var switched = await ReadNativeConfiguration(NativeConfigurationMode.CurrentScene);
            var otherSaved = await Task.Run(() => desktopApi.GetConfiguration(other.Scenario, other.Id));
            if (desktopJson.Serialize(switched["draft"]) != desktopJson.Serialize(otherSaved["draft"])) throw new Exception("Same-scenario history switch reused stale draft");
            var copied = await ReadNativeConfiguration(NativeConfigurationMode.CopyRun, selected.Id);
            if (desktopJson.Serialize(copied["draft"]) != desktopJson.Serialize(saved["draft"])) throw new Exception("Copy did not use selected run");
            var newConfig = await ReadNativeConfiguration(NativeConfigurationMode.NewScene);
            var newTemplate = await Task.Run(() => desktopApi.GetConfiguration(SelectedScenario, null));
            if (desktopJson.Serialize(newConfig["draft"]) != desktopJson.Serialize(newTemplate["draft"]) || newConfig["run_id"] != null) throw new Exception("New scene did not use fresh template");
            var fileMenu = MainMenuStrip.Items.Cast<ToolStripMenuItem>().Single(i => i.Text.StartsWith("文件"));
            await InspectConfigurationDialog(() => fileMenu.DropDownItems.Cast<ToolStripItem>().Single(i => i.Text == "新建场景…").PerformClick(), newConfig, Path.Combine(directory, "new-scene-template.png"), false);
            var unchanged = await Task.Run(() => desktopApi.GetConfiguration(selected.Scenario, selected.Id));
            if (desktopJson.Serialize(unchanged["draft"]) != desktopJson.Serialize(saved["draft"])) throw new Exception("Editing changed original run");
            File.WriteAllText(Path.Combine(directory, "configuration-source-verification.json"), desktopJson.Serialize(new {
                sourceRun = selected.Id, sourceScenario = selected.Scenario, distinctFromTemplate = true,
                toolbarSnapshot = true, selectorMismatchHandled = true, staleDraftIgnored = true,
                appliedEditsRetained = true, menuReopensDraft = true, sameScenarioSwitch = true,
                copyUsesSelectedSnapshot = true, newSceneUsesTemplate = true, originalRunUnchanged = true
            }));
        }
    }
}
