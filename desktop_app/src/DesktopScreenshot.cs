using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Threading.Tasks;

namespace MarlDesktopPreview
{
    public sealed partial class MainWindow
    {
        private async Task SaveNativeScreenshot(string path)
        {
            using (Bitmap bitmap = new Bitmap(Width, Height))
            {
                DrawToBitmap(bitmap, new Rectangle(0, 0, Width, Height));
                // Draw the command row separately: DrawToBitmap can let its docked label cover it.
                System.Windows.Forms.Control[] commandRows = Controls.Find("SceneMapActions", true);
                if(commandRows.Length>0 && commandRows[0].Visible) {
                    var row=commandRows[0];
                    using(Bitmap commands=new Bitmap(row.Width,row.Height))using(Graphics g=Graphics.FromImage(bitmap)) {
                        row.DrawToBitmap(commands,new Rectangle(0,0,row.Width,row.Height));
                        Point screen=row.PointToScreen(Point.Empty); Point origin=new Point(screen.X-Location.X,screen.Y-Location.Y);
                        g.DrawImageUnscaled(commands,origin.X,origin.Y);
                    }
                }
                if (webReady && webView != null && webView.Visible && webView.CoreWebView2 != null)
                {
                    using (MemoryStream stream = new MemoryStream())
                    {
                        await webView.CoreWebView2.CapturePreviewAsync(Microsoft.Web.WebView2.Core.CoreWebView2CapturePreviewImageFormat.Png, stream);
                        stream.Position = 0;
                        using (Image scene = Image.FromStream(stream))
                        using (Graphics graphics = Graphics.FromImage(bitmap))
                        {
                            Point origin = webView.PointToScreen(Point.Empty);
                            graphics.DrawImage(scene, new Rectangle(origin.X - Location.X, origin.Y - Location.Y, webView.Width, webView.Height));
                        }
                    }
                }
                bitmap.Save(path, ImageFormat.Png);
            }
        }
    }
}
