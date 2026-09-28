from tomllib import load
from argparse import ArgumentParser
from subprocess import run
from pathlib import Path
from shutil import copy2

with open("pyproject.toml", "rb") as file:
    version = load(file)["project"]["version"]

parser = ArgumentParser(description="打包功夫派怀旧服存档工具（WPF 版）")
parser.add_argument("--dir", default="D:\\Downloads", help="输出目录（默认：D:\\Downloads）")
parser.add_argument("--file", default="gfp.exe", help="输出文件名（默认：gfp.exe）")
args = parser.parse_args()

kill = run(["taskkill", "/f", "/im", "gfp.exe"], capture_output=True, text=True)
if kill.returncode == 0:
    print("[i] 已结束正在运行的 gfp.exe")

BASE_DIR = Path(__file__).resolve().parent
cmd = ["dotnet", "build", str(BASE_DIR / "wpf" / "gfp.csproj"), "-c", "Release", f"-p:Version={version}"]
print(f"[$] {" ".join(cmd)}", flush=True)
run(cmd, check=True)

target = Path(args.dir) / args.file
copy2(BASE_DIR / "wpf" / "bin" / "Release" / "net48" / "gfp.exe", target)
print(f"[v] 已输出：{target}（{target.stat().st_size / 1024 / 1024:.3f} MB）")
