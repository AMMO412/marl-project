using System;
using System.Collections;
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
        public async Task VerifyStructuredEditors(string directory)
        {
            Program.DesktopTrace("structured verification enter " + directory);
            Directory.CreateDirectory(directory);
            string progressPath = Path.Combine(directory,
                                                "structured-editor-progress.log");
            Program.DesktopTrace("structured verification writing progress " + progressPath);
            File.WriteAllText(progressPath, "start\r\n", new System.Text.UTF8Encoding(false));
            Program.DesktopTrace("structured verification progress written");
            DateTime deadline = DateTime.UtcNow.AddSeconds(75);
            while (desktopApi == null || desktopCatalog == null)
            {
                if (DateTime.UtcNow > deadline)
                    throw new Exception("专用表单验证等待后端超时。");
                await Task.Delay(200);
            }

            var results = new Dictionary<string, object>();
            string[] scenarios = {
                "interop_recon", "interop_containment", "interop_patrol",
                "interop_hold", "interop_asl"
            };
            foreach (string scenario in scenarios)
            {
                File.AppendAllText(progressPath, "load " + scenario + "\r\n");
                Dictionary<string, object> config =
                    await Task.Run(delegate {
                        return desktopApi.GetConfiguration(scenario, null);
                    });
                Dictionary<string, object> draft =
                    (Dictionary<string, object>)config["draft"];
                using (NativeStructuredEditor editor =
                       new NativeStructuredEditor(desktopApi, draft, 0))
                {
                    File.AppendAllText(progressPath, "open " + scenario + "\r\n");
                    editor.ShowInTaskbar = false;
                    editor.StartPosition = FormStartPosition.Manual;
                    editor.Location = new Point(-15000, -15000);
                    editor.Show();
                    Application.DoEvents();
                    DataGridView tasks = (DataGridView)editor.Controls.Find(
                        "NativeStructuredTasks", true)[0];
                    DataGridView parameters =
                        (DataGridView)editor.Controls.Find(
                            "NativeStructuredParameters", true)[0];
                    DataGridView targets = (DataGridView)editor.Controls.Find(
                        "NativeStructuredTargets", true)[0];
                    if (tasks.Rows.Count < 1 || parameters.Rows.Count < 4)
                        throw new Exception("专用表单未加载任务参数：" + scenario);
                    using (Bitmap bitmap = new Bitmap(
                               editor.Width, editor.Height))
                    {
                        editor.DrawToBitmap(bitmap,
                            new Rectangle(0, 0, editor.Width, editor.Height));
                        bitmap.Save(Path.Combine(
                            directory, "task-form-" + scenario + ".png"));
                    }
                    results[scenario] = new {
                        tasks = tasks.Rows.Count,
                        parameters = parameters.Rows.Count,
                        targets = targets.Rows.Count
                    };
                    editor.DialogResult = DialogResult.Cancel;
                    editor.Close();
                }
                File.AppendAllText(progressPath, "done " + scenario + "\r\n");
            }

            File.AppendAllText(progressPath, "edit recon\r\n");
            Dictionary<string, object> reconConfig =
                await Task.Run(delegate {
                    return desktopApi.GetConfiguration("interop_recon", null);
                });
            using (NativeStructuredEditor editor = new NativeStructuredEditor(
                       desktopApi, (Dictionary<string, object>)reconConfig["draft"], 0))
            {
                editor.ShowInTaskbar = false;
                editor.StartPosition = FormStartPosition.Manual;
                editor.Location = new Point(-15000, -15000);
                editor.Show();
                Application.DoEvents();
                TabControl tabs = (TabControl)editor.Controls.Find(
                    "NativeStructuredTabs", true)[0];
                DataGridView parameters =
                    (DataGridView)editor.Controls.Find(
                        "NativeStructuredParameters", true)[0];
                DataGridViewRow duration = parameters.Rows.Cast<DataGridViewRow>()
                    .First(delegate(DataGridViewRow row) {
                        return Convert.ToString(row.Cells[0].Value)
                            .Contains("(duration_s)");
                    });
                parameters.CurrentCell = duration.Cells[0];
                using (Timer timer = new Timer { Interval = 80 })
                {
                    timer.Tick += delegate {
                        NativeEditorValueDialog dialog =
                            Application.OpenForms.Cast<Form>()
                            .OfType<NativeEditorValueDialog>().FirstOrDefault();
                        if (dialog == null) return;
                        timer.Stop();
                        TextBox input = Descendants(dialog)
                            .OfType<TextBox>().First();
                        input.Text = "155";
                        ((Button)dialog.Controls.Find(
                            "NativeEditorValueSave", true)[0]).PerformClick();
                    };
                    timer.Start();
                    ((Button)editor.Controls.Find(
                        "NativeStructuredParameterEdit", true)[0]).PerformClick();
                }
                tabs.SelectedIndex = 1;
                Application.DoEvents();
                DataGridView targets =
                    (DataGridView)editor.Controls.Find(
                        "NativeStructuredTargets", true)[0];
                if (targets.Rows.Count < 1)
                    throw new Exception("侦察红方目标未显示。");
                targets.CurrentCell = targets.Rows[0].Cells[0];
                using (Timer timer = new Timer { Interval = 80 })
                {
                    timer.Tick += delegate {
                        NativeTargetDialog dialog =
                            Application.OpenForms.Cast<Form>()
                            .OfType<NativeTargetDialog>().FirstOrDefault();
                        if (dialog == null) return;
                        timer.Stop();
                        TextBox input = Descendants(dialog)
                            .OfType<TextBox>().First();
                        input.Text = "UI-TARGET-1";
                        ((Button)dialog.Controls.Find(
                            "NativeTargetDialogSave", true)[0]).PerformClick();
                    };
                    timer.Start();
                    ((Button)editor.Controls.Find(
                        "NativeStructuredTargetEdit", true)[0]).PerformClick();
                }
                using (Bitmap bitmap = new Bitmap(
                           editor.Width, editor.Height))
                {
                    editor.DrawToBitmap(bitmap,
                        new Rectangle(0, 0, editor.Width, editor.Height));
                    bitmap.Save(Path.Combine(
                        directory, "red-targets-recon.png"));
                }
                ((Button)editor.Controls.Find(
                    "NativeStructuredSave", true)[0]).PerformClick();
                deadline = DateTime.UtcNow.AddSeconds(35);
                while (editor.DialogResult != DialogResult.OK
                       && DateTime.UtcNow < deadline)
                    await Task.Delay(100);
                if (editor.DialogResult != DialogResult.OK)
                    throw new Exception("专用表单保存未完成。");
                Dictionary<string, object> message =
                    (Dictionary<string, object>)editor.Draft["message"];
                Dictionary<string, object> task =
                    (Dictionary<string, object>)((IList)message["tasks"])[0];
                Dictionary<string, object> parametersValue =
                    (Dictionary<string, object>)task["params"];
                Dictionary<string, object> tracking =
                    (Dictionary<string, object>)parametersValue["tracking_target"];
                if (Convert.ToDouble(parametersValue["duration_s"]) != 155
                    || Convert.ToString(tracking["target_id"]) != "UI-TARGET-1")
                    throw new Exception("专用表单编辑或红方目标写回失败。");
                results["editedRecon"] = new {
                    duration = 155,
                    targetId = "UI-TARGET-1",
                    backendValidation = true
                };
            }
            File.AppendAllText(progressPath, "finish\r\n");
            File.WriteAllText(Path.Combine(
                directory, "structured-editor-verification.json"),
                desktopJson.Serialize(results));
        }

        private static IEnumerable<Control> Descendants(Control parent)
        {
            foreach (Control child in parent.Controls)
            {
                yield return child;
                foreach (Control nested in Descendants(child))
                    yield return nested;
            }
        }
    }
}
