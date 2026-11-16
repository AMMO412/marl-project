using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    internal static class MapRandomVerification
    {
        public static int Run(string directory)
        {
            try
            {
                Directory.CreateDirectory(directory);
                using (var backend = new BackendSupervisor(Program.DesktopTrace))
                {
                    var api = new DesktopApi(backend.EnsureStartedAsync().GetAwaiter().GetResult());
                    var catalog = api.GetCatalog();
                    var source = api.GetConfiguration("interop_recon", null);
                    int result = 0;
                    using (var dialog = new NativeRunConfiguration(api, catalog, source))
                    {
                        dialog.ShowInTaskbar = false;
                        dialog.StartPosition = FormStartPosition.Manual;
                        dialog.Location = new Point(-16000, -16000);
                        dialog.Shown += async delegate
                        {
                            try { await Verify(dialog, api, catalog, directory); }
                            catch (Exception ex)
                            {
                                result = 1;
                                WriteError(directory, ex);
                            }
                            finally { dialog.DialogResult = DialogResult.OK; dialog.Close(); }
                        };
                        Application.Run(dialog);
                    }
                    return result;
                }
            }
            catch (Exception ex)
            {
                WriteError(directory, ex);
                return 1;
            }
        }

        private static void WriteError(string directory, Exception error)
        {
            Program.DesktopTrace("map random verification failed: " + error);
            try { File.WriteAllText(Path.Combine(directory, "map-random-error.txt"), error.ToString()); }
            catch (Exception writeError) { Program.DesktopTrace("map random verification error output failed: " + writeError.Message); }
        }

        private static async Task Verify(NativeRunConfiguration dialog,
            DesktopApi desktopApi, DesktopCatalog desktopCatalog, string directory)
        {
            await Task.Delay(200);
            if (desktopCatalog.Maps.Count != 3)
                throw new InvalidOperationException("原生目录未返回三张可选地图");

                ComboBox map = (ComboBox)dialog.Controls.Find(
                    "NativeMapChoice", true).Single();
                NumericUpDown seed = (NumericUpDown)dialog.Controls.Find(
                    "NativeTaskSeed", true).Single();
                CheckBox randomize = (CheckBox)dialog.Controls.Find(
                    "NativeRandomizeTasks", true).Single();
                if (map.Items.Count != desktopCatalog.Maps.Count)
                    throw new InvalidOperationException("地图下拉框与地图目录数量不一致");
                int mixed = desktopCatalog.Maps.FindIndex(
                    item => item.Id == "mixed");
                if (mixed < 0)
                    throw new InvalidOperationException("地图目录缺少公园与斜街混合片区");
                map.SelectedIndex = mixed;
                seed.Value = 24681357;
                randomize.Checked = true;
                Program.DesktopTrace("map random verification controls set");

                Dictionary<string, object> draftPayload = dialog.ReadDraft();
                Dictionary<string, object> checkedInput = await Task.Run(
                    delegate { return desktopApi.ValidateDraft(draftPayload); });
                Program.DesktopTrace("map random verification input validated");
                Dictionary<string, object> draft =
                    (Dictionary<string, object>)checkedInput["draft"];
                Dictionary<string, object> request =
                    (Dictionary<string, object>)draft["request"];
                Dictionary<string, object> message =
                    (Dictionary<string, object>)draft["message"];
                Dictionary<string, object> meta =
                    (Dictionary<string, object>)message["_meta"];
                Dictionary<string, object> placement =
                    (Dictionary<string, object>)meta["task_placement"];
                if (Convert.ToString(request["map_id"]) != "mixed")
                    throw new InvalidOperationException("地图选择没有写入运行请求");
                if (Convert.ToInt32(request["task_seed"]) != 24681357)
                    throw new InvalidOperationException("随机种子没有写入运行请求");
                if (Convert.ToString(placement["map_id"]) != "mixed")
                    throw new InvalidOperationException("任务点没有使用所选地图");

                // Capture the visible parameter page only: hidden JSON pages can
                // contain hundreds of map constraints and stall DrawToBitmap.
                var tabs = (TabControl)dialog.Controls.Find("NativeConfigurationTabs", true).Single();
                var page = tabs.SelectedTab;
                using (Bitmap bitmap = new Bitmap(page.Width, page.Height))
                {
                    Program.DesktopTrace("map random verification drawing page");
                    page.DrawToBitmap(bitmap, new Rectangle(Point.Empty, page.Size));
                    Program.DesktopTrace("map random verification saving page");
                    bitmap.Save(Path.Combine(directory, "map-random-configuration.png"));
                }
                File.WriteAllText(
                    Path.Combine(directory, "map-random-verification.json"),
                    new System.Web.Script.Serialization.JavaScriptSerializer().Serialize(new
                    {
                        maps = desktopCatalog.Maps.Select(item => item.Id).ToArray(),
                        selectedMap = "mixed",
                        taskSeed = 24681357,
                        randomizeTasks = true,
                        taskPlacementUsesSelectedMap = true,
                        nativeConfigurationCapture = true,
                        sourceScenario = "interop_recon"
                    }));
                Program.DesktopTrace("map random verification complete");
        }
    }
}
