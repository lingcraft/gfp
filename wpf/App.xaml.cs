using System.Windows;
using Gfp.Core;

namespace Gfp;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        if (e.Args.Contains("--selftest"))
        {
            SelfTest.Run();
            Shutdown();
            return;
        }
        base.OnStartup(e);
    }
}
