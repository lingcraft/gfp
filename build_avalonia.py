from tomllib import load
from argparse import ArgumentParser
from subprocess import run
from pathlib import Path
from shutil import copy2
from os import environ

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "pyproject.toml", "rb") as file:
    version = load(file)["project"]["version"]

parser = ArgumentParser(description="打包功夫派怀旧服存档工具（Avalonia 安卓版）")
parser.add_argument("--dir", default="D:\\Downloads", help="输出目录（默认：D:\\Downloads）")
parser.add_argument("--file", default="gfp-android.apk", help="输出文件名（默认：gfp-android.apk）")
parser.add_argument("--abi", default="android-arm64", help="ABI（默认 android-arm64；模拟器用 android-x64）")
args = parser.parse_args()

# SDK 路径：优先读环境变量，否则用本机固定路径。
ANDROID_HOME = environ.get("ANDROID_HOME") or environ.get("ANDROID_SDK_ROOT") or r"D:\Software\Android"
JAVA_HOME = environ.get("JAVA_HOME") or r"D:\Software\JDK\17"

# 版本号：csproj 已会自己读 pyproject.toml（手动 dotnet publish 也能对齐版本），
# 这里再显式传 -p:Version，与 build_wpf.py 保持对称、双保险。
cmd = [
    "dotnet", "publish",
    str(BASE_DIR / "avalonia" / "Gfp.Mobile.csproj"),
    "-f", "net10.0-android",
    "-c", "Release",
    f"-p:Version={version}",
    f"-p:RuntimeIdentifiers={args.abi}",
    "-p:EmbedAssembliesIntoApk=true",
    f"-p:AndroidSdkDirectory={ANDROID_HOME}",
    f"-p:JavaSdkDirectory={JAVA_HOME}",
]
print(f"[$] {" ".join(cmd)}", flush=True)
run(cmd, check=True)

src = BASE_DIR / "avalonia" / "bin" / "Release" / "net10.0-android" / "publish" / "com.yierpai.savetool-Signed.apk"
target = Path(args.dir) / args.file
copy2(src, target)
print(f"[v] 已输出：{target}（{target.stat().st_size / 1024 / 1024:.3f} MB，版本 {version}）")
