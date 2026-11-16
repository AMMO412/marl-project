using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace MarlDesktopPreview
{
    public sealed class DesktopRunSummary
    {
        public string Id, Scenario, Mode, Motion, Objective;
        public int Done, Total;
        public bool Behavior, BehaviorDetails;
        public double End;
        public double? Makespan, PlanEnergy, PlanExposure, ExecutionExposure, PlanProbability, ExecutionProbability;
        public int? Retries, Timeouts;
        public string PlanMetricsSource = "", ComparisonScope = "";
        public bool ComparisonComplete;
    }

    public sealed class DesktopCatalog
    {
        public string Version = "";
        public string DefaultRun = "";
        public readonly List<DesktopRunSummary> Runs = new List<DesktopRunSummary>();
        public readonly Dictionary<string, string> Scenarios = new Dictionary<string, string>();
        public readonly List<DesktopMapItem> Maps = new List<DesktopMapItem>();
        public bool ProcessRunning;
        public string ProcessId = "";
        public string ProcessState = "";
    }

    public sealed class DesktopMapItem
    {
        public string Id = "", Label = "";
        public int Buildings, Roads, Obstacles;
    }

    public sealed class DesktopTask
    {
        public string Id = "", Label = "", Type = "", Status = "", StatusAt = "";
        public readonly List<string> Assigned = new List<string>();
        public double[] Position, Window;
        public int Crew;
        public double Progress, Work;
    }

    public sealed class DesktopPlatform
    {
        public string Id = "", Kind = "", Job = "", Phase = "", Status = "";
        public double[] Position;
        public double Z, Yaw;
        public double? Battery;
        public bool Alive = true;
        public bool Participates;
    }

    public sealed class DesktopEvent
    {
        public double Time;
        public string Kind = "", JobId = "", Label = "";
        public object Raw;
    }

    public sealed class DesktopRunView
    {
        public string Id = "";
        public double At, End;
        public string Scenario = "", Objective = "", Mode = "", Motion = "", Status = "", Backend = "", Limits = "";
        public int Done, Total;
        public bool Settled, AllSucceeded, LimitReached;
        public readonly List<DesktopTask> Tasks = new List<DesktopTask>();
        public readonly List<DesktopPlatform> Platforms = new List<DesktopPlatform>();
        public readonly List<DesktopEvent> Events = new List<DesktopEvent>();
        public readonly List<string> Files = new List<string>();

        public DesktopTask FindTask(string id)
        {
            return Tasks.FirstOrDefault(delegate(DesktopTask t) { return t.Id == id; });
        }
    }

    public sealed partial class DesktopApi
    {
        public readonly string BaseUrl;
        private readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };

        public DesktopApi(string baseUrl)
        {
            BaseUrl = baseUrl.TrimEnd('/');
        }

        private string Get(string path)
        {
            using (WebClient client = new NativeHttpClient())
            {
                client.Encoding = Encoding.UTF8;
                client.Headers[HttpRequestHeader.CacheControl] = "no-cache";
                return client.DownloadString(BaseUrl + path);
            }
        }

        private string Post(string path, string body)
        {
            ServicePointManager.Expect100Continue = false;
            using (WebClient client = new NativeHttpClient())
            {
                client.Encoding = Encoding.UTF8;
                client.Headers[HttpRequestHeader.ContentType] = "application/json; charset=utf-8";
                return client.UploadString(BaseUrl + path, "POST", body);
            }
        }

        public DesktopCatalog GetCatalog()
        {
            object raw = json.DeserializeObject(Get("/api/catalog"));
            Dictionary<string, object> root = AsDict(raw);
            DesktopCatalog catalog = new DesktopCatalog();
            catalog.Version = Str(root, "version");
            catalog.DefaultRun = Str(root, "default_run");
            foreach (object item in AsList(Value(root, "runs")))
            {
                Dictionary<string, object> row = AsDict(item);
                DesktopRunSummary run = new DesktopRunSummary();
                run.Id = Str(row, "id");
                run.Scenario = Str(row, "scenario");
                run.Mode = Str(row, "mode");
                run.Motion = Str(row, "motion");
                run.Objective = Str(row, "objective");
                run.Done = Int(row, "done");
                run.Total = Int(row, "total");
                run.End = Dbl(row, "end");
                run.Makespan = OptionalNumber(row, "makespan");
                run.PlanMetricsSource = Str(row, "plan_metrics_source");
                run.ComparisonScope = Str(row, "comparison_scope");
                run.ComparisonComplete = Bool(row, "comparison_complete");
                run.PlanEnergy = OptionalNumber(row, "plan_energy");
                run.PlanExposure = OptionalNumber(row, "exposure");
                run.ExecutionExposure = OptionalNumber(row, "execution_exposure");
                run.PlanProbability = OptionalNumber(row, "detection_probability");
                run.ExecutionProbability = OptionalNumber(row, "execution_detection_probability");
                run.Retries = OptionalNumber(row, "retries").HasValue ? (int?)Int(row, "retries") : null;
                run.Timeouts = OptionalNumber(row, "timeouts").HasValue ? (int?)Int(row, "timeouts") : null;
                run.Behavior = Bool(row, "behavior");
                run.BehaviorDetails = Bool(row, "behavior_details");
                if (run.Id.Length > 0) catalog.Runs.Add(run);
            }
            Dictionary<string, object> scenarios = AsDict(Value(root, "scenarios"));
            foreach (KeyValuePair<string, object> pair in scenarios)
                catalog.Scenarios[pair.Key] = Convert.ToString(pair.Value, CultureInfo.InvariantCulture);
            foreach (object item in AsList(Value(root, "maps")))
            {
                Dictionary<string, object> row = AsDict(item);
                DesktopMapItem map = new DesktopMapItem
                {
                    Id = Str(row, "id"),
                    Label = Str(row, "label"),
                    Buildings = Int(row, "buildings"),
                    Roads = Int(row, "roads"),
                    Obstacles = Int(row, "obstacles")
                };
                if (map.Id.Length > 0) catalog.Maps.Add(map);
            }
            Dictionary<string, object> process = AsDict(Value(root, "process"));
            string state = Str(process, "state");
            catalog.ProcessState = state;
            catalog.ProcessRunning = state == "running";
            catalog.ProcessId = Str(process, "id");
            return catalog;
        }

        public DesktopRunView GetRun(string runId, double? atSeconds)
        {
            string path = "/api/desktop/run/" + Uri.EscapeDataString(runId);
            if (atSeconds.HasValue)
                path += "?t=" + atSeconds.Value.ToString("0.###", CultureInfo.InvariantCulture);
            object raw = json.DeserializeObject(Get(path));
            Dictionary<string, object> root = AsDict(raw);
            Dictionary<string, object> run = AsDict(Value(root, "run"));
            DesktopRunView view = new DesktopRunView();
            view.Id = Str(root, "id");
            view.At = Dbl(root, "at_s");
            view.End = Dbl(root, "end");
            view.Scenario = Str(run, "scenario");
            view.Objective = Str(run, "objective");
            view.Mode = Str(run, "mode");
            view.Motion = Str(run, "motion");
            view.Status = Str(run, "status");
            view.Backend = Str(run, "backend");
            view.Done = Int(run, "done");
            view.Total = Int(run, "total");
            view.Settled = Bool(run, "settled");
            view.AllSucceeded = Bool(run, "all_succeeded");
            view.LimitReached = Bool(run, "limit_reached");
            view.Limits = Str(root, "limits");
            foreach (object item in AsList(Value(root, "tasks")))
            {
                Dictionary<string, object> row = AsDict(item);
                DesktopTask task = new DesktopTask();
                task.Id = Str(row, "id");
                task.Label = Str(row, "label");
                task.Type = Str(row, "type");
                task.Status = Str(row, "status");
                task.StatusAt = Str(row, "status_at");
                task.Position = DblArray(Value(row, "position"));
                task.Window = DblArray(Value(row, "window"));
                task.Crew = Int(row, "crew");
                task.Progress = Dbl(row, "progress");
                task.Work = Dbl(row, "work");
                foreach (object pid in AsList(Value(row, "assigned")))
                    task.Assigned.Add(Convert.ToString(pid, CultureInfo.InvariantCulture));
                view.Tasks.Add(task);
            }
            foreach (object item in AsList(Value(root, "platforms")))
            {
                Dictionary<string, object> row = AsDict(item);
                DesktopPlatform platform = new DesktopPlatform();
                platform.Id = Str(row, "id");
                platform.Kind = Str(row, "kind");
                platform.Job = Str(row, "job");
                platform.Phase = Str(row, "phase");
                platform.Status = Str(row, "status");
                platform.Position = DblArray(Value(row, "position"));
                platform.Z = Dbl(row, "z");
                platform.Yaw = Dbl(row, "yaw");
                platform.Battery = Value(row, "battery") == null ? (double?)null : Dbl(row, "battery");
                platform.Alive = Bool(row, "alive");
                platform.Participates = Bool(row, "participates");
                view.Platforms.Add(platform);
            }
            foreach (object item in AsList(Value(root, "events")))
            {
                Dictionary<string, object> row = AsDict(item);
                DesktopEvent ev = new DesktopEvent();
                ev.Time = Dbl(row, "sim_s");
                ev.Kind = Str(row, "kind");
                ev.JobId = Str(row, "job_id");
                ev.Label = Str(row, "label");
                view.Events.Add(ev);
            }
            foreach (object file in AsList(Value(root, "files"))) view.Files.Add(Convert.ToString(file));
            return view;
        }

        public void StartRun(string scenario, string mode, string objective, int maxTicks)
        {
            Dictionary<string, object> body = new Dictionary<string, object>();
            body["scenario"] = scenario;
            body["mode"] = mode;
            body["motion"] = "real";
            body["avoid"] = true;
            body["behavior"] = true;
            body["max_ticks"] = maxTicks;
            body["objective"] = objective;
            body["effect_kind"] = "damage";
            body["planner"] = "interop";
            Post("/api/runs", json.Serialize(body));
        }

        private static object Value(Dictionary<string, object> dict, string key)
        {
            object value;
            return dict != null && dict.TryGetValue(key, out value) ? value : null;
        }

        private static Dictionary<string, object> AsDict(object value)
        {
            return value as Dictionary<string, object> ?? new Dictionary<string, object>();
        }

        private static List<object> AsList(object value)
        {
            List<object> result = new List<object>();
            IEnumerable seq = value as IEnumerable;
            if (seq == null || value is string) return result;
            foreach (object item in seq) result.Add(item);
            return result;
        }

        private static string Str(Dictionary<string, object> dict, string key)
        {
            object value = Value(dict, key);
            return value == null ? "" : Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        private static int Int(Dictionary<string, object> dict, string key)
        {
            object value = Value(dict, key);
            if (value == null) return 0;
            int parsed;
            return int.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture),
                                NumberStyles.Integer, CultureInfo.InvariantCulture, out parsed) ? parsed : 0;
        }

        private static double Dbl(Dictionary<string, object> dict, string key)
        {
            object value = Value(dict, key);
            return value == null ? 0.0 : Convert.ToDouble(value, CultureInfo.InvariantCulture);
        }

        private static double? OptionalNumber(Dictionary<string, object> dict, string key)
        {
            double value; object raw = Value(dict, key);
            return raw != null && double.TryParse(Convert.ToString(raw, CultureInfo.InvariantCulture),
                NumberStyles.Float, CultureInfo.InvariantCulture, out value) && !double.IsNaN(value) && !double.IsInfinity(value) ? (double?)value : null;
        }

        private static bool Bool(Dictionary<string, object> dict, string key)
        {
            object value = Value(dict, key);
            if (value is bool) return (bool)value;
            bool parsed;
            return bool.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture), out parsed) && parsed;
        }

        private static double[] DblArray(object value)
        {
            List<object> items = AsList(value);
            double[] result = new double[items.Count];
            for (int i = 0; i < items.Count; i++)
                result[i] = Convert.ToDouble(items[i], CultureInfo.InvariantCulture);
            return result;
        }
    }

    public sealed class BackendSupervisor : IDisposable
    {
        private Process process;
        private readonly Action<string> log;
        public string BaseUrl = "";
        public bool Reused;

        public BackendSupervisor(Action<string> logger)
        {
            log = logger ?? delegate { };
        }

        public Task<string> EnsureStartedAsync()
        {
            return Task.Run(delegate
            {
                string existing = FindExisting();
                if (existing != null)
                {
                    Reused = true;
                    BaseUrl = existing;
                    log("已连接现有本地后端：" + existing);
                    return existing;
                }
                string server = FindServer();
                if (server == null) throw new InvalidOperationException("找不到 planning_middle_demo/workbench_server.py。");
                PythonCommand python = FindPython();
                int port = FindFreePort();
                log("启动本地后端：" + python.FileName + " " + server + " --port " + port);
                ProcessStartInfo info = new ProcessStartInfo();
                info.FileName = python.FileName;
                info.Arguments = python.Prefix + " -B \"" + server + "\" --port " + port;
                info.WorkingDirectory = Path.GetDirectoryName(server);
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                info.StandardOutputEncoding = Encoding.UTF8;
                info.StandardErrorEncoding = Encoding.UTF8;
                info.EnvironmentVariables["PYTHONUTF8"] = "1";
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
                string dataRoot = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "data", "runs");
                Directory.CreateDirectory(dataRoot);
                info.EnvironmentVariables["MARL_WORKBENCH_OUTPUTS"] = dataRoot;
                process = new Process();
                process.StartInfo = info;
                process.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
                {
                    if (string.IsNullOrEmpty(e.Data)) return;
                    log(e.Data);
                    AppendBackendLog(e.Data);
                };
                process.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
                {
                    if (string.IsNullOrEmpty(e.Data)) return;
                    log("[stderr] " + e.Data);
                    AppendBackendLog("[stderr] " + e.Data);
                };
                if (!process.Start()) throw new InvalidOperationException("本地后端进程启动失败。");
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                DateTime deadline = DateTime.UtcNow.AddSeconds(25);
                while (DateTime.UtcNow < deadline)
                {
                    if (process.HasExited)
                        throw new InvalidOperationException("本地后端启动后退出，退出码 " + process.ExitCode + "。");
                    string found = FindExisting();
                    if (found != null)
                    {
                        BaseUrl = found;
                        log("本地后端已就绪：" + found);
                        return found;
                    }
                    Thread.Sleep(400);
                }
                throw new TimeoutException("本地后端启动超时（25 秒）。");
            });
        }

        private static string FindExisting()
        {
            for (int port = 8766; port <= 8771; port++)
            {
                try
                {
                    string url = "http://127.0.0.1:" + port;
                    HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url + "/api/catalog");
                    request.Timeout = 700;
                    request.ReadWriteTimeout = 700;
                    using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                    using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                    {
                        string body = reader.ReadToEnd();
                        JavaScriptSerializer json = new JavaScriptSerializer();
                        Dictionary<string, object> root = json.DeserializeObject(body) as Dictionary<string, object>;
                        if (root == null) continue;
                        string service = Convert.ToString(root.ContainsKey("service") ? root["service"] : "");
                        string portableRoot=AppDomain.CurrentDomain.BaseDirectory;
                        if(File.Exists(Path.Combine(portableRoot,"PORTABLE.txt"))) {
                            string expectedApp=Path.GetFullPath(Path.Combine(portableRoot,"app","planning_middle_demo"));
                            string expectedRuns=Path.GetFullPath(Path.Combine(portableRoot,"data","runs"));
                            if(!root.ContainsKey("app_root")||!root.ContainsKey("outputs_root")||
                               !string.Equals(Convert.ToString(root["app_root"]),expectedApp,StringComparison.OrdinalIgnoreCase)||
                               !string.Equals(Convert.ToString(root["outputs_root"]),expectedRuns,StringComparison.OrdinalIgnoreCase))continue;
                        }
                        Dictionary<string, object> features = root.ContainsKey("features") ? root["features"] as Dictionary<string, object> : null;
                        bool bridge = features != null && features.ContainsKey("desktop_bridge")
                                      && Convert.ToBoolean(features["desktop_bridge"]);
                        bool urbanBenchmarks = features != null
                                               && features.ContainsKey("urban_benchmark_scenarios")
                                               && Convert.ToBoolean(features["urban_benchmark_scenarios"]);
                        if (service == "planning-middle-workbench/v1" && bridge
                            && urbanBenchmarks
                            && features.ContainsKey("static_task_editor_v2")
                            && Convert.ToBoolean(features["static_task_editor_v2"])
                            && features.ContainsKey("desktop_workflow")
                            && Convert.ToBoolean(features["desktop_workflow"])
                            && features.ContainsKey("desktop_workflow_version")
                            && Convert.ToInt32(features["desktop_workflow_version"]) >= 17)
                            return url;
                    }
                }
                catch (Exception) { }
            }
            return null;
        }

        private static void AppendBackendLog(string text)
        {
            try
            {
                File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "backend.log"),
                    DateTime.Now.ToString("HH:mm:ss.fff") + " " + text + "\r\n", Encoding.UTF8);
            }
            catch (Exception) { }
        }

        private static int FindFreePort()
        {
            for (int port = 8766; port <= 8771; port++)
            {
                try
                {
                    TcpListener listener = new TcpListener(IPAddress.Loopback, port);
                    listener.Start();
                    listener.Stop();
                    return port;
                }
                catch (SocketException) { }
            }
            throw new InvalidOperationException("8766–8771 端口均被占用。");
        }

        private static string FindServer()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            DirectoryInfo dir = new DirectoryInfo(baseDir);
            for (int i = 0; i < 7 && dir != null; i++)
            {
                string candidate = Path.Combine(dir.FullName, "app", "planning_middle_demo", "workbench_server.py");
                if (File.Exists(candidate)) return candidate;
                candidate = Path.Combine(dir.FullName, "planning_middle_demo", "workbench_server.py");
                if (File.Exists(candidate)) return candidate;
                dir = dir.Parent;
            }
            return null;
        }

        private static PythonCommand FindPython()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string[] local = new string[]
            {
                Path.Combine(baseDir, "runtime", "python.exe"),
                Path.Combine(baseDir, "..", "runtime", "python.exe"),
            };
            foreach (string path in local)
            {
                string full = Path.GetFullPath(path);
                if (File.Exists(full)) return new PythonCommand { FileName = full, Prefix = "" };
            }
            string py = Environment.GetEnvironmentVariable("MARL_PYTHON");
            if (!string.IsNullOrEmpty(py) && File.Exists(py))
                return new PythonCommand { FileName = py, Prefix = "" };
            return new PythonCommand { FileName = "py", Prefix = "-3.14" };
        }

        public void Dispose()
        {
            if (process == null || Reused) return;
            try
            {
                if (!process.HasExited)
                {
                    Process kill = new Process();
                    kill.StartInfo.FileName = "taskkill";
                    kill.StartInfo.Arguments = "/PID " + process.Id + " /T /F";
                    kill.StartInfo.UseShellExecute = false;
                    kill.StartInfo.CreateNoWindow = true;
                    kill.Start();
                    kill.WaitForExit(3000);
                }
            }
            catch (Exception) { }
            try { process.Dispose(); } catch (Exception) { }
            process = null;
        }

        private sealed class PythonCommand
        {
            public string FileName, Prefix;
        }
    }
}
