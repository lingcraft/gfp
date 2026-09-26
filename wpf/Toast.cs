using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using Gfp.Core;

namespace Gfp;

/// 非模态 Toast（Fusion 风格），居中游戏窗口，2.5s 后自动消失
public sealed class Toast
{
    public static void Show(string msg)
    {
        var w = new Window
        {
            WindowStyle = WindowStyle.None,
            AllowsTransparency = true,
            Background = Brushes.Transparent,
            ShowInTaskbar = false,
            Topmost = true,
            SizeToContent = SizeToContent.WidthAndHeight,
            ResizeMode = ResizeMode.NoResize,
        };
        var border = new Border
        {
            // Python: TOAST_BG = QColor(238, 216, 167, 240), TOAST_BORDER = QColor(150, 110, 40)
            // 边框 2px、圆角 10、padding 12/24、文字 14pt bold 居中
            Background = new SolidColorBrush(Color.FromArgb(240, 238, 216, 167)),
            BorderBrush = new SolidColorBrush(Color.FromRgb(150, 110, 40)),
            BorderThickness = new Thickness(2),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(24, 12, 24, 12),
        };
        border.Child = new TextBlock
        {
            Text = msg,
            Foreground = new SolidColorBrush(Color.FromRgb(59, 42, 18)),
            FontFamily = new FontFamily("Microsoft YaHei"),
            FontSize = 14 * 96.0 / 72.0, // PySide6 14pt → WPF DIU (1pt = 96/72 DIU)
            FontWeight = FontWeights.Bold,
            TextWrapping = TextWrapping.NoWrap,
            TextAlignment = TextAlignment.Center,
        };
        w.Content = border;

        var (cx, cy) = Win.Center("yierpai");
        w.Loaded += (_, _) =>
        {
            w.Left = cx - w.ActualWidth / 2;
            w.Top = cy - w.ActualHeight / 2;
        };
        w.Show();

        var timer = new DispatcherTimer { Interval = System.TimeSpan.FromMilliseconds(2500) };
        timer.Tick += (_, _) => { timer.Stop(); w.Close(); };
        timer.Start();
    }
}
