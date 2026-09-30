from tomllib import load
from argparse import ArgumentParser
from subprocess import run

with open("pyproject.toml", "rb") as file:
    version = load(file)["project"]["version"]

parser = ArgumentParser(description="打包功夫派怀旧服存档工具")
parser.add_argument("--dir", default="D:\\Downloads", help="输出目录")
parser.add_argument("--name", default="存档工具", help="输出文件名")
args = parser.parse_args()

cmd = " ".join([
    "nuitka", "gfp.py",
    "--standalone", "--jobs=8", "--lto=yes", "--remove-output",
    "--windows-console-mode=disable", "--windows-icon-from-ico=icon.ico",
    "--enable-plugin=pyside6",
    "--copyright=\"Copyright (C) 2026 lingcraft. All Rights Reserved\"",
    "--file-description=功夫派怀旧服存档工具",
    "--product-name=功夫派怀旧服存档工具",
    f"--file-version={version}",
    f"--product-version={version}",
    f"--output-dir=\"{args.dir}\"",
    f"--output-filename=\"{args.name}.exe\"",
    "--include-data-files=7z.dll=7z.dll",
    "--include-data-files=zh_CN.qm=zh_CN.qm",
    "--include-data-dir=装备=装备",
    "--onefile"
])

run(cmd, input=b"Yes\n", shell=True)
