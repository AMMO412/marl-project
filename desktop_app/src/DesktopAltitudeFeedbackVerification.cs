using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private async Task AwaitAltitudeRun(string id)
        {
            DateTime deadline = DateTime.UtcNow.AddSeconds(35);
            while (desktopRunId != id || altitudeRunId != id) {
                if (DateTime.UtcNow > deadline) throw new Exception("Aircraft altitude did not load: " + id);
                await Task.Delay(150);
            }
            await Task.Delay(2200); SetPlaying(false);
        }
        public async Task VerifyAltitudeFeedback(string directory)
        {
            Directory.CreateDirectory(directory); DateTime deadline = DateTime.UtcNow.AddSeconds(75);
            while (desktopApi == null || desktopCatalog == null || !webReady) {
                if (DateTime.UtcNow > deadline) throw new Exception("Altitude verification backend not ready"); await Task.Delay(200);
            }
            string id = "workbench_20261110_163408_905850";
            if (!desktopCatalog.Runs.Any(r => r.Id == id)) id = desktopCatalog.Runs.First(r => r.Scenario == "interop_recon" && r.Done > 0).Id;
            LoadRunAsync(id); await AwaitAltitudeRun(id);
            SetTime(43.7); await Task.Delay(1300); UpdateAircraftAltitude();
            string aircraft = Convert.ToString(altitudeAircraft.SelectedItem);
            if (aircraft != "rover_41" || !altitudeReading.Text.Contains("z ")) throw new Exception("Idle plane still hides wing altitude: " + aircraft + ", " + altitudeReading.Text);
            var samples = altitudeSamples[aircraft];
            var latest = samples.Last(s => s.Time <= Time + 1e-9);
            if (!latest.Z.HasValue || !altitudeReading.Text.Contains(latest.Z.Value.ToString("0.00"))) throw new Exception("Height differs from the recorded sample");
            int visiblePoints = samples.Count(s => s.Time <= Time + 1e-9 && s.Z.HasValue);
            if (visiblePoints < 2 || altitudeChart.Height < 40) throw new Exception("Height chart is empty or clipped");
            string reading = altitudeReading.Text;
            Size = new Size(1500, 940); ResetLayout(); await Task.Delay(250);
            await SaveNativeScreenshot(Path.Combine(directory, "recon-altitude.png"));
            Size = new Size(1180, 740); ResetLayout(); await Task.Delay(250);
            if (altitudeChart.Height < 40) throw new Exception("Compact window clips height chart");
            await SaveNativeScreenshot(Path.Combine(directory, "recon-altitude-compact.png"));
            altitudeAircraft.SelectedItem = "rover_42"; UpdateAircraftAltitude();
            if (!altitudeReading.Text.Contains("z ")) throw new Exception("Second flown aircraft has no reading");
            string secondReading = altitudeReading.Text;
            var payload = new Dictionary<string, object> {
                { "runId", id }, { "aircraft", altitudeSamples.Select(p => new {
                    id=p.Key, samples=p.Value.Select(s => new object[] { s.Time, s.Z, s.Lost }).ToArray()
                }).ToArray() }
            };
            var repeated = (Dictionary<string, object>)desktopJson.DeserializeObject(desktopJson.Serialize(payload));
            HandleAltitudeMessage("altitude", repeated);
            if (Convert.ToString(altitudeAircraft.SelectedItem) != "rover_42") throw new Exception("Repeated data reset manual aircraft selection");
            altitudeAircraft.SelectedItem = "rover_31"; UpdateAircraftAltitude();
            if (!altitudeReading.Text.Contains("没有该机的高度采样") || altitudeChart.Samples.Count != 0 || !altitudeAircraft.GetItemText("rover_31").Contains("无高度记录")) throw new Exception("Idle aircraft is not explicitly identified");
            altitudeAircraft.SelectedItem = "rover_42";
            var other = desktopCatalog.Runs.First(r => r.Scenario == "interop_containment" && r.Done > 0);
            LoadRunAsync(other.Id); await AwaitAltitudeRun(other.Id);
            if (Convert.ToString(altitudeAircraft.SelectedItem) != "rover_31") throw new Exception("Switching runs reused the previous run's aircraft choice");
            File.WriteAllText(Path.Combine(directory, "altitude-feedback-verification.json"), desktopJson.Serialize(new {
                sourceRun=id, defaultAircraft=aircraft, reading=reading, recordedHeight=latest.Z,
                visiblePoints=visiblePoints, secondAircraft="rover_42", secondReading=secondReading,
                idleAircraftExplicit=true, repeatPreservesManualChoice=true,
                newRunDefault="rover_31", compactChartVisible=true
            }));
        }
    }
}
