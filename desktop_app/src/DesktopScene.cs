using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private bool sceneFramePending;
        private DateTime lastSceneFrame = DateTime.MinValue;
        private Dictionary<string, object> sceneTaskProgress = new Dictionary<string, object>();

        private double SceneTaskPercent(string taskId, double fallback)
        {
            object raw; double percent;
            if (sceneTaskProgress.TryGetValue(taskId, out raw) && double.TryParse(Convert.ToString(raw, CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out percent))
                return Math.Max(0, Math.Min(100, percent));
            return fallback;
        }

        // Only the renderer lives in the scene tab. All commands and panels stay native.
        private void SyncSceneClock(Dictionary<string, object> frame)
        {
            if (desktopRun == null || frame == null) return;
            string runId = frame.ContainsKey("runId") ? Convert.ToString(frame["runId"]) : "";
            if (runId != desktopRunId) return; // Ignore late messages from the previous run.
            if (frame.ContainsKey("taskProgress"))
                sceneTaskProgress = frame["taskProgress"] as Dictionary<string, object> ?? new Dictionary<string, object>();
            double time, duration;
            if (!double.TryParse(Convert.ToString(frame.ContainsKey("time") ? frame["time"] : 0, CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out time)) return;
            if (!double.TryParse(Convert.ToString(frame.ContainsKey("duration") ? frame["duration"] : 0, CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out duration) || duration <= 0) return;
            Time = Math.Max(0, Math.Min(duration, time)); PlaybackEnd = duration;
            UpdateAircraftAltitude();
            webPlaying = frame.ContainsKey("playing") && Convert.ToBoolean(frame["playing"]);
            refreshing = true;
            timeline.Maximum = Math.Max(1, (int)Math.Ceiling(duration * 10));
            timeline.Value = Math.Min(timeline.Maximum, (int)Math.Round(Time * 10));
            refreshing = false;
            clock.Text = Time.ToString("0.0") + " / " + duration.ToString("0.0") + " s";
            timeStatus.Text = "回放 " + clock.Text;
            play.Text = webPlaying ? "Ⅱ 暂停" : "▶ 播放";
            if (string.IsNullOrEmpty(nativeSelectedPlatformId) && !string.IsNullOrEmpty(desktopTaskId))
            {
                TaskProperties selected = properties.SelectedObject as TaskProperties;
                if (selected != null && selected.Id == desktopTaskId)
                {
                    double percent = SceneTaskPercent(desktopTaskId, taskProgress.Value);
                    taskProgress.Value = (int)Math.Round(percent); selected.Progress = percent.ToString("0") + "%"; properties.Refresh();
                }
            }
            if (sceneFramePending || (DateTime.UtcNow - lastSceneFrame).TotalMilliseconds < 800 || Math.Abs(desktopRun.At - time) < .001) return;
            sceneFramePending = true; lastSceneFrame = DateTime.UtcNow;
            string expectedRun = desktopRunId;
            Task.Run(delegate
            {
                try
                {
                    DesktopRunView run = desktopApi.GetRun(expectedRun, time);
                    Ui(delegate
                    {
                        if (desktopRunId != expectedRun || Math.Abs(Time - run.At) > Math.Max(3, PlaybackSpeed * 2)) return;
                        desktopRun = run;
                        for (int i = 0; i < run.Tasks.Count && i < taskGrid.Rows.Count; i++)
                            taskGrid.Rows[i].Cells[3].Value = StatusText(string.IsNullOrEmpty(run.Tasks[i].StatusAt) ? run.Tasks[i].Status : run.Tasks[i].StatusAt);
                        RefreshNativePlatforms(run);
                        if (!string.IsNullOrEmpty(nativeSelectedPlatformId)) SelectNativePlatform(nativeSelectedPlatformId, false);
                        else if (!string.IsNullOrEmpty(desktopTaskId)) SelectDesktopTask(desktopTaskId, false);
                        RefreshNativeEvents();
                    });
                }
                catch (Exception ex) { LogDesktop("同步场景属性失败：" + ex.Message); }
                finally { Ui(delegate { sceneFramePending = false; }); }
            });
        }

        private void SetSceneLayer(int index, bool visible)
        {
            if (index < 0 || index >= sceneLayerVisibility.Length) return;
            if (index == 0) visible = true;
            sceneLayerVisibility[index] = visible;
            SyncSceneLayerMenu(index, visible);
            string[] names = { "buildings", "boundary", "units", "planned", "targets", "grid", "threats", "trails" };
            if (index >= 0 && index < names.Length && webReady)
                Bridge("setLayer(" + desktopJson.Serialize(names[index]) + "," + (visible ? "true" : "false") + ")");
        }
    }
}
