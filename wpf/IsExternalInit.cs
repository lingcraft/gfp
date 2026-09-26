// net48 缺少 record/init 所需的 IsExternalInit 类型，这里补一个 polyfill。
namespace System.Runtime.CompilerServices
{
    internal sealed class IsExternalInit { }
}
