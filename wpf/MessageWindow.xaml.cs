using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using Gfp.Core;

namespace Gfp;

public enum MsgIcon { Info, Warn, Error, Question }
public enum MsgButtons { OK, YesNo }

public sealed partial class MessageWindow : Window
{
    public MessageWindow(string title, string msg, MsgIcon icon, MsgButtons buttons)
    {
        InitializeComponent();
        Title = title;
        MsgText.Text = msg;
        IconBox.Child = MakeIcon(icon);
        void HookDefault(Button b)
        {
            // 谁获得焦点/点击，谁就成为当前默认按钮，紫色跟随过去；失去焦点则让出默认状态
            b.GotFocus += (_, _) => b.IsDefault = true;
            b.LostFocus += (_, _) => b.IsDefault = false;
        }

        if (buttons == MsgButtons.OK)
        {
            var ok = new Button { Content = "确定", Width = 80, Height = 23, IsDefault = true };
            ok.Click += (_, _) => { DialogResult = true; };
            HookDefault(ok);
            Buttons.Children.Add(ok);
        }
        else
        {
            var yes = new Button { Content = "是", Width = 80, Height = 23, IsDefault = true };
            yes.Click += (_, _) => { DialogResult = true; };
            var no = new Button { Content = "否", Width = 80, Height = 23, Margin = new Thickness(6, 0, 0, 0) };
            no.Click += (_, _) => { DialogResult = false; };
            HookDefault(yes);
            HookDefault(no);
            Buttons.Children.Add(yes);
            Buttons.Children.Add(no);
        }
    }

    private static UIElement MakeIcon(MsgIcon icon)
    {
        var grid = new Grid { Width = 48, Height = 48 };
        if (icon == MsgIcon.Warn)
        {
            // 用 Canvas 绝对定位：Polygon 在 Grid 里对齐是按 PointCollection 的边界框算的，
            // 居中会整体偏移，导致感叹号看着错位。感叹号用几何图形画，避免字体度量差异。
            var canvas = new Canvas { Width = 48, Height = 48 };
            canvas.Children.Add(new Polygon
            {
                Points = new PointCollection { new Point(24, 4), new Point(44, 44), new Point(4, 44) },
                Fill = new SolidColorBrush(Color.FromRgb(250, 200, 50)),
                Stroke = new SolidColorBrush(Color.FromRgb(200, 160, 30)),
                StrokeThickness = 1,
            });

            var bar = new Rectangle { Width = 5, Height = 15, Fill = new SolidColorBrush(Colors.Black) };
            Canvas.SetLeft(bar, 21.5);
            Canvas.SetTop(bar, 17);
            canvas.Children.Add(bar);

            var dot = new Ellipse { Width = 5, Height = 5, Fill = new SolidColorBrush(Colors.Black) };
            Canvas.SetLeft(dot, 21.5);
            Canvas.SetTop(dot, 35.5);
            canvas.Children.Add(dot);

            return canvas;
        }
        else
        {
            var (r, g, b) = icon == MsgIcon.Error ? (214, 60, 60) : (46, 124, 195);
            var ell = new Ellipse
            {
                Width = 44, Height = 44,
                Fill = new SolidColorBrush(Color.FromRgb((byte)r, (byte)g, (byte)b)),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            };
            grid.Children.Add(ell);
            string ch = icon == MsgIcon.Error ? "✕" : icon == MsgIcon.Question ? "?" : "i";
            grid.Children.Add(Text(ch, Colors.White, new Thickness(0, 0, 0, 2)));
        }
        return grid;
    }

    private static UIElement Text(string s, Color c, Thickness margin)
    {
        return new TextBlock
        {
            Text = s,
            Foreground = new SolidColorBrush(c),
            FontFamily = new FontFamily("Microsoft YaHei"),
            FontSize = 22,
            FontWeight = FontWeights.Bold,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = margin,
        };
    }

    private static bool? Show(Window? owner, string title, string msg, MsgIcon icon, MsgButtons buttons)
    {
        var w = new MessageWindow(title, msg, icon, buttons) { Owner = owner };
        return w.ShowDialog();
    }

    public static void Info(Window? owner, string t, string m) => Show(owner, t, m, MsgIcon.Info, MsgButtons.OK);
    public static void Warn(Window? owner, string t, string m) => Show(owner, t, m, MsgIcon.Warn, MsgButtons.OK);
    public static void Err(Window? owner, string t, string m) => Show(owner, t, m, MsgIcon.Error, MsgButtons.OK);
    public static bool Confirm(Window? owner, string t, string m) => Show(owner, t, m, MsgIcon.Question, MsgButtons.YesNo) == true;
}
