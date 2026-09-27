#!/usr/bin/env python3
"""往 GodotActivity.onCreate 开头注入"所有文件访问"权限检查（启动秒弹授权页）。

时机说明：GodotActivity.onCreate 在引擎（GodotLib.setup，加载 3.6G sparsepck）之前执行，
所以授权页在启动后 1~2 秒内就弹出，不必等游戏资源加载完（GDScript 层 _ready 太晚）。
"""
import re
import sys
from pathlib import Path

SMALI = """    # === GFP INJECT START: 启动即引导"所有文件访问"授权 ===
    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I
    const/16 v1, 0x1e
    if-lt v0, v1, :gfp_perm_done

    invoke-static {}, Landroid/os/Environment;->isExternalStorageManager()Z
    move-result v0
    if-nez v0, :gfp_perm_done

    const-string v0, "GFP_PERM"
    const-string v1, "no All-Files-Access, opening settings"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    new-instance v1, Ljava/lang/StringBuilder;
    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V
    const-string v2, "package:"
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {p0}, Landroid/content/Context;->getPackageName()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    invoke-static {v1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setData(Landroid/net/Uri;)Landroid/content/Intent;

    invoke-virtual {p0, v0}, Landroid/app/Activity;->startActivity(Landroid/content/Intent;)V

    :gfp_perm_done
    # === GFP INJECT END ===

"""


def inject(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "GFP INJECT START" in text:
        print("[i] 已注入过，跳过")
        return True

    m = re.search(r"\.method protected onCreate\(Landroid/os/Bundle;\)V\n", text)
    if not m:
        print("[x] 找不到 onCreate 方法")
        return False

    head = m.end()
    # 跳到 .param 之后、第一条 .line 之前（避开 try 块，寄存器全部空闲）
    rest = text[head:]
    lm = re.search(r"\n(?:    \.param [^\n]*\n)*    \.line ", rest)
    if not lm:
        print("[x] 找不到 onCreate 内的 .line 定位点")
        return False
    pos = head + lm.start() + 1
    new = text[:pos] + SMALI + text[pos:]
    path.write_text(new, encoding="utf-8")
    print(f"[v] 已注入权限引导到 {path.name}（onCreate 开头）")
    return True


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1
               else "smali8/org/godotengine/godot/GodotActivity.smali")
    sys.exit(0 if inject(src) else 1)
