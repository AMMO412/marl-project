using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private static string PlatformNumberKey(string id)
        {
            return Regex.Replace(id ?? "", @"\d+", delegate(Match m) { return m.Value.PadLeft(16, '0'); });
        }

        private static List<DesktopPlatform> ParticipatingPlatforms(DesktopRunView run)
        {
            // The backend marks every platform dispatched in this run, including replacements.
            // Current job alone would drop completed and returning participants.
            var assigned = new HashSet<string>(run.Tasks.SelectMany(t => t.Assigned));
            return run.Platforms.Where(p => p.Participates || assigned.Contains(p.Id) || !string.IsNullOrEmpty(p.Job))
                .OrderBy(p => PlatformNumberKey(p.Id), StringComparer.OrdinalIgnoreCase).ToList();
        }

        private static string PlatformStateText(DesktopPlatform platform)
        {
            if (!platform.Alive || platform.Status == "lost") return "失联";
            if (platform.Phase == "returned") return "已返回出发点";
            if (platform.Status == "failed" || platform.Status == "cancelled" || platform.Status == "timeout") return StatusText(platform.Status);
            if (platform.Phase == "return") return "返航中";
            if (!string.IsNullOrEmpty(platform.Phase)) return StatusText(platform.Phase);
            return StatusText(platform.Status);
        }

        private void RefreshNativePlatforms(DesktopRunView run)
        {
            if (platformGrid == null) return;
            string selected = platformGrid.CurrentRow == null ? "" : Convert.ToString(platformGrid.CurrentRow.Cells[0].Value);
            int first = platformGrid.FirstDisplayedScrollingRowIndex;
            var assigned = new HashSet<string>(run.Tasks.SelectMany(t => t.Assigned));
            var ordered = ParticipatingPlatforms(run);
            bool rebuild = platformGrid.Rows.Count != ordered.Count;
            if (!rebuild) for (int i = 0; i < ordered.Count; i++)
                if (Convert.ToString(platformGrid.Rows[i].Cells[0].Value) != ordered[i].Id) { rebuild = true; break; }
            platformGrid.SuspendLayout();
            try
            {
                if (rebuild) { platformGrid.Rows.Clear(); foreach (var p in ordered) platformGrid.Rows.Add(p.Id); }
                for (int i = 0; i < ordered.Count; i++)
                {
                    var p = ordered[i]; var row = platformGrid.Rows[i]; row.Tag = p.Id;
                    row.Cells[1].Value = p.Kind;
                    row.Cells[2].Value = string.IsNullOrEmpty(p.Job) ? "—" : p.Job;
                    row.Cells[3].Value = PlatformStateText(p);
                    row.Cells[4].Value = p.Battery.HasValue ? p.Battery.Value.ToString("0.0") : "—";
                    row.Cells[5].Value = p.Z.ToString("0.00");
                    row.Cells[6].Value = p.Participates || assigned.Contains(p.Id) || !string.IsNullOrEmpty(p.Job) ? "已分配任务" : "未分配";
                }
                if (nativePlatformSearch != null && (rebuild || nativePlatformSearch.Text.Length > 0)) FilterNativeGrid(platformGrid, nativePlatformSearch.Text);
                if (rebuild || (nativePlatformSearch != null && nativePlatformSearch.Text.Length > 0))
                {
                    foreach (DataGridViewRow row in platformGrid.Rows)
                        if (row.Visible && Convert.ToString(row.Cells[0].Value) == selected) { platformGrid.CurrentCell = row.Cells[0]; break; }
                    if (first >= 0 && first < platformGrid.Rows.Count && platformGrid.Rows[first].Visible)
                        platformGrid.FirstDisplayedScrollingRowIndex = first;
                }
            }
            finally { platformGrid.ResumeLayout(); }
        }
    }
}
