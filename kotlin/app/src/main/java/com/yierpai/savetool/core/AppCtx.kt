package com.yierpai.savetool.core

import android.content.res.AssetManager

/** 由 MainActivity 在最早期注入的应用级句柄（让 Core 层不依赖 Context）。 */
object AppCtx {
    lateinit var assets: AssetManager
    var cacheDir: String = ""
}
