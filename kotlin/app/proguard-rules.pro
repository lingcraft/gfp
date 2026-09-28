# R8 默认规则已覆盖 Compose / Manifest 入口类；这里只做兜底。
-keep class com.yierpai.savetool.MainActivity { *; }
# 装备库 JSON 走 android.jar 自带的 org.json（框架类，不参与裁剪）。

# ---- 压缩库（7z / rar 导入用）----
# commons-compress 会按名引用一批"可选编解码器"（我们只打包了 xz/LZMA，7z 够用），
# 缺失的那些只需 -dontwarn，不需要真的引入：
-dontwarn org.apache.commons.compress.compressors.**
-dontwarn com.github.luben.zstd.**
-dontwarn org.brotli.dec.**
-dontwarn org.iq80.snappy.**
-dontwarn org.slf4j.**
# commons-compress 的 7z 支持用 commons-io 的 Builder，保留其被引用到的入口即可（R8 会自动判定）。
