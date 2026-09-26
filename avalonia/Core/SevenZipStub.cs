namespace Gfp.Core;

/// <summary>
/// 移动端的 SevenZip 存根。
///
/// ⚠ 为什么需要它：wpf/Core/Archive.cs 被本工程直接链接复用，而它的 7z / rar 分支会调
///   SevenZip.ExtractTo / ListNames。真正的 SevenZip.cs 依赖 7z.dll（Windows x64 native），
///   在 Android 上既编译不了也跑不动。
///   所以这里只提供同名同签名的存根 —— 编译期满足引用，运行期一旦真走到 7z/rar 就明确报错，
///   而不是抛一个莫名其妙的 DllNotFoundException。
///
/// ✅ zip 路径完全不经过这里（Archive.cs 里 zip 全部走 System.IO.Compression）。
/// </summary>
public static class SevenZip
{
    private const string Msg = "移动端只支持 zip 格式，7z / rar 请先在电脑上转成 zip。";

    public static void ExtractTo(string src, string target) => throw new NotSupportedException(Msg);

    public static List<string> ListNames(string src) => throw new NotSupportedException(Msg);
}
