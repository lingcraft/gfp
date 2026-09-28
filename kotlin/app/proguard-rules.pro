# R8 默认规则已覆盖 Compose / Manifest 入口类；这里只做兜底。
-keep class com.yierpai.savetool.MainActivity { *; }
# 装备库 JSON 走 android.jar 自带的 org.json（框架类，不参与裁剪）。
