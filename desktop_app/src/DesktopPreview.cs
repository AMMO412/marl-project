using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace MarlDesktopPreview
{
    public class DemoTask
    {
        public string Id, Seat, Name, ShortName, Type, Area, Platform;
        public double Start, End, Travel;
        public PointF Position, Spawn, Marker;
        public PointF[] Path;
        public DemoTask(string id, string seat, string name, string shortName, string type, string area,
                        double start, double end, double travel, PointF position, PointF spawn, PointF[] path, string platform)
        {
            Id = id; Seat = seat; Name = name; ShortName = shortName; Type = type; Area = area;
            Start = start; End = end; Travel = travel; Position = position; Spawn = spawn; Path = path; Platform = platform;
            Marker = position;
        }
        public string[] Members { get { return new string[] { Platform }; } }
    }

    public class DemoTarget
    {
        public string Id, Label, Done;
        public PointF Start, Goal;
        public double T0, ResolveAt;
        public float Speed;
        public bool Authorized;
        public DemoTarget(string id, string label, string done, PointF start, PointF goal, float speed, double t0, double resolveAt, bool authorized)
        { Id = id; Label = label; Done = done; Start = start; Goal = goal; Speed = speed; T0 = t0; ResolveAt = resolveAt; Authorized = authorized; }
    }

    public class TaskProperties
    {
        [Category("1. 席位信息"), DisplayName("席位编号"), ReadOnly(true)] public string Id { get; set; }
        [Category("1. 席位信息"), DisplayName("席位名称"), ReadOnly(true)] public string Name { get; set; }
        [Category("1. 席位信息"), DisplayName("职责类型"), ReadOnly(true)] public string Type { get; set; }
        [Category("1. 席位信息"), DisplayName("所属封控区"), ReadOnly(true)] public string Area { get; set; }
        [Category("2. 计划参数"), DisplayName("开始时间 (s)"), ReadOnly(true)] public string Start { get; set; }
        [Category("2. 计划参数"), DisplayName("结束时间 (s)"), ReadOnly(true)] public string End { get; set; }
        [Category("2. 计划参数"), DisplayName("机动时长"), ReadOnly(true)] public string Travel { get; set; }
        [Category("2. 计划参数"), DisplayName("分配平台"), ReadOnly(true)] public string Members { get; set; }
        [Category("2. 计划参数"), DisplayName("占位点坐标"), ReadOnly(true)] public string Position { get; set; }
        [Category("3. 回放状态"), DisplayName("当前阶段"), ReadOnly(true)] public string Phase { get; set; }
        [Category("3. 回放状态"), DisplayName("任务进度"), ReadOnly(true)] public string Progress { get; set; }
        [Category("3. 回放状态"), DisplayName("数据来源"), ReadOnly(true)] public string Source { get; set; }
    }

    public sealed class SceneCanvas : Control
    {
        public MainWindow OwnerWindow;
        public bool ShowLabels = true, ShowRoutes = true, ShowGrid = true, ShowBoundary = true, ShowBuildings = true, ShowUnits = true, ShowTargets = true;
        public float Zoom = 1f;
        public PointF Pan = PointF.Empty;
        public bool FullView;
        private Point down;
        private PointF startPan;
        private bool dragging;
        private readonly Font labelFont = new Font("Microsoft YaHei UI", 8f);
        private readonly Font smallFont = new Font("Microsoft YaHei UI", 7f);
        private readonly Font tagFont = new Font("Microsoft YaHei UI", 7f, FontStyle.Bold);
        private readonly Font mapFont = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold);
        private static readonly RectangleF BlockView = new RectangleF(-205f, -202f, 230f, 116f);
        private static readonly RectangleF RouteView = new RectangleF(-215f, -215f, 245f, 210f);

        public SceneCanvas(MainWindow owner)
        {
            OwnerWindow = owner; BackColor = Color.White; Dock = DockStyle.Fill; Cursor = Cursors.Cross;
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            MouseWheel += delegate(object s, MouseEventArgs e) { Zoom = Math.Min(3.2f, Math.Max(.6f, Zoom * (e.Delta > 0 ? 1.12f : .89f))); Invalidate(); };
            MouseDown += delegate(object s, MouseEventArgs e) { if (e.Button != MouseButtons.Left) return; down = e.Location; startPan = Pan; dragging = true; Capture = true; Focus(); };
            MouseMove += delegate(object s, MouseEventArgs e) { if (dragging) { Pan = new PointF(startPan.X + e.X - down.X, startPan.Y + e.Y - down.Y); Invalidate(); } };
            MouseUp += delegate(object s, MouseEventArgs e)
            {
                if (!dragging) return; dragging = false; Capture = false;
                if (Math.Abs(e.X - down.X) + Math.Abs(e.Y - down.Y) >= 5) return;
                Pan = startPan;
                foreach (DemoTask t in OwnerWindow.Tasks)
                {
                    PointF p = ScreenPoint(t.Marker);
                    if (Math.Abs(p.X - e.X) < 22 && Math.Abs(p.Y - e.Y) < 22) { OwnerWindow.SelectTask(t.Id); return; }
                }
            };
        }
        private RectangleF View { get { return FullView ? RouteView : BlockView; } }
        private float SceneScale
        {
            get
            {
                RectangleF v = View;
                float sx = (ClientSize.Width - 64f) / v.Width;
                float sy = (ClientSize.Height - 46f) / v.Height;
                return Math.Max(.05f, Math.Min(sx, sy) * Zoom);
            }
        }
        private PointF Origin
        {
            get
            {
                RectangleF v = View; float s = SceneScale;
                return new PointF((ClientSize.Width - v.Width * s) / 2f + Pan.X, (ClientSize.Height - v.Height * s) / 2f + Pan.Y);
            }
        }
        public PointF ScreenPoint(PointF p)
        {
            PointF o = Origin; float s = SceneScale; RectangleF v = View;
            return new PointF(o.X + (p.X - v.X) * s, o.Y + (v.Bottom - p.Y) * s);
        }
        private PointF P(float x, float y) { return ScreenPoint(new PointF(x, y)); }
        private void Line(Graphics g, Pen pen, float x1, float y1, float x2, float y2) { g.DrawLine(pen, P(x1, y1), P(x2, y2)); }
        private RectangleF WR(float x0, float y0, float x1, float y1)
        {
            PointF a = P(x0, y1); PointF b = P(x1, y0);
            return new RectangleF(a.X, a.Y, Math.Max(1f, b.X - a.X), Math.Max(1f, b.Y - a.Y));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
            if (ShowGrid) DrawGrid(g);
            DrawRoads(g);
            if (ShowBuildings) DrawBuildings(g);
            if (ShowBoundary) DrawContainment(g);
            if (ShowRoutes) DrawRoutes(g);
            if (ShowTargets) DrawTargets(g);
            if (ShowUnits) { DrawAir(g); DrawSeats(g); }
            DrawOverlay(g);
        }

        private void DrawGrid(Graphics g)
        {
            RectangleF v = View;
            using (Pen minor = new Pen(Color.FromArgb(244, 247, 251)))
            using (Pen major = new Pen(Color.FromArgb(234, 240, 247)))
            {
                for (float x = -240; x <= 60; x += 10)
                {
                    if (x < v.Left - 15 || x > v.Right + 15) continue;
                    Line(g, ((int)Math.Round(x) % 50 == 0) ? major : minor, x, v.Top - 30, x, v.Bottom + 30);
                }
                for (float y = -240; y <= 0; y += 10)
                {
                    if (y < v.Top - 15 || y > v.Bottom + 15) continue;
                    Line(g, ((int)Math.Round(y) % 50 == 0) ? major : minor, v.Left - 30, y, v.Right + 30, y);
                }
            }
        }

        private void DrawRoads(Graphics g)
        {
            using (SolidBrush b = new SolidBrush(Color.FromArgb(238, 242, 247)))
            {
                g.FillRectangle(b, WR(-165, -152, -25, -138));
                g.FillRectangle(b, WR(-102, -200, -88, -90));
            }
            using (SolidBrush plaza = new SolidBrush(Color.FromArgb(230, 236, 245)))
                g.FillRectangle(plaza, WR(-112, -162, -78, -128));
            using (Pen edge = new Pen(Color.FromArgb(222, 229, 238)))
            {
                RectangleF road = WR(-165, -152, -25, -138); g.DrawRectangle(edge, road.X, road.Y, road.Width, road.Height);
                road = WR(-102, -200, -88, -90); g.DrawRectangle(edge, road.X, road.Y, road.Width, road.Height);
                road = WR(-112, -162, -78, -128); g.DrawRectangle(edge, road.X, road.Y, road.Width, road.Height);
            }
            using (Pen lane = new Pen(Color.FromArgb(207, 217, 230), 1f))
            {
                lane.DashStyle = DashStyle.Dash;
                Line(g, lane, -165, -145, -114, -145);
                Line(g, lane, -76, -145, -25, -145);
                Line(g, lane, -95, -200, -95, -164);
                Line(g, lane, -95, -126, -95, -90);
            }
            using (Pen zebra = new Pen(Color.FromArgb(190, 216, 225, 237), 1.8f))
            {
                for (int i = 0; i < 4; i++)
                {
                    Line(g, zebra, -101, -126.5f + i * 2.2f, -89, -126.5f + i * 2.2f);
                    Line(g, zebra, -101, -163.5f - i * 2.2f, -89, -163.5f - i * 2.2f);
                    Line(g, zebra, -113.5f - i * 2.2f, -151, -113.5f - i * 2.2f, -139);
                    Line(g, zebra, -76.5f + i * 2.2f, -151, -76.5f + i * 2.2f, -139);
                }
            }
        }

        private void Building(Graphics g, float x0, float y0, float x1, float y1, string name, string height)
        {
            RectangleF r = WR(x0, y0, x1, y1);
            using (SolidBrush b = new SolidBrush(Color.FromArgb(242, 246, 251))) g.FillRectangle(b, r);
            using (Pen pen = new Pen(Color.FromArgb(189, 204, 221)))
            {
                g.DrawRectangle(pen, r.X, r.Y, r.Width, r.Height);
                if (r.Width > 46 && r.Height > 26) g.DrawRectangle(pen, r.X + 3, r.Y + 3, r.Width - 7, r.Height - 7);
            }
            if (!ShowLabels || r.Width < 38) return;
            using (StringFormat f = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
            using (SolidBrush nameBrush = new SolidBrush(Color.FromArgb(112, 133, 156)))
            using (SolidBrush heightBrush = new SolidBrush(Color.FromArgb(159, 174, 192)))
            {
                bool twoLines = r.Width >= 56 && r.Height >= 26;
                g.DrawString(name, smallFont, nameBrush, new RectangleF(r.X, r.Y + r.Height / 2 - (twoLines ? 10 : 6), r.Width, 12), f);
                if (twoLines) g.DrawString(height, smallFont, heightBrush, new RectangleF(r.X, r.Y + r.Height / 2 + 1, r.Width, 12), f);
            }
        }

        private void DrawBuildings(Graphics g)
        {
            Building(g, -145.6f, -191.8f, -129.2f, -178.9f, "House 1", "住宅 · 7.7 m");
            Building(g, -60.6f, -190.7f, -47.9f, -180.9f, "House 2", "住宅 · 7.2 m");
            Building(g, -144.1f, -109.4f, -130.9f, -100.7f, "House 3", "住宅 · 9.2 m");
            Building(g, -60.9f, -111.1f, -44.4f, -98.2f, "House 4", "住宅 · 7.7 m");
            Building(g, -173.9f, -153.9f, -156.2f, -136.2f, "Office 1", "办公楼 · 18.7 m");
            Building(g, -33.9f, -153.9f, -16.2f, -136.2f, "Office 2", "办公楼 · 18.7 m");
        }

        private void DrawContainment(Graphics g)
        {
            RectangleF area = WR(-125, -175, -65, -115);
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(10, 46, 130, 203))) g.FillRectangle(fill, area);
            using (Pen border = new Pen(Color.FromArgb(46, 130, 203), 2.2f)) g.DrawRectangle(border, area.X, area.Y, area.Width, area.Height);

            Color c1 = Color.FromArgb(61, 115, 190);
            Color c2 = Color.FromArgb(47, 158, 143);
            using (Pen p1 = new Pen(c1, 4.2f) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            using (Pen p2 = new Pen(c2, 4.2f) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                Line(g, p1, -125, -115, -102, -115); Line(g, p1, -88, -115, -65, -115);
                Line(g, p1, -65, -115, -65, -138); Line(g, p1, -65, -152, -65, -175);
                Line(g, p2, -65, -175, -125, -175); Line(g, p2, -125, -175, -125, -115);
            }
            using (Pen gate = new Pen(Color.FromArgb(46, 130, 203), 1.6f) { DashStyle = DashStyle.Dash })
            {
                Line(g, gate, -102, -115, -88, -115);
                Line(g, gate, -65, -138, -65, -152);
            }
            GatePost(g, -102, -115); GatePost(g, -88, -115);
            GatePost(g, -65, -138); GatePost(g, -65, -152);

            if (!ShowLabels) return;
            LabelBox(g, "T1 封控区", "60 × 60 m", -127, -119, Color.FromArgb(46, 130, 203), ContentAlignment.MiddleRight);
            DrawText(g, "1/2 段", -62.5f, -121, tagFont, c1, ContentAlignment.MiddleLeft);
            DrawText(g, "2/2 段", -127, -160, tagFont, c2, ContentAlignment.MiddleRight);
        }
        private void GatePost(Graphics g, float x, float y)
        {
            PointF p = P(x, y);
            using (SolidBrush b = new SolidBrush(Color.FromArgb(46, 130, 203))) g.FillRectangle(b, p.X - 2.5f, p.Y - 2.5f, 5, 5);
        }

        private void DrawRoutes(Graphics g)
        {
            PointF c = P(-2.5f, -19f);
            float r = 30f * SceneScale;
            using (SolidBrush b = new SolidBrush(Color.FromArgb(16, 46, 130, 203))) g.FillEllipse(b, c.X - r, c.Y - r, r * 2, r * 2);
            using (Pen pen = new Pen(Color.FromArgb(120, 148, 186)) { DashStyle = DashStyle.Dash }) g.DrawEllipse(pen, c.X - r, c.Y - r, r * 2, r * 2);
            foreach (DemoTask t in OwnerWindow.Tasks)
            {
                PointF sp = P(t.Spawn.X, t.Spawn.Y);
                using (SolidBrush b = new SolidBrush(Color.FromArgb(150, 31, 111, 195))) g.FillEllipse(b, sp.X - 2.5f, sp.Y - 2.5f, 5, 5);
            }
            if (ShowLabels) LabelBox(g, "集结待机区", "R=30 m · 编成表出生位", -2.5f, -53, Color.FromArgb(110, 134, 163), ContentAlignment.TopCenter);

            foreach (DemoTask t in OwnerWindow.Tasks)
            {
                Color color = MainWindow.RoleColor(t);
                using (Pen pen = new Pen(Color.FromArgb(115, color), 1.3f) { DashStyle = DashStyle.Dash })
                    g.DrawLines(pen, Array.ConvertAll(t.Path, delegate(PointF p) { return P(p.X, p.Y); }));
            }
        }

        private void DrawTargets(Graphics g)
        {
            foreach (DemoTarget target in OwnerWindow.Targets)
            {
                Color color = target.Authorized ? Color.FromArgb(47, 158, 143) : Color.FromArgb(203, 88, 88);
                float off = target.Id == "AU-1" ? 2f : 0f;
                using (Pen pen = new Pen(Color.FromArgb(150, color), 1.4f) { DashStyle = DashStyle.Dash })
                    Line(g, pen, target.Start.X + off, target.Start.Y, target.Goal.X + off, target.Goal.Y);
                PointF goal = P(target.Goal.X + off, target.Goal.Y);
                using (SolidBrush b = new SolidBrush(Color.FromArgb(150, color)))
                    g.FillPolygon(b, new PointF[] { new PointF(goal.X, goal.Y), new PointF(goal.X - 4, goal.Y - 9), new PointF(goal.X + 4, goal.Y - 9) });

                PointF pos; string state;
                TargetState(target, out pos, out state);
                PointF sp = P(pos.X + off, pos.Y);
                using (SolidBrush b = new SolidBrush(color)) g.FillEllipse(b, sp.X - 5, sp.Y - 5, 10, 10);
                using (Pen ring = new Pen(Color.White, 1.6f)) g.DrawEllipse(ring, sp.X - 5, sp.Y - 5, 10, 10);
                if (!ShowLabels) continue;
                bool in2 = target.Id == "IN-2";
                ContentAlignment align = target.Id == "AU-1" ? ContentAlignment.MiddleRight : ContentAlignment.MiddleLeft;
                float lx = target.Id == "AU-1" ? target.Start.X - 2 : target.Start.X + 2;
                float ly = in2 ? target.Start.Y + 9 : target.Start.Y;
                LabelBox(g, target.Id + " " + target.Label, state, lx, ly, color, align);
            }
        }
        private void TargetState(DemoTarget t, out PointF pos, out string state)
        {
            double time = OwnerWindow.Time;
            float speed = t.Speed;
            float dx = t.Goal.X - t.Start.X, dy = t.Goal.Y - t.Start.Y;
            float length = (float)Math.Sqrt(dx * dx + dy * dy);
            float ux = dx / length, uy = dy / length;
            if (time < t.T0) { pos = t.Start; state = "未出现"; return; }
            double travelled = speed * (time - t.T0);
            if (t.Id == "IN-2")
            {
                double outbound = speed * (t.ResolveAt - t.T0);
                if (time < t.ResolveAt) { pos = new PointF(t.Start.X + ux * (float)travelled, t.Start.Y + uy * (float)travelled); state = "接近中"; }
                else
                {
                    double back = speed * (time - t.ResolveAt);
                    float remain = (float)Math.Max(0, outbound - back);
                    pos = new PointF(t.Start.X + ux * remain, t.Start.Y + uy * remain);
                    state = remain > 0.5f ? "警告撤离中" : "已撤离";
                }
                return;
            }
            if (t.Id == "IN-1")
            {
                double stop = speed * (t.ResolveAt - t.T0);
                travelled = Math.Min(travelled, stop);
                pos = new PointF(t.Start.X + ux * (float)travelled, t.Start.Y + uy * (float)travelled);
                state = time < t.ResolveAt ? "接近中" : "已拦阻";
                return;
            }
            travelled = Math.Min(travelled, length);
            pos = new PointF(t.Start.X + ux * (float)travelled, t.Start.Y + uy * (float)travelled);
            state = pos.Y <= -115.5f ? "已授权放行" : "接近中";
        }

        private void DrawAir(Graphics g)
        {
            PointF c = P(-95f, -145f);
            float r = 55f * SceneScale;
            using (Pen orbit = new Pen(Color.FromArgb(95, 122, 111, 193), 1f) { DashStyle = DashStyle.Dash })
                g.DrawEllipse(orbit, c.X - r, c.Y - r, r * 2, r * 2);
            DrawText(g, "空中监视 60 m · R=55 m", -95, -197, smallFont, Color.FromArgb(140, 128, 200), ContentAlignment.BottomCenter);
        }

        private void DrawSeats(Graphics g)
        {
            bool compact = SceneScale < 3.0f;
            foreach (DemoTask t in OwnerWindow.Tasks)
            {
                Color color = MainWindow.RoleColor(t);
                PointF p = P(t.Marker.X, t.Marker.Y);
                if (t.Id == OwnerWindow.SelectedId)
                {
                    using (SolidBrush b = new SolidBrush(Color.FromArgb(26, color))) g.FillEllipse(b, p.X - 16, p.Y - 16, 32, 32);
                    using (Pen ring = new Pen(Color.FromArgb(150, color), 1.2f) { DashStyle = DashStyle.Dash }) g.DrawEllipse(ring, p.X - 14, p.Y - 14, 28, 28);
                }
                DrawUnit(g, t, color, p);
                if (!ShowLabels || (compact && t.Id != OwnerWindow.SelectedId)) continue;
                string l1 = t.Seat + "  " + t.ShortName;
                string l2 = t.Platform;
                float lx = t.Marker.X, ly = t.Marker.Y;
                ContentAlignment align = ContentAlignment.BottomCenter;
                if (t.Id == "T1-S1") { ly -= 6.5f; align = ContentAlignment.TopCenter; }
                else if (t.Id == "T1-S2") { ly -= 6.5f; align = ContentAlignment.TopCenter; }
                else if (t.Id == "T1-S3") { ly += 6.2f; align = ContentAlignment.BottomCenter; }
                else if (t.Id == "T1-S4") { lx += 2.2f; ly -= 3f; align = ContentAlignment.MiddleLeft; }
                else if (t.Id == "T1-S5") { ly += 6.5f; align = ContentAlignment.BottomCenter; }
                else { lx += 2.2f; ly -= 7.2f; align = ContentAlignment.MiddleLeft; }
                LabelBox(g, l1, l2, lx, ly, color, align);
            }
        }
        private void DrawUnit(Graphics g, DemoTask t, Color color, PointF p)
        {
            using (SolidBrush b = new SolidBrush(color))
            {
                if (t.Type == "空中监视") g.FillPolygon(b, new PointF[] { new PointF(p.X, p.Y - 7), new PointF(p.X + 6, p.Y + 5), new PointF(p.X - 6, p.Y + 5) });
                else if (t.Platform == "U4" || t.Platform == "U5")
                {
                    using (Pen pen = new Pen(color, 1.6f)) g.DrawRectangle(pen, p.X - 7, p.Y - 5, 14, 10);
                    using (SolidBrush inner = new SolidBrush(Color.White)) g.FillRectangle(inner, p.X - 3, p.Y - 2, 6, 4);
                }
                else { g.FillRectangle(b, p.X - 5.5f, p.Y - 4, 11, 8); }
            }
        }

        private void DrawOverlay(Graphics g)
        {
            using (SolidBrush b = new SolidBrush(Color.FromArgb(133, 151, 173)))
            {
                g.DrawString("N", mapFont, b, Width - 34, 14);
                g.DrawString("↑", mapFont, b, Width - 33, 33);
                g.DrawString("局部坐标 XY（米，向北为正）  |  " + (FullView ? "全程视图 · 集结 → 占位" : "封控区视图 · 小十字路口街区"), smallFont, b, 15, Height - 24);
                g.DrawString("滚轮缩放 · 拖动平移 · 点击席位", smallFont, b, Math.Max(15, Width - 212), Height - 24);
            }
            float s = SceneScale, meters = s * 50 > 230 ? 20f : 50f, px = meters * s;
            using (Pen bar = new Pen(Color.FromArgb(133, 151, 173), 1.4f))
            {
                g.DrawLine(bar, 18, Height - 42, 18 + px, Height - 42);
                g.DrawLine(bar, 18, Height - 46, 18, Height - 38);
                g.DrawLine(bar, 18 + px, Height - 46, 18 + px, Height - 38);
            }
            using (SolidBrush b = new SolidBrush(Color.FromArgb(133, 151, 173)))
                g.DrawString(((int)meters) + " m", smallFont, b, 20, Height - 58);
        }

        private void DrawText(Graphics g, string text, float x, float y, Font font, Color color, ContentAlignment align)
        {
            PointF p = P(x, y);
            SizeF size = g.MeasureString(text, font);
            float dx = 0, dy = 0;
            if (align == ContentAlignment.TopCenter || align == ContentAlignment.MiddleCenter || align == ContentAlignment.BottomCenter) dx = -size.Width / 2;
            else if (align == ContentAlignment.TopRight || align == ContentAlignment.MiddleRight || align == ContentAlignment.BottomRight) dx = -size.Width;
            if (align == ContentAlignment.MiddleLeft || align == ContentAlignment.MiddleCenter || align == ContentAlignment.MiddleRight) dy = -size.Height / 2;
            else if (align == ContentAlignment.BottomLeft || align == ContentAlignment.BottomCenter || align == ContentAlignment.BottomRight) dy = -size.Height;
            using (SolidBrush b = new SolidBrush(color)) g.DrawString(text, font, b, p.X + dx, p.Y + dy);
        }
        private void LabelBox(Graphics g, string line1, string line2, float x, float y, Color color, ContentAlignment align)
        {
            PointF p = P(x, y);
            SizeF s1 = g.MeasureString(line1, tagFont);
            SizeF s2 = g.MeasureString(line2, smallFont);
            float w = Math.Max(s1.Width, s2.Width) + 8, h = s1.Height + s2.Height + 2;
            float left = p.X, top = p.Y;
            if (align == ContentAlignment.TopCenter || align == ContentAlignment.MiddleCenter || align == ContentAlignment.BottomCenter) left = p.X - w / 2;
            else if (align == ContentAlignment.TopRight || align == ContentAlignment.MiddleRight || align == ContentAlignment.BottomRight) left = p.X - w;
            if (align == ContentAlignment.MiddleLeft || align == ContentAlignment.MiddleCenter || align == ContentAlignment.MiddleRight) top = p.Y - h / 2;
            else if (align == ContentAlignment.BottomLeft || align == ContentAlignment.BottomCenter || align == ContentAlignment.BottomRight) top = p.Y - h;
            using (SolidBrush back = new SolidBrush(Color.FromArgb(232, 255, 255, 255))) g.FillRectangle(back, left, top, w, h);
            using (SolidBrush c = new SolidBrush(color)) g.DrawString(line1, tagFont, c, left + 4, top + 1);
            using (SolidBrush c = new SolidBrush(Color.FromArgb(126, 144, 166))) g.DrawString(line2, smallFont, c, left + 4, top + s1.Height);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { labelFont.Dispose(); smallFont.Dispose(); tagFont.Dispose(); mapFont.Dispose(); }
            base.Dispose(disposing);
        }
    }

    public sealed partial class MainWindow : Form
    {
        public static readonly Color Blue = Color.FromArgb(31, 111, 195);
        public readonly List<DemoTask> Tasks = new List<DemoTask>();
        public readonly List<DemoTarget> Targets = new List<DemoTarget>();
        public string SelectedId = "T1-S3";
        public double Time = 106.0;
        public const double PlaybackEnd = 210.0;
        public SceneCanvas Canvas;
        public TabControl Documents;
        private TreeView tree;
        private PropertyGrid properties;
        private DataGridView taskGrid, platformGrid;
        private TextBox log;
        private Label selectedTitle, sceneInfo, clock;
        private ProgressBar taskProgress;
        private TrackBar timeline;
        private ToolStripStatusLabel status, timeStatus;
        private Button play;
        private Timer timer;
        private bool refreshing;
        private string scenarioName = "区域封控 · T-SEC（小十字路口）";
        private string objective = "时效优先";
        private decimal seed = 42;
        private readonly List<string> records = new List<string>();
        private ListView history;
        private SplitContainer leftSplit, rightSplit, bottomSplit;

        public static Color RoleColor(DemoTask t)
        {
            if (t.Type == "边界封控") return Color.FromArgb(61, 115, 190);
            if (t.Type == "通道哨位") return Color.FromArgb(47, 158, 143);
            if (t.Type == "机动拦截") return Color.FromArgb(206, 137, 46);
            return Color.FromArgb(122, 111, 193);
        }

        public MainWindow()
        {
            Text = "多智能体协同规划系统 — 区域封控 · 小十字路口街区";
            Font = new Font("Microsoft YaHei UI", 9f); BackColor = Color.White;
            ForeColor = Color.FromArgb(48, 59, 75); Size = new Size(1500, 940); MinimumSize = new Size(1100, 740);
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.None;
            using (Bitmap b = new Bitmap(32, 32)) { using (Graphics g = Graphics.FromImage(b)) { g.Clear(Blue); using (Font f = new Font("Segoe UI", 17f, FontStyle.Bold)) g.DrawString("M", f, Brushes.White, 1, 1); } Icon = Icon.FromHandle(b.GetHicon()); }
            Tasks.Add(new DemoTask("T1-S1", "#01", "边界段 1/2（北段·东段）", "边界段 1/2", "边界封控", "封控区北侧与东侧边界",
                21.184, 201.184, 21.2, new PointF(-79f, -145f), new PointF(-10f, -22.5f),
                new PointF[] { new PointF(-10f, -22.5f), new PointF(-72.9f, -110.8f), new PointF(-79f, -145f) }, "U4"));
            Tasks.Add(new DemoTask("T1-S2", "#02", "边界段 2/2（南段·西段）", "边界段 2/2", "边界封控", "封控区南侧与西侧边界",
                23.133, 203.133, 23.1, new PointF(-111f, -145f), new PointF(-10f, -17.5f),
                new PointF[] { new PointF(-10f, -17.5f), new PointF(-111f, -145f) }, "U5"));
            Tasks.Add(new DemoTask("T1-S3", "#03", "通道哨位 G-A", "哨位 G-A", "通道哨位", "北侧通道口 G-A",
                19.536, 199.536, 19.5, new PointF(-95f, -115f), new PointF(0f, -22.5f),
                new PointF[] { new PointF(0f, -22.5f), new PointF(-95f, -115f) }, "U1"));
            Tasks.Add(new DemoTask("T1-S4", "#04", "通道哨位 G-B", "哨位 G-B", "通道哨位", "东侧通道口 G-B",
                21.298, 201.298, 21.3, new PointF(-65f, -145f), new PointF(0f, -17.5f),
                new PointF[] { new PointF(0f, -17.5f), new PointF(-24.9f, -102.8f), new PointF(-65f, -145f) }, "U2"));
            Tasks.Add(new DemoTask("T1-S5", "#05", "机动拦截待机", "机动拦截", "机动拦截", "封控区中心路口",
                23.506, 203.506, 23.5, new PointF(-95f, -145f), new PointF(0f, -12.5f),
                new PointF[] { new PointF(0f, -12.5f), new PointF(-90.9f, -134.8f), new PointF(-95f, -145f) }, "U3"));
            Tasks.Add(new DemoTask("T1-S6", "#06", "空中监视盘旋", "空中监视", "空中监视", "封控区上空 60 m",
                8.751, 188.751, 8.8, new PointF(-95f, -145f), new PointF(-15f, -22.5f),
                new PointF[] { new PointF(-15f, -22.5f), new PointF(-95f, -145f) }, "U6"));

            Targets.Add(new DemoTarget("IN-1", "未授权", "已拦阻", new PointF(-95f, -90f), new PointF(-95f, -130f), 2.5f, 45, 54, false));
            Targets.Add(new DemoTarget("IN-2", "未授权", "已撤离", new PointF(-40f, -145f), new PointF(-70f, -145f), 2.0f, 70, 74, false));
            Targets.Add(new DemoTarget("AU-1", "已授权", "已放行", new PointF(-95f, -90f), new PointF(-95f, -135f), 2.5f, 100, 110, true));
            Tasks[5].Marker = new PointF(-46.4f, -170.8f);

            records.Add("T-SEC 街区封控 003"); records.Add("T-SEC 街区封控 002");
            BuildWindow(); SelectTask(SelectedId); RefreshPlayback(); InitializeDesktop();
            timer = new Timer { Interval = 100 }; timer.Tick += delegate { SetTime(Math.Min(PlaybackEnd, Time + .1 * PlaybackSpeed)); if (Time >= PlaybackEnd) SetPlaying(false); };
            FormClosed += delegate { timer.Dispose(); };
            KeyPreview = true; KeyDown += delegate(object s, KeyEventArgs e) { if (e.KeyCode == Keys.Space && !(ActiveControl is TextBoxBase)) { SetPlaying(!timer.Enabled); e.Handled = true; } };
        }
        private double PlaybackSpeed = 1;
        private MenuStrip BuildMenus()
        {
            MenuStrip menu = new MenuStrip { BackColor = Color.White, Padding = new Padding(7, 3, 0, 3), Height = 29, Renderer = new ToolStripProfessionalRenderer(new BlueColors()) };
            ToolStripMenuItem file = new ToolStripMenuItem("文件(&F)");
            AddMenu(file, "新建场景…", delegate { ShowConfiguration(); }, Keys.Control | Keys.N);
            AddMenu(file, "打开配置…", delegate { OpenConfig(); }, Keys.Control | Keys.O);
            AddMenu(file, "保存配置…", delegate { SaveConfig(); }, Keys.Control | Keys.S);
            file.DropDownItems.Add(new ToolStripSeparator()); AddMenu(file, "导出窗口截图…", delegate { ExportScreenshot(); }, Keys.None);
            file.DropDownItems.Add(new ToolStripSeparator()); AddMenu(file, "退出", delegate { Close(); }, Keys.Alt | Keys.F4);
            ToolStripMenuItem edit = new ToolStripMenuItem("编辑(&E)"); AddMenu(edit, "场景参数…", delegate { ShowConfiguration(); }, Keys.None); AddMenu(edit, "选择下一项任务", delegate { SelectNext(); }, Keys.None);
            ToolStripMenuItem view = new ToolStripMenuItem("视图(&V)");
            AddMenu(view, "封控区视图", delegate { SetFullView(false); }, Keys.Control | Keys.D1);
            AddMenu(view, "全程视图（集结 → 占位）", delegate { SetFullView(true); }, Keys.Control | Keys.D2);
            view.DropDownItems.Add(new ToolStripSeparator());
            AddMenu(view, "适应窗口", delegate { FitMap(); }, Keys.Control | Keys.D0); AddMenu(view, "放大", delegate { Canvas.Zoom = Math.Min(3.2f, Canvas.Zoom * 1.2f); Canvas.Invalidate(); }, Keys.None); AddMenu(view, "缩小", delegate { Canvas.Zoom = Math.Max(.6f, Canvas.Zoom / 1.2f); Canvas.Invalidate(); }, Keys.None); view.DropDownItems.Add(new ToolStripSeparator());
            AddMenu(view, "恢复默认布局", delegate { ResetLayout(); }, Keys.None);
            ToolStripMenuItem plan = new ToolStripMenuItem("规划(&P)"); AddMenu(plan, "检查示例输入", delegate { CheckInput(); }, Keys.F6); AddMenu(plan, "生成示例记录", delegate { GenerateDemo(); }, Keys.F7);
            ToolStripMenuItem simulation = new ToolStripMenuItem("回放(&R)"); AddMenu(simulation, "播放 / 暂停", delegate { SetPlaying(!timer.Enabled); }, Keys.F5); AddMenu(simulation, "返回开始", delegate { SetPlaying(false); SetTime(0); }, Keys.None); AddMenu(simulation, "跳至结束", delegate { SetPlaying(false); SetTime(PlaybackEnd); }, Keys.None);
            ToolStripMenuItem tools = new ToolStripMenuItem("工具(&T)"); AddMenu(tools, "运行记录", delegate { Documents.SelectedIndex = 3; }, Keys.None); AddMenu(tools, "复制当前任务信息", delegate { CopyTask(); }, Keys.None);
            ToolStripMenuItem help = new ToolStripMenuItem("帮助(&H)"); AddMenu(help, "关于软件原型", delegate { ShowAboutDesktop(); }, Keys.F1);
            menu.Items.AddRange(new ToolStripItem[] { file, edit, view, plan, simulation, tools, help }); return menu;
        }
        private static void AddMenu(ToolStripMenuItem parent, string text, EventHandler handler, Keys key)
        { ToolStripMenuItem item = new ToolStripMenuItem(text); item.Click += handler; item.ShortcutKeys = key; parent.DropDownItems.Add(item); }
        private ToolStripButton ToolButton(string text, string icon, EventHandler handler, bool primary)
        {
            ToolStripButton b = new ToolStripButton(text, DrawIcon(icon)) { DisplayStyle = ToolStripItemDisplayStyle.ImageAndText, Padding = new Padding(6, 6, 6, 6), Margin = new Padding(2, 1, 2, 1), ForeColor = primary ? Blue : ForeColor };
            b.Click += handler; return b;
        }
        private Image DrawIcon(string name)
        {
            Bitmap bitmap = new Bitmap(20, 20); using (Graphics g = Graphics.FromImage(bitmap))
            { g.SmoothingMode = SmoothingMode.AntiAlias; using (Pen pen = new Pen(Blue, 1.6f))
                {
                    if (name == "file") { g.DrawRectangle(pen, 4, 2, 12, 16); g.DrawLine(pen, 7, 7, 13, 7); g.DrawLine(pen, 7, 11, 13, 11); }
                    else if (name == "folder") { g.DrawLines(pen, new Point[] { new Point(2, 16), new Point(2, 5), new Point(8, 5), new Point(10, 7), new Point(18, 7), new Point(17, 16), new Point(2, 16) }); }
                    else if (name == "save") { g.DrawRectangle(pen, 3, 3, 14, 14); g.DrawRectangle(pen, 6, 3, 8, 5); g.DrawRectangle(pen, 6, 11, 8, 6); }
                    else if (name == "check") { g.DrawEllipse(pen, 2, 2, 16, 16); g.DrawLines(pen, new Point[] { new Point(5, 10), new Point(9, 14), new Point(15, 6) }); }
                    else if (name == "play") { using (SolidBrush b = new SolidBrush(Blue)) g.FillPolygon(b, new Point[] { new Point(5, 3), new Point(17, 10), new Point(5, 17) }); }
                    else if (name == "map") { g.DrawRectangle(pen, 2, 3, 16, 14); g.DrawLine(pen, 7, 3, 7, 17); g.DrawLine(pen, 13, 3, 13, 17); }
                    else if (name == "gear") { g.DrawEllipse(pen, 3, 3, 14, 14); g.DrawEllipse(pen, 7, 7, 6, 6); g.DrawLine(pen, 10, 0, 10, 4); g.DrawLine(pen, 10, 16, 10, 20); g.DrawLine(pen, 0, 10, 4, 10); g.DrawLine(pen, 16, 10, 20, 10); }
                    else { g.DrawRectangle(pen, 3, 3, 14, 14); g.DrawLine(pen, 6, 8, 14, 8); g.DrawLine(pen, 6, 12, 14, 12); }
                }
            } return bitmap;
        }
        private void BuildWindow()
        {
            MenuStrip menu = BuildMenus(); MainMenuStrip = menu;
            ToolStrip toolbar = new ToolStrip { GripStyle = ToolStripGripStyle.Hidden, BackColor = Color.FromArgb(248, 250, 253), AutoSize = false, Height = 44, Padding = new Padding(8, 0, 0, 0), Renderer = new ToolStripProfessionalRenderer(new BlueColors()) };
            toolbar.Items.Add(ToolButton("新建", "file", delegate { ShowConfiguration(); }, false)); toolbar.Items.Add(ToolButton("打开", "folder", delegate { OpenConfig(); }, false)); toolbar.Items.Add(ToolButton("保存", "save", delegate { SaveConfig(); }, false)); toolbar.Items.Add(new ToolStripSeparator());
            toolbar.Items.Add(ToolButton("场景参数", "gear", delegate { ShowConfiguration(); }, false)); toolbar.Items.Add(ToolButton("检查输入", "check", delegate { CheckInput(); }, false)); toolbar.Items.Add(ToolButton("生成示例", "play", delegate { GenerateDemo(); }, true)); toolbar.Items.Add(new ToolStripSeparator()); toolbar.Items.Add(ToolButton("适应窗口", "map", delegate { FitMap(); }, false)); toolbar.Items.Add(ToolButton("运行记录", "list", delegate { Documents.SelectedIndex = 3; }, false)); AugmentDesktopToolbar(toolbar);
            ToolStripLabel source = new ToolStripLabel("本地可视化演示  |  后端连接中") { Name = "desktopSourceLabel", Alignment = ToolStripItemAlignment.Right, ForeColor = Color.FromArgb(112, 133, 156), Padding = new Padding(10, 0, 10, 0) }; toolbar.Items.Add(source);
            StatusStrip statusbar = new StatusStrip { BackColor = Color.FromArgb(239, 246, 253), SizingGrip = true, Padding = new Padding(8, 0, 16, 0), Height = 25 };
            status = new ToolStripStatusLabel("就绪") { Spring = true, TextAlign = ContentAlignment.MiddleLeft };
            statusbar.Items.Add(status); statusbar.Items.Add(new ToolStripStatusLabel("本地演示 · 后端连接中") { Name = "desktopBackendStatus", BorderSides = ToolStripStatusLabelBorderSides.Left, Padding = new Padding(10, 0, 10, 0) });
            timeStatus = new ToolStripStatusLabel("回放 106.0 s / 210.0 s") { BorderSides = ToolStripStatusLabelBorderSides.Left, Padding = new Padding(10, 0, 10, 0) }; statusbar.Items.Add(timeStatus);
            leftSplit = NewSplit(Orientation.Vertical, 225); leftSplit.FixedPanel = FixedPanel.Panel1;
            rightSplit = NewSplit(Orientation.Vertical, 860); rightSplit.FixedPanel = FixedPanel.Panel2;
            bottomSplit = NewSplit(Orientation.Horizontal, 550); bottomSplit.FixedPanel = FixedPanel.Panel2;
            leftSplit.Panel1.Controls.Add(BuildExplorer()); leftSplit.Panel2.Controls.Add(rightSplit);
            rightSplit.Panel1.Controls.Add(bottomSplit); rightSplit.Panel2.Controls.Add(BuildProperties());
            Documents = new TabControl { Dock = DockStyle.Fill, Padding = new Point(17, 7), Font = Font };
            TabPage scene = NewTab("场景视图"); Canvas = new SceneCanvas(this); scene.Controls.Add(Canvas);
            Panel sceneToolbar = new Panel { Dock = DockStyle.Top, Height = 35, BackColor = Color.FromArgb(248, 251, 254) };
            sceneInfo = new Label { Text = "场景布局示意 · T-SEC 小十字路口    |    真实运行数据请在“任务视图”查看", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(10, 0, 0, 0), ForeColor = Color.FromArgb(83, 108, 138), Font = new Font(Font.FontFamily, 8.5f) };
            sceneToolbar.Controls.Add(sceneInfo); scene.Controls.Add(sceneToolbar); scene.Controls.Add(BuildPlayback());
            TabPage tasksTab = NewTab("任务列表"); taskGrid = NewGrid(); taskGrid.Columns.Add("id", "席位编号"); taskGrid.Columns.Add("name", "席位名称"); taskGrid.Columns.Add("type", "职责"); taskGrid.Columns.Add("phase", "当前阶段"); taskGrid.Columns.Add("members", "分配平台"); taskGrid.Columns.Add("time", "计划时间段");
            foreach (DemoTask t in Tasks) taskGrid.Rows.Add(t.Id, t.Name, t.Type, Phase(t), t.Platform, t.Start.ToString("0.0") + " – " + t.End.ToString("0.0") + " s");
            taskGrid.CellDoubleClick += delegate(object s, DataGridViewCellEventArgs e) { if (e.RowIndex >= 0) { SelectTask((string)taskGrid.Rows[e.RowIndex].Cells[0].Value); Documents.SelectedIndex = 0; } }; tasksTab.Controls.Add(taskGrid);
            TabPage platformsTab = NewTab("平台列表"); platformGrid = NewGrid(); foreach (string h in new string[] { "平台编号", "平台型号", "平台类别", "关联席位", "编成续航" }) platformGrid.Columns.Add(h, h);
            string[] ids = { "U1", "U2", "U3", "U4", "U5", "U6" }; string[] models = { "IFV", "IFV", "IFV", "TANK", "TANK", "UAV 侦察" };
            string[] classes = { "UGV 地面", "UGV 地面", "UGV 地面", "UGV 地面", "UGV 地面", "PLANE 空中" }; string[] endurance = { "6.0 h", "6.0 h", "6.0 h", "8.0 h", "8.0 h", "10.0 h" };
            for (int i = 0; i < ids.Length; i++) { string seat = ""; foreach (DemoTask t in Tasks) if (t.Platform == ids[i]) seat = t.Id; platformGrid.Rows.Add(ids[i], models[i], classes[i], seat, endurance[i]); } platformsTab.Controls.Add(platformGrid);
            TabPage historyTab = NewTab("运行记录"); history = new ListView { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true, BorderStyle = BorderStyle.None }; history.Columns.Add("运行名称", 230); history.Columns.Add("场景", 210); history.Columns.Add("数据来源", 150); history.Columns.Add("状态", 120); RefreshHistory(); historyTab.Controls.Add(history);
            Panel historyButtons = new Panel { Dock = DockStyle.Bottom, Height = 48, Padding = new Padding(10, 8, 10, 8), BackColor = Color.FromArgb(247, 250, 253) }; Button replay = StandardButton("打开示例回放", 140); replay.Dock = DockStyle.Left; replay.Click += delegate { Documents.SelectedIndex = 0; SetTime(0); status.Text = "已打开示例回放。所有记录共用示例轨迹，不代表不同实验结果。"; }; historyButtons.Controls.Add(replay); historyTab.Controls.Add(historyButtons);
            Documents.TabPages.AddRange(new TabPage[] { scene, tasksTab, platformsTab, historyTab }); bottomSplit.Panel1.Controls.Add(Documents); bottomSplit.Panel2.Controls.Add(BuildOutput()); AugmentDesktopTabs();
            Controls.Add(leftSplit); Controls.Add(toolbar); Controls.Add(menu); Controls.Add(statusbar);
            Shown += delegate { ResetLayout(); }; Resize += delegate { if (IsHandleCreated && ClientSize.Width > 800 && rightSplit.Width > 400) SetRightWidth(); };
        }
        private SplitContainer NewSplit(Orientation orientation, int distance)
        { SplitContainer s = new SplitContainer { Dock = DockStyle.Fill, Orientation = orientation, BackColor = Color.FromArgb(218, 226, 237), SplitterWidth = 5 }; s.Size = new Size(1400, 800); s.SplitterDistance = distance; s.Panel1.BackColor = Color.White; s.Panel2.BackColor = Color.White; return s; }
        private TabPage NewTab(string text) { return new TabPage(text) { BackColor = Color.White, Padding = new Padding(0), UseVisualStyleBackColor = false }; }
        private Label PanelHeader(string text)
        { return new Label { Text = text, Dock = DockStyle.Top, Height = 32, TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(10, 0, 0, 0), BackColor = Color.FromArgb(232, 241, 252), ForeColor = Color.FromArgb(46, 84, 128), Font = new Font(Font, FontStyle.Bold) }; }
        private Control BuildExplorer()
        {
            Panel panel = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            SplitContainer split = NewSplit(Orientation.Horizontal, 430); split.FixedPanel = FixedPanel.Panel2;
            tree = new TreeView { Dock = DockStyle.Fill, BorderStyle = BorderStyle.None, HideSelection = false, FullRowSelect = true, ShowLines = true, ItemHeight = 29, Indent = 18, ShowNodeToolTips = true };
            ImageList images = new ImageList { ImageSize = new Size(18, 18), ColorDepth = ColorDepth.Depth32Bit }; images.Images.Add(DrawIcon("folder")); images.Images.Add(DrawIcon("file")); images.Images.Add(DrawIcon("map")); images.Images.Add(DrawIcon("list")); tree.ImageList = images;
            TreeNode root = new TreeNode("T1 区域封控 · 小十字路口", 0, 0); TreeNode scene = new TreeNode("场景与环境", 0, 0); scene.Nodes.Add(new TreeNode("小十字路口街区", 2, 2) { Tag = "scene" }); scene.Nodes.Add(new TreeNode("场景参数", 1, 1) { Tag = "config" });
            TreeNode taskNodes = new TreeNode("任务 (6)", 0, 0); foreach (DemoTask t in Tasks) taskNodes.Nodes.Add(new TreeNode(t.Seat + "  " + t.ShortName, 1, 1) { Tag = t.Id, ToolTipText = t.Id + "  " + t.Name });
            TreeNode workerNodes = new TreeNode("平台 (6)", 0, 0); foreach (string id in new string[] { "U1 IFV · 地面", "U2 IFV · 地面", "U3 IFV · 地面", "U4 TANK · 地面", "U5 TANK · 地面", "U6 UAV · 空中" }) workerNodes.Nodes.Add(new TreeNode(id, 1, 1) { Tag = "platforms" });
            root.Nodes.AddRange(new TreeNode[] { scene, taskNodes, workerNodes, new TreeNode("运行记录", 3, 3) { Tag = "history" } }); tree.Nodes.Add(root); root.Expand(); scene.Expand(); taskNodes.Expand();
            tree.AfterSelect += delegate(object s, TreeViewEventArgs e) { string tag = e.Node.Tag as string; if (tag != null && tag.StartsWith("T1-")) SelectTask(tag); else if (tag == "platforms") Documents.SelectedIndex = 2; else if (tag == "history") Documents.SelectedIndex = 3; else if (tag == "scene") Documents.SelectedIndex = 0; };
            tree.NodeMouseDoubleClick += delegate(object s, TreeNodeMouseClickEventArgs e) { if ((string)e.Node.Tag == "config") ShowConfiguration(); };
            split.Panel1.Controls.Add(tree); split.Panel1.Controls.Add(PanelHeader("项目浏览器"));
            CheckedListBox layers = new CheckedListBox { Dock = DockStyle.Fill, BorderStyle = BorderStyle.None, CheckOnClick = true, IntegralHeight = false, Padding = new Padding(7), ItemHeight = 27, Font = new Font(Font.FontFamily, 9f) };
            foreach (string name in new string[] { "建筑轮廓", "封控边界", "席位与平台", "规划路径", "目标接近", "坐标网格" }) layers.Items.Add(name, true);
            layers.ItemCheck += delegate(object s, ItemCheckEventArgs e) { if (Canvas == null) return; bool value = e.NewValue == CheckState.Checked; if (e.Index == 0) Canvas.ShowBuildings = value; if (e.Index == 1) Canvas.ShowBoundary = value; if (e.Index == 2) Canvas.ShowUnits = value; if (e.Index == 3) Canvas.ShowRoutes = value; if (e.Index == 4) Canvas.ShowTargets = value; if (e.Index == 5) Canvas.ShowGrid = value; Canvas.Invalidate(); };
            split.Panel2.Controls.Add(layers); split.Panel2.Controls.Add(PanelHeader("图层")); panel.Controls.Add(split);
            split.SizeChanged += delegate { if (split.Height > 300) split.SplitterDistance = Math.Max(200, split.Height - 190); }; return panel;
        }
        private Control BuildProperties()
        {
            Panel panel = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            properties = new PropertyGrid { Dock = DockStyle.Fill, ToolbarVisible = false, HelpVisible = true, HelpBackColor = Color.FromArgb(249, 251, 254), ViewBackColor = Color.White, ViewForeColor = ForeColor, LineColor = Color.FromArgb(231, 236, 242), CategoryForeColor = Color.FromArgb(63, 89, 121), PropertySort = PropertySort.Categorized, BackColor = Color.White, CommandsBackColor = Color.White, HelpBorderColor = Color.FromArgb(224, 231, 240) };
            selectedTitle = new Label { Text = "T1-S3  通道哨位 G-A", Dock = DockStyle.Top, Height = 45, Padding = new Padding(11, 0, 0, 0), TextAlign = ContentAlignment.MiddleLeft, Font = new Font(Font.FontFamily, 10f, FontStyle.Bold), ForeColor = Blue };
            Panel progressPanel = new Panel { Dock = DockStyle.Bottom, Height = 80, Padding = new Padding(12, 9, 12, 10), BackColor = Color.FromArgb(249, 251, 254) };
            Label label = new Label { Text = "当前席位进度（示例）", Dock = DockStyle.Top, Height = 26, ForeColor = Color.FromArgb(100, 121, 146), Font = new Font(Font.FontFamily, 8.5f) };
            taskProgress = new ProgressBar { Dock = DockStyle.Top, Height = 14, Style = ProgressBarStyle.Continuous, ForeColor = Blue };
            progressPanel.Controls.Add(taskProgress); progressPanel.Controls.Add(label); panel.Controls.Add(properties); panel.Controls.Add(selectedTitle); panel.Controls.Add(PanelHeader("属性")); panel.Controls.Add(progressPanel); return panel;
        }
        private Control BuildPlayback()
        {
            Panel panel = new Panel { Dock = DockStyle.Bottom, Height = 91, BackColor = Color.FromArgb(249, 251, 254), Padding = new Padding(10, 6, 10, 4) };
            TableLayoutPanel layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 }; layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            FlowLayoutPanel row = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false, Padding = new Padding(0), FlowDirection = FlowDirection.LeftToRight };
            play = StandardButton("▶ 播放", 82); play.BackColor = Blue; play.ForeColor = Color.White; play.FlatAppearance.BorderColor = Blue; play.Click += delegate { SetPlaying(!timer.Enabled); };
            Button restart = StandardButton("返回开始", 80); restart.Click += delegate { SetPlaying(false); SetTime(0); };
            Button step = StandardButton("前进 5 秒", 85); step.Click += delegate { SetPlaying(false); SetTime(Math.Min(PlaybackEnd, Time + 5)); };
            clock = new Label { AutoSize = false, Width = 145, Height = 28, TextAlign = ContentAlignment.MiddleCenter, ForeColor = Color.FromArgb(73, 101, 137) };
            ComboBox speed = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 62, Margin = new Padding(8, 3, 0, 0) }; speed.Items.AddRange(new object[] { "0.5×", "1×", "2×", "4×", "8×" }); speed.SelectedIndex = 1; speed.SelectedIndexChanged += delegate { PlaybackSpeed = new double[] { .5, 1, 2, 4, 8 }[speed.SelectedIndex]; };
            row.Controls.AddRange(new Control[] { play, restart, step, clock, speed });
            timeline = new TrackBar { Dock = DockStyle.Fill, Minimum = 0, Maximum = (int)(PlaybackEnd * 10), TickFrequency = 150, SmallChange = 10, LargeChange = 100, AutoSize = false, Height = 35, BackColor = panel.BackColor };
            timeline.Scroll += delegate { if (!refreshing) { SetPlaying(false); SetTime(timeline.Value / 10.0); } };
            layout.Controls.Add(row, 0, 0); layout.Controls.Add(timeline, 0, 1); panel.Controls.Add(layout); return panel;
        }
        public static Button StandardButton(string text, int width)
        { return new Button { Text = text, Width = width, Height = 28, Margin = new Padding(0, 1, 7, 1), BackColor = Color.White, FlatStyle = FlatStyle.Flat, ForeColor = Color.FromArgb(61, 82, 110), UseVisualStyleBackColor = false, FlatAppearance = { BorderColor = Color.FromArgb(198, 212, 229) } }; }
        private DataGridView NewGrid()
        {
            DataGridView g = new DataGridView { Dock = DockStyle.Fill, BackgroundColor = Color.White, BorderStyle = BorderStyle.None, AllowUserToAddRows = false, AllowUserToDeleteRows = false, ReadOnly = true, RowHeadersVisible = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill, SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false, EnableHeadersVisualStyles = false, GridColor = Color.FromArgb(229, 235, 243), CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal, ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.Single, ColumnHeadersHeight = 35 };
            g.ColumnHeadersDefaultCellStyle = new DataGridViewCellStyle { BackColor = Color.FromArgb(237, 244, 252), ForeColor = Color.FromArgb(74, 103, 139), Font = Font, Padding = new Padding(6, 0, 0, 0), SelectionBackColor = Color.FromArgb(237, 244, 252) };
            g.DefaultCellStyle = new DataGridViewCellStyle { Font = Font, ForeColor = Color.FromArgb(70, 89, 112), BackColor = Color.White, SelectionBackColor = Color.FromArgb(220, 236, 253), SelectionForeColor = Color.FromArgb(31, 94, 163), Padding = new Padding(6, 0, 0, 0) }; g.RowTemplate.Height = 34; return g;
        }
        private Control BuildOutput()
        {
            TabControl tabs = new TabControl { Dock = DockStyle.Fill, Padding = new Point(13, 5) }; TabPage logs = NewTab("运行日志"), messages = NewTab("消息列表"), output = NewTab("输出文件");
            log = new TextBox { Dock = DockStyle.Fill, BorderStyle = BorderStyle.None, ReadOnly = true, Multiline = true, ScrollBars = ScrollBars.Vertical, BackColor = Color.White, ForeColor = Color.FromArgb(83, 108, 138), Font = new Font("Consolas", 9f) };
            log.Text = "[00:00.0]  INFO   示例场景已载入：区域封控 · T-SEC（小十字路口街区）\r\n[00:00.0]  INFO   T1 封控区 60×60 m；6 台平台自编成表出生位出发\r\n[00:19.5]  INFO   U1 到达 G-A 通道哨位（T1-S3）\r\n[00:23.5]  INFO   6 席全部到位，control_established（示例）\r\n[00:45.0]  WARN   IN-1 未授权目标接近 G-A\r\n[00:50.0]  NOTE   发出警告，IN-1 未撤离\r\n[00:54.0]  INFO   机动组 U3 前出拦阻，IN-1 已拦阻（示例）\r\n[01:10.0]  INFO   IN-2 警告后撤离\r\n[01:40.0]  INFO   AU-1 已授权目标经 G-A 放行（示例）\r\n"; logs.Controls.Add(log);
            DataGridView grid = NewGrid(); grid.Columns.Add("time", "示例时刻"); grid.Columns.Add("level", "级别"); grid.Columns.Add("object", "关联对象"); grid.Columns.Add("message", "消息");
            grid.Rows.Add("45.0 s", "警告", "T1-S3 · U1", "IN-1 未授权接近 G-A，发出警告");
            grid.Rows.Add("70.0 s", "警告", "T1-S4 · U2", "IN-2 未授权接近 G-B，警告后撤离");
            grid.Rows.Add("100.0 s", "信息", "T1-S3 · U1", "AU-1 已授权目标经 G-A 放行");
            grid.CellDoubleClick += delegate(object s, DataGridViewCellEventArgs e) { if (e.RowIndex >= 0) { SetPlaying(false); SetTime(new double[] { 45, 70, 100 }[e.RowIndex]); SelectTask(new string[] { "T1-S3", "T1-S4", "T1-S3" }[e.RowIndex]); } }; messages.Controls.Add(grid);
            Label outputText = new Label { Dock = DockStyle.Fill, Text = "本地可视化演示版。\r\n\r\n真实运行产物由本机规划后端生成，保存在 planning_middle_demo/outputs；\r\n可在“运行记录”中重新载入，或从“任务视图”查看真实回放。\r\n真实平台展示目标为 Gazebo / UE5，本软件不代表真实平台联调完成。", Padding = new Padding(14), ForeColor = Color.FromArgb(111, 132, 155) }; output.Controls.Add(outputText);
            tabs.TabPages.AddRange(new TabPage[] { logs, messages, output }); return tabs;
        }
        public void SelectTask(string id)
        {
            DemoTask found = Tasks.Find(delegate(DemoTask t) { return t.Id == id; }); if (found == null) return; SelectedId = id; RefreshProperties();
            if (Canvas != null) Canvas.Invalidate(); if (tree != null) SelectTreeNode(tree.Nodes, id);
            if (taskGrid != null) { foreach (DataGridViewRow row in taskGrid.Rows) { row.Selected = (string)row.Cells[0].Value == id; if (row.Selected) taskGrid.CurrentCell = row.Cells[0]; } }
            if (status != null) status.Text = "已选择 " + found.Id + " · " + found.Name;
        }
        private void SelectTreeNode(TreeNodeCollection nodes, string id)
        { foreach (TreeNode n in nodes) { if ((n.Tag as string) == id) { if (tree.SelectedNode != n) tree.SelectedNode = n; return; } SelectTreeNode(n.Nodes, id); } }
        public string Phase(DemoTask t)
        {
            if (Time < t.Start) return "待开始";
            if (Time < t.Start + t.Travel) return "机动中";
            if (Time < t.End)
            {
                if (t.Type == "空中监视") return "空中盘旋";
                if (t.Type == "机动拦截") return "机动待机";
                return "在位封控";
            }
            return "已结束";
        }
        private int Progress(DemoTask t) { return (int)Math.Max(0, Math.Min(100, (Time - t.Start) / (t.End - t.Start) * 100)); }
        private void RefreshProperties()
        {
            DemoTask t = Tasks.Find(delegate(DemoTask item) { return item.Id == SelectedId; }); if (t == null || properties == null) return;
            selectedTitle.Text = t.Id + "  " + t.Name;
            properties.SelectedObject = new TaskProperties
            {
                Id = t.Id, Name = t.Name, Type = t.Type, Area = "T1 · " + t.Area,
                Start = t.Start.ToString("0.0") + " s", End = t.End.ToString("0.0") + " s", Travel = t.Travel.ToString("0.0") + " s",
                Members = t.Platform, Position = "(" + t.Position.X.ToString("0.0") + ", " + t.Position.Y.ToString("0.0") + ")",
                Phase = Phase(t), Progress = Progress(t) + "%", Source = "界面原型合成数据"
            };
            taskProgress.Value = Progress(t);
        }
        public void SetTime(double time) { Time = Math.Max(0, Math.Min(PlaybackEnd, time)); RefreshPlayback(); }
        private void RefreshPlayback()
        {
            refreshing = true; timeline.Value = (int)Math.Round(Time * 10); refreshing = false; clock.Text = string.Format("{0:0.0} / 210.0 s", Time); timeStatus.Text = "回放 " + clock.Text;
            for (int i = 0; i < Tasks.Count && taskGrid != null && i < taskGrid.Rows.Count; i++) taskGrid.Rows[i].Cells[3].Value = Phase(Tasks[i]); RefreshProperties(); Canvas.Invalidate();
        }
        private void SetPlaying(bool enabled) { if (enabled && Time >= PlaybackEnd) SetTime(0); timer.Enabled = enabled; play.Text = enabled ? "Ⅱ 暂停" : "▶ 播放"; status.Text = enabled ? "正在播放示例记录；不控制后台运行" : "回放已暂停"; }
        private void SetFullView(bool full) { Canvas.FullView = full; Canvas.Zoom = 1f; Canvas.Pan = PointF.Empty; Canvas.Invalidate(); status.Text = full ? "全程视图：编成表出生位 → 各占位点（示例规划路径）" : "封控区视图：T1 小十字路口 60×60 m 街区"; }
        private void SelectNext() { int i = Tasks.FindIndex(delegate(DemoTask t) { return t.Id == SelectedId; }); SelectTask(Tasks[(i + 1) % Tasks.Count].Id); }
        private void FitMap() { Canvas.FullView = false; Canvas.Zoom = 1; Canvas.Pan = PointF.Empty; Canvas.Invalidate(); }
        private void SetRightWidth() { if (rightSplit.Width > 650) rightSplit.SplitterDistance = rightSplit.Width - 291; }
        private void ResetLayout() { if (leftSplit.Width > 700) leftSplit.SplitterDistance = 225; SetRightWidth(); if (bottomSplit.Height > 400) bottomSplit.SplitterDistance = bottomSplit.Height - 181; if (Canvas != null) FitMap(); }
        private void CheckInput() { MessageBox.Show(this, "原型基础检查通过。\n\n场景：" + scenarioName + "\n封控区：T1 · 60 × 60 m\n示例席位：6 席（2 边界段 / 2 通道哨位 / 1 机动拦截 / 1 空中监视）\n示例平台：6 台（5 地面 + 1 空中）\n\n仅检查原型配置，不代表正式接口、规划可行性或算法效果已验证。", "检查输入", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        private void GenerateDemo()
        {
            DialogResult result = MessageBox.Show(this, "生成一条新的界面示例记录？\n\n该操作仅复制当前原型参数并装载预置轨迹，不调用项目规划器。", "生成示例", MessageBoxButtons.OKCancel, MessageBoxIcon.Information);
            if (result != DialogResult.OK) return; records.Insert(0, "T-SEC 街区封控 " + (records.Count + 1).ToString("000")); RefreshHistory(); SetPlaying(false); SetTime(0); Documents.SelectedIndex = 0; log.AppendText("[界面操作] 已新增示例记录，使用预置示例轨迹。\n"); status.Text = "示例记录已生成。可点击播放查看界面效果。";
        }
        private void RefreshHistory() { if (history == null) return; history.Items.Clear(); foreach (string name in records) { ListViewItem item = new ListViewItem(new string[] { name, scenarioName, "界面合成示例", "示例已结束" }); history.Items.Add(item); } }
        private void CopyTask() { DemoTask t = Tasks.Find(delegate(DemoTask item) { return item.Id == SelectedId; }); if (t == null) return; try { Clipboard.SetText(t.Id + " " + t.Name + "\r\n分配平台：" + t.Platform + "\r\n占位点：(" + t.Position.X + ", " + t.Position.Y + ")\r\n来源：界面原型示例"); status.Text = "席位信息已复制。"; } catch (ExternalException) { status.Text = "剪贴板正在被占用，请稍后再试。"; } }
        private void ShowConfiguration(string capturePath = null)
        {
            using (Form dialog = new Form { Text = "场景参数", Size = new Size(530, 400), StartPosition = FormStartPosition.CenterParent, Font = Font, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false, BackColor = Color.White })
            {
                TableLayoutPanel table = new TableLayoutPanel { Dock = DockStyle.Top, Padding = new Padding(22, 18, 22, 5), Height = 260, ColumnCount = 2, RowCount = 5 }; table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110)); table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
                TextBox name = new TextBox { Text = scenarioName, Dock = DockStyle.Fill, MaxLength = 80 }; ComboBox target = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill }; target.Items.AddRange(new object[] { "时效优先", "能耗优先", "均衡目标" }); target.SelectedItem = objective;
                NumericUpDown random = new NumericUpDown { Minimum = 0, Maximum = 100000, Value = seed, Dock = DockStyle.Fill };
                Control[] controls = { name, target, random, new Label { Text = "6 席任务 / 6 台平台", AutoSize = true }, new Label { Text = "本地示例数据（未连接后端）", AutoSize = true, ForeColor = Blue } };
                string[] labels = { "场景名称", "规划目标", "随机种子", "输入概况", "数据来源" };
                for (int i = 0; i < 5; i++) { table.RowStyles.Add(new RowStyle(SizeType.Absolute, 43)); table.Controls.Add(new Label { Text = labels[i], AutoSize = true, Margin = new Padding(0, 6, 0, 0) }, 0, i); controls[i].Margin = new Padding(0, 4, 0, 0); table.Controls.Add(controls[i], 1, i); }
                Label note = new Label { Text = "参数用于展示配置流程；不会改变预置路径或计算算法效果。", Dock = DockStyle.Top, Height = 40, Padding = new Padding(22, 5, 15, 0), ForeColor = Color.FromArgb(116, 134, 155), Font = new Font(Font.FontFamily, 8.5f) };
                FlowLayoutPanel buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 51, BackColor = Color.FromArgb(246, 249, 253), Padding = new Padding(10, 10, 12, 10), FlowDirection = FlowDirection.RightToLeft };
                Button cancel = StandardButton("取消", 78); cancel.DialogResult = DialogResult.Cancel; Button ok = StandardButton("确定", 78); ok.BackColor = Blue; ok.ForeColor = Color.White;
                ok.Click += delegate { if (string.IsNullOrWhiteSpace(name.Text)) { MessageBox.Show(dialog, "请输入场景名称。", "参数检查"); return; } scenarioName = name.Text.Trim(); objective = target.Text; seed = random.Value; UpdateSceneName(); dialog.DialogResult = DialogResult.OK; };
                buttons.Controls.Add(cancel); buttons.Controls.Add(ok); dialog.Controls.Add(note); dialog.Controls.Add(table); dialog.Controls.Add(buttons); dialog.AcceptButton = ok; dialog.CancelButton = cancel;
                if (capturePath == null) dialog.ShowDialog(this);
                else { dialog.StartPosition = FormStartPosition.Manual; dialog.Location = new Point(-16000, -16000); dialog.ShowInTaskbar = false; dialog.Show(); Application.DoEvents(); using (Bitmap bmp = new Bitmap(dialog.Width, dialog.Height)) { dialog.DrawToBitmap(bmp, new Rectangle(0, 0, dialog.Width, dialog.Height)); bmp.Save(capturePath, ImageFormat.Png); } dialog.Close(); }
            }
        }
        private void UpdateSceneName() { Text = "多智能体协同规划系统 — " + scenarioName; tree.Nodes[0].Text = scenarioName; sceneInfo.Text = scenarioName + "   |   任务 6 席   平台 6 台"; status.Text = "已更新原型场景参数。历史示例不作为真实实验记录。"; }
        private void SaveConfig()
        {
            using (SaveFileDialog d = new SaveFileDialog { Title = "保存原型配置", Filter = "原型配置 (*.marlpreview)|*.marlpreview", FileName = "区域封控_小十字路口.marlpreview" })
            { if (d.ShowDialog(this) != DialogResult.OK) return; try { File.WriteAllLines(d.FileName, new string[] { "MARL_DESKTOP_PREVIEW_V1", scenarioName, objective, seed.ToString(System.Globalization.CultureInfo.InvariantCulture), "SYNTHETIC_DATA_ONLY" }, new UTF8Encoding(false)); status.Text = "原型配置已保存：" + d.FileName; } catch (Exception ex) { MessageBox.Show(this, ex.Message, "保存失败", MessageBoxButtons.OK, MessageBoxIcon.Error); } }
        }
        private void OpenConfig()
        {
            using (OpenFileDialog d = new OpenFileDialog { Title = "打开原型配置", Filter = "原型配置 (*.marlpreview)|*.marlpreview" })
            { if (d.ShowDialog(this) != DialogResult.OK) return; try { string[] values = File.ReadAllLines(d.FileName, Encoding.UTF8); decimal parsed; if (values.Length != 5 || values[0] != "MARL_DESKTOP_PREVIEW_V1" || values[4] != "SYNTHETIC_DATA_ONLY" || string.IsNullOrWhiteSpace(values[1]) || values[1].Length > 80 || Array.IndexOf(new string[] { "时效优先", "能耗优先", "均衡目标" }, values[2]) < 0 || !decimal.TryParse(values[3], System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out parsed) || parsed < 0 || parsed > 100000) throw new InvalidDataException("不是有效的原型配置文件。正式项目 JSON 不能作为此原型配置打开。"); scenarioName = values[1]; objective = values[2]; seed = parsed; UpdateSceneName(); } catch (Exception ex) { MessageBox.Show(this, ex.Message, "打开失败", MessageBoxButtons.OK, MessageBoxIcon.Error); } }
        }
        private void ExportScreenshot() { using (SaveFileDialog d = new SaveFileDialog { Title = "导出窗口截图", Filter = "PNG 图像 (*.png)|*.png", FileName = "软件界面.png" }) { if (d.ShowDialog(this) != DialogResult.OK) return; try { SaveScreenshot(d.FileName); status.Text = "窗口截图已导出。"; } catch (Exception ex) { MessageBox.Show(this, ex.Message, "导出失败"); } } }
        public void SaveScreenshot(string path) { using (Bitmap bitmap = new Bitmap(Width, Height)) { DrawToBitmap(bitmap, new Rectangle(0, 0, Width, Height)); bitmap.Save(path, ImageFormat.Png); } }
        public void VerifyAndCapture(string directory)
        {
            Directory.CreateDirectory(directory); List<string> checks = new List<string>();
            Action<bool, string> check = delegate(bool passed, string label) { if (!passed) throw new InvalidOperationException(label); checks.Add(label); };
            check(Documents.TabPages.Count == 5, "Five native document tabs including task view"); check(taskGrid.Rows.Count >= 1, "Task table populated"); check(platformGrid.Rows.Count >= 1, "Platform table populated");
            SelectTask("T1-S3"); check(properties.SelectedObject is TaskProperties, "Seat selection updates native property grid");
            SetTime(0); check(Phase(Tasks[0]) == "待开始" && Phase(Tasks[5]) == "待开始", "Beginning replay states");
            SetTime(210); check(Tasks.TrueForAll(delegate(DemoTask t) { return Phase(t) == "已结束"; }), "End replay states");
            SetTime(106); SelectTask("T1-S3"); check(taskProgress.Value >= 0, "Progress matches selected replay time");
            Canvas.ShowBoundary = false; Canvas.Invalidate(); check(!Canvas.ShowBoundary, "Layer visibility toggles"); Canvas.ShowBoundary = true;
            SetPlaying(true); check(timer.Enabled && play.Text.Contains("暂停"), "Playback button starts timer"); SetPlaying(false); check(!timer.Enabled, "Playback button pauses timer");
            ShowConfiguration(Path.Combine(directory, "configuration.png"));
            Documents.SelectedIndex = 1; Application.DoEvents(); SaveScreenshot(Path.Combine(directory, "tasks.png"));
            Documents.SelectedIndex = 0; Size = new Size(1500, 940); ResetLayout(); Application.DoEvents(); SaveScreenshot(Path.Combine(directory, "preview.png"));
            check(timeline.PointToScreen(Point.Empty).Y + timeline.Height < PointToScreen(new Point(0, ClientSize.Height)).Y, "Playback visible in native window");
            Size = new Size(1180, 780); ResetLayout(); Application.DoEvents(); SaveScreenshot(Path.Combine(directory, "preview-1180.png"));
            check(Canvas.Width > 400 && properties.Width >= 260, "Resizable compact desktop layout");
            Size = new Size(1500, 940); ResetLayout(); Documents.SelectedIndex = 0; Application.DoEvents();
            File.WriteAllLines(Path.Combine(directory, "verification.txt"), checks.ToArray(), new UTF8Encoding(false));
        }
    }
    public sealed class BlueColors : ProfessionalColorTable
    {
        public override Color ToolStripGradientBegin { get { return Color.FromArgb(248, 250, 253); } }
        public override Color ToolStripGradientMiddle { get { return Color.FromArgb(248, 250, 253); } }
        public override Color ToolStripGradientEnd { get { return Color.FromArgb(248, 250, 253); } }
        public override Color MenuItemSelected { get { return Color.FromArgb(222, 237, 253); } }
        public override Color MenuItemBorder { get { return Color.FromArgb(157, 193, 232); } }
        public override Color ButtonSelectedGradientBegin { get { return Color.FromArgb(228, 240, 254); } }
        public override Color ButtonSelectedGradientEnd { get { return Color.FromArgb(228, 240, 254); } }
        public override Color ImageMarginGradientBegin { get { return Color.FromArgb(248, 250, 253); } }
        public override Color ImageMarginGradientMiddle { get { return Color.FromArgb(248, 250, 253); } }
        public override Color ImageMarginGradientEnd { get { return Color.FromArgb(248, 250, 253); } }
    }
    internal static class Program
    {
        private static Timer liveVerifyTimer;

        public static void DesktopTrace(string message)
        {
            try
            {
                File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "desktop.log"),
                    DateTime.Now.ToString("HH:mm:ss.fff") + " " + message + "\r\n", Encoding.UTF8);
            }
            catch (Exception) { }
        }

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            DesktopTrace("main args=" + string.Join("|", args));
            if (args.Length == 2 && args[0] == "--verify")
            {
                try
                {
                    using (MainWindow form = new MainWindow()) { form.ShowInTaskbar = false; form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-16000, -16000); form.Show(); Application.DoEvents(); form.VerifyAndCapture(args[1]); form.Close(); } return 0;
                }
                catch (Exception ex) { Directory.CreateDirectory(args[1]); File.WriteAllText(Path.Combine(args[1], "verification-error.txt"), ex.ToString()); return 1; }
            }
            if (args.Length == 2 && args[0] == "--live-verify")
            {
                try
                {
                    using (MainWindow form = new MainWindow())
                    {
                        form.StartPosition = FormStartPosition.Manual;
                        form.Location = new Point(30, 30);
                        form.Show();
                        int ticks = 0;
                        Timer timer = new Timer { Interval = 1000 };
                        liveVerifyTimer = timer;
                        timer.Tick += delegate
                        {
                            ticks++;
                            DesktopTrace("live tick " + ticks);
                            if (ticks < 14) return;
                            timer.Stop();
                            try { form.CaptureLiveVerification(args[1]); }
                            catch (Exception ex) { Directory.CreateDirectory(args[1]); File.WriteAllText(Path.Combine(args[1], "live-verification-error.txt"), ex.ToString()); }
                            form.Close();
                        };
                        timer.Start();
                        Application.Run(form);
                    }
                    return 0;
                }
                catch (Exception ex) { Directory.CreateDirectory(args[1]); File.WriteAllText(Path.Combine(args[1], "live-verification-error.txt"), ex.ToString()); return 1; }
            }
            Application.Run(new MainWindow()); return 0;
        }
    }
}
