using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    internal sealed class AltitudeSample
    {
        public double Time;
        public double? Z;
        public bool Lost;
    }
    internal sealed class AltitudeChart : Control
    {
        public List<AltitudeSample> Samples = new List<AltitudeSample>();
        public double At;
        public AltitudeChart()
        {
            Dock = DockStyle.Fill; BackColor = Color.White;
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            var points = Samples.Where(p => p.Time <= At + 1e-9).ToList();
            var valid = points.Where(p => p.Z.HasValue).ToList();
            if (valid.Count == 0 || Width < 80 || Height < 35) return;
            double lo = valid.Min(p => p.Z.Value), hi = valid.Max(p => p.Z.Value);
            if (hi == lo) { lo -= .5; hi += .5; }
            float left = 43, top = 8, right = Width - 9, bottom = Height - 21;
            Func<AltitudeSample, PointF> xy = p => new PointF(left + (right-left)*(float)(p.Time/Math.Max(At,1)), bottom-(bottom-top)*(float)((p.Z.Value-lo)/(hi-lo)));
            using (var axis = new Pen(Color.FromArgb(215, 226, 239)))
            using (var line = new Pen(Color.FromArgb(31, 111, 195), 1.5f))
            using (var ink = new SolidBrush(Color.FromArgb(88, 112, 140)))
            {
                e.Graphics.DrawLines(axis, new[] {new PointF(left,top),new PointF(left,bottom),new PointF(right,bottom)});
                AltitudeSample previous = null;
                foreach (var p in points)
                {
                    if (!p.Z.HasValue) { previous = null; continue; }
                    var q = xy(p);
                    if (previous != null) { var a = xy(previous); e.Graphics.DrawLines(line, new[] {a,new PointF(q.X,a.Y),q}); }
                    e.Graphics.FillEllipse(Brushes.SteelBlue,q.X-1.3f,q.Y-1.3f,2.6f,2.6f); previous=p;
                }
                e.Graphics.DrawString(hi.ToString("0.0"),Font,ink,0,0);
                e.Graphics.DrawString(lo.ToString("0.0"),Font,ink,0,bottom-9);
                e.Graphics.DrawString("0 s",Font,ink,left,bottom+3);
                var label=At.ToString("0.0")+" s";
                e.Graphics.DrawString(label,Font,ink,Math.Max(left,right-e.Graphics.MeasureString(label,Font).Width),bottom+3);
            }
        }
    }

    public sealed partial class MainWindow
    {
        private ComboBox altitudeAircraft;
        private Label altitudeReading;
        private AltitudeChart altitudeChart;
        private string altitudeRunId = "";
        private readonly Dictionary<string,List<AltitudeSample>> altitudeSamples = new Dictionary<string,List<AltitudeSample>>();

        private Control BuildAircraftAltitude()
        {
            var panel = new Panel { Dock=DockStyle.Bottom, Height=224, Padding=new Padding(9,4,9,6), BackColor=Color.White };
            var title = new Label { Text="飞机运行高度", Dock=DockStyle.Top, Height=23, ForeColor=Blue, Font=new Font(Font,FontStyle.Bold) };
            altitudeAircraft = new ComboBox { Dock=DockStyle.Top, DropDownStyle=ComboBoxStyle.DropDownList, Name="AltitudeAircraft" };
            altitudeAircraft.FormattingEnabled = true;
            altitudeAircraft.Format += delegate(object sender, ListControlConvertEventArgs e) {
                string id = Convert.ToString(e.ListItem); List<AltitudeSample> samples;
                e.Value = id + (altitudeSamples.TryGetValue(id, out samples) && samples.Any(p => p.Z.HasValue) ? " · 有高度记录" : " · 无高度记录");
            };
            altitudeReading = new Label { Dock=DockStyle.Top, Height=40, Padding=new Padding(0,5,0,0), Text="等待飞机高度记录", Name="AltitudeReading" };
            altitudeChart = new AltitudeChart { Name="AltitudeChart", Font=new Font(Font.FontFamily,7.5f) };
            var note = new Label { Dock=DockStyle.Bottom, Height=32, Text="场景坐标 z，未标定海拔。\r\n阶梯线连接已记录采样，仅显示回放时刻以前。", ForeColor=Color.SlateGray, Font=new Font(Font.FontFamily,7.5f) };
            panel.Controls.Add(altitudeChart);panel.Controls.Add(altitudeReading);panel.Controls.Add(altitudeAircraft);panel.Controls.Add(title);panel.Controls.Add(note);
            altitudeAircraft.SelectedIndexChanged += delegate { UpdateAircraftAltitude(); };
            return panel;
        }

        private bool HandleAltitudeMessage(string type, Dictionary<string,object> message)
        {
            if(type!="altitude")return false;
            string run=Convert.ToString(message["runId"]);
            if(run!=desktopRunId)return true;
            string selected=altitudeRunId==run?Convert.ToString(altitudeAircraft.SelectedItem):"";
            altitudeSamples.Clear();altitudeAircraft.Items.Clear();altitudeRunId=run;
            foreach (object raw in (IEnumerable)message["aircraft"])
            {
                var worker=raw as Dictionary<string,object>; if(worker==null)continue;
                string id=Convert.ToString(worker["id"]); var samples=new List<AltitudeSample>();
                foreach(object point in (IEnumerable)worker["samples"])
                {
                    var values=(object[])point;double t,z;
                    if(!double.TryParse(Convert.ToString(values[0],CultureInfo.InvariantCulture),NumberStyles.Float,CultureInfo.InvariantCulture,out t)||double.IsNaN(t)||double.IsInfinity(t))continue;
                    double? height=values[1]!=null && double.TryParse(Convert.ToString(values[1],CultureInfo.InvariantCulture),NumberStyles.Float,CultureInfo.InvariantCulture,out z)&&!double.IsNaN(z)&&!double.IsInfinity(z)?(double?)z:null;
                    samples.Add(new AltitudeSample {Time=t,Z=height,Lost=Convert.ToBoolean(values[2])});
                }
                altitudeSamples[id]=samples.OrderBy(p=>p.Time).ToList();
            }
            // Idle aircraft remain selectable, but must not hide the flown aircraft's feedback.
            foreach (string id in altitudeSamples.Keys.OrderByDescending(id => altitudeSamples[id].Any(p => p.Z.HasValue))
                .ThenByDescending(id => altitudeSamples[id].Count > 0).ThenBy(id => PlatformNumberKey(id), StringComparer.OrdinalIgnoreCase))
                altitudeAircraft.Items.Add(id);
            if(altitudeAircraft.Items.Count>0)altitudeAircraft.SelectedIndex=Math.Max(0,altitudeAircraft.Items.IndexOf(selected));
            UpdateAircraftAltitude();return true;
        }

        private void UpdateAircraftAltitude()
        {
            if(altitudeChart==null)return;
            string id=Convert.ToString(altitudeAircraft.SelectedItem);List<AltitudeSample> all;
            if(altitudeRunId!=desktopRunId || !altitudeSamples.TryGetValue(id,out all))
            {
                altitudeReading.Text=altitudeRunId==desktopRunId?"当前运行没有飞机":"等待本轮飞机高度记录";
                altitudeChart.Samples=new List<AltitudeSample>();altitudeChart.Invalidate();return;
            }
            altitudeChart.Samples=all;altitudeChart.At=Time;
            var past=all.Where(p=>p.Time<=Time+1e-9).ToList();var latest=past.LastOrDefault();
            if(all.Count==0)altitudeReading.Text="本轮没有该机的高度采样\r\n可切换标记“有高度记录”的飞机";
            else if(latest==null || !latest.Z.HasValue)altitudeReading.Text="当前时刻无有效高度反馈";
            else
            {
                var prev=past.Count<2?null:past[past.Count-2];
                string change=latest.Lost?"反馈已失联":prev==null||!prev.Z.HasValue?"单点反馈":Math.Abs(latest.Z.Value-prev.Z.Value)<.001?"高度未变":latest.Z>prev.Z?"上升":"下降";
                altitudeReading.Text="z "+latest.Z.Value.ToString("0.00")+" · "+change+"\r\n最近反馈 "+latest.Time.ToString("0.0")+" s";
            }
            altitudeChart.Invalidate();
        }
    }
}
