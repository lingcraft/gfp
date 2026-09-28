package com.yierpai.savetool.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/**
 * 应用主题（Material Design 3）。
 *
 * - 默认使用 **M3 baseline 配色**（Google 官方紫色调，即参考截图那种观感），
 *   并同时提供深色配色（跟随系统深色模式）。
 * - 若想跟随壁纸（Material You 动态取色），把 [USE_DYNAMIC_COLOR] 改成 true 即可
 *   （仅 Android 12 / API 31+ 生效，低版本自动回落 baseline）。
 */
private const val USE_DYNAMIC_COLOR = false

@Composable
fun GfpTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val ctx = LocalContext.current
    val scheme = when {
        USE_DYNAMIC_COLOR && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)

        dark -> darkColorScheme()
        else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = scheme, content = content)
}
