package com.yierpai.savetool

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings

/**
 * 「所有文件访问权限」（MANAGE_EXTERNAL_STORAGE）的检测与引导。
 *
 * ⚠ 这个权限与普通运行时权限不同：**系统不会弹窗**，只能由用户到系统设置页手动打开，
 *   所以 App 必须自己给入口，否则用户只会看到"读不到存档"而不知所措。
 */
object Permission {
    var activity: Activity? = null

    /** Activity 恢复前台时触发（典型场景：用户刚从这个权限的设置页返回） */
    var onResumed: (() -> Unit)? = null

    /** Android 11 以下没有该概念，公共目录直接可写，视为已授权 */
    fun isGranted(): Boolean {
        if (Build.VERSION.SDK_INT < 30) return true
        return Environment.isExternalStorageManager()
    }

    /** 跳到本 App 的「所有文件访问权限」设置页 */
    fun openSettings() {
        val act = activity
        if (act == null) {
            println("[GFP-PERM] 无法跳转设置：Activity 引用为空")
            return
        }
        try {
            // 优先跳"本应用"的授权页（带 package: 数据）
            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            intent.data = Uri.parse("package:${act.packageName}")
            act.startActivity(intent)
            println("[GFP-PERM] 已跳转到应用专属授权页")
            return
        } catch (e: Exception) {
            println("[GFP-PERM] 应用专属授权页打不开，改用全部应用列表: ${e.message}")
        }
        try {
            act.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            println("[GFP-PERM] 已跳转到「所有文件访问」总列表")
        } catch (e: Exception) {
            println("[GFP-PERM] 跳转设置失败: ${e.message}")
        }
    }
}
