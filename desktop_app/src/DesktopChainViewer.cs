using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace MarlDesktopPreview
{
    internal sealed class DesktopChainViewer : Form
    {
        private readonly string baseUrl;
        private readonly string runId;
        private readonly WebView2 browser;
        private readonly Label status;
        private WebViewProfileLease profile;

        private DesktopChainViewer(string baseUrl, string runId)
        {
            this.baseUrl = baseUrl.TrimEnd('/');
            this.runId = runId;
            Text = "全链路追溯 · " + runId;
            Font = new Font("Microsoft YaHei UI", 9f);
            BackColor = Color.White;
            Size = new Size(1180, 760);
            MinimumSize = new Size(820, 520);
            StartPosition = FormStartPosition.CenterParent;
            ShowIcon = false;

            status = new Label
            {
                Dock = DockStyle.Top,
                Height = 30,
                Padding = new Padding(9, 6, 9, 3),
                Text = "正在读取本轮实际指令、反馈和动态事件…",
                ForeColor = Color.FromArgb(55, 82, 111),
                BackColor = Color.FromArgb(247, 250, 253)
            };
            browser = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(browser);
            Controls.Add(status);
            Shown += async delegate { await InitializeAsync(); };
            FormClosed += delegate
            {
                try { browser.Dispose(); }
                catch (Exception) { }
                if (profile != null) profile.Dispose();
            };
        }

        internal static void Open(Form owner, string baseUrl, string runId)
        {
            DesktopChainViewer viewer = new DesktopChainViewer(baseUrl, runId);
            viewer.Show(owner);
        }

        private async Task InitializeAsync()
        {
            try
            {
                profile = WebViewProfileLease.Acquire(new HashSet<string>());
                CoreWebView2Environment environment =
                    await CoreWebView2Environment.CreateAsync(null, profile.DirectoryPath, null);
                if (IsDisposed) return;
                await browser.EnsureCoreWebView2Async(environment);
                if (IsDisposed || browser.CoreWebView2 == null) return;
                browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
                browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
                browser.CoreWebView2.NavigationStarting += delegate(
                    object sender, CoreWebView2NavigationStartingEventArgs args)
                {
                    if (!args.Uri.StartsWith(baseUrl + "/", StringComparison.OrdinalIgnoreCase))
                        args.Cancel = true;
                };
                browser.CoreWebView2.NavigationCompleted += delegate(
                    object sender, CoreWebView2NavigationCompletedEventArgs args)
                {
                    status.Text = args.IsSuccess
                        ? "归档来自同一运行；校验通过只说明关联与哈希一致，不代表任务或外部平台联调成功。"
                        : "全链路页面加载失败：" + args.WebErrorStatus;
                    status.ForeColor = args.IsSuccess
                        ? Color.FromArgb(55, 82, 111) : Color.Firebrick;
                };
                browser.CoreWebView2.Navigate(
                    baseUrl + "/artifacts/" + Uri.EscapeDataString(runId)
                    + "/chain_viewer.html");
            }
            catch (Exception ex)
            {
                status.Text = "全链路页面初始化失败：" + ex.Message;
                status.ForeColor = Color.Firebrick;
            }
        }
    }
}
