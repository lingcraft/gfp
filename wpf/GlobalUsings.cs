// 全局 using：net48 + WPF 通过 dotnet CLI 编译时，XAML 临时项目(wpftmp)不会继承
// ImplicitUsings 生成的 global usings，这里显式声明，确保 Core 等所有 .cs 都能解析。
global using System;
global using System.IO;
global using System.Linq;
global using System.Collections.Generic;
global using System.Text;
global using System.Text.Json;
global using System.Threading;
global using System.Threading.Tasks;
