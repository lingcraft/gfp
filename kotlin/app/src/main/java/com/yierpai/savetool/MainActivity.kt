package com.yierpai.savetool

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.yierpai.savetool.core.AppCtx
import com.yierpai.savetool.core.Save
import com.yierpai.savetool.ui.MainScreen

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Android 15+ 强制 edge-to-edge（Android 16 对 targetSdk 36 连 opt-out 都忽略）：
        // 显式开启并交给 Scaffold 的 innerPadding 处理系统栏内边距，避免内容被状态栏/导航栏压住。
        enableEdgeToEdge()

        // 供 Core 层读取装备库 assets / 临时目录（避免 Core 依赖 Context）
        AppCtx.assets = assets
        AppCtx.cacheDir = cacheDir.absolutePath

        // 游戏 SAVE_ROOT = /storage/emulated/0/YierPai/saves ⇒ 这里指向其父目录，
        // 于是 Save.savesDir = /storage/emulated/0/YierPai/saves。
        // ⚠ 共享存储根下的目录，跨应用读写必须 MANAGE_EXTERNAL_STORAGE（界面上的引导区就是干这个的）。
        Save.dataDirOverride = "/storage/emulated/0/YierPai"

        Permission.activity = this

        setContent {
            MainScreen()
        }
    }

    override fun onResume() {
        super.onResume()
        // 用户可能刚从系统设置页返回 —— 通知界面重新检测权限
        Permission.activity = this
        Permission.onResumed?.invoke()
    }

    override fun onDestroy() {
        if (Permission.activity === this) Permission.activity = null
        Permission.onResumed = null
        super.onDestroy()
    }
}
