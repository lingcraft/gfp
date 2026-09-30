from tomllib import load
from argparse import ArgumentParser
from subprocess import run
from pathlib import Path
from shutil import copy2

with open("pyproject.toml", "rb") as file:
    version = load(file)["project"]["version"]

parser = ArgumentParser(description="打包功夫派怀旧服存档工具")
parser.add_argument("--dir", default="D:\\Downloads", help="输出目录")
parser.add_argument("--name", default="存档工具", help="输出文件名")
args = parser.parse_args()

BASE_DIR = Path(__file__).resolve().parent
GRADLE = r"D:\Software\Gradle\bin\gradle.bat"
cmd = [GRADLE, "-p", str(BASE_DIR / "kotlin"), "assembleRelease", "--console=plain"]
print(f"[$] {" ".join(cmd)}", flush=True)
run(cmd, check=True)

target = Path(args.dir) / f"{args.name}.apk"
copy2(BASE_DIR / "kotlin" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk", target)
print(f"[v] 已输出：{target}（{target.stat().st_size / 1024 / 1024:.3f} MB，版本 {version}）")
