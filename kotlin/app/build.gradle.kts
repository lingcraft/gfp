// 版本号唯一来源 = 上一级目录的 pyproject.toml（与 Python / WPF / Avalonia 保持一致）。
// ⚠ Android 版沿用 3 段版本号（1.2.1），与 Avalonia 版一致（WPF 版才是 4 段）。
val pyprojectText = rootProject.file("../pyproject.toml").readText()
val versionNameValue = Regex("""(?m)^version\s*=\s*"([^"]+)"""").find(pyprojectText)!!.groupValues[1]
private val verNums = versionNameValue.split(".").map { it.toInt() }
val versionCodeValue = verNums[0] * 1_000_000 + verNums[1] * 1_000 + verNums[2]

plugins {
    // AGP 9 起内置 Kotlin 支持：不再需要 org.jetbrains.kotlin.android（AGP 自带 KGP）
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.yierpai.savetool"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.yierpai.savetool"
        // ⚠ minSdk 从 24 提到 26（Android 8.0）：导入 7z/rar 用的 commons-compress / commons-io /
        //   junrar 都引用 `java.nio.file`（API 26 才有）。其余功能不受影响。
        minSdk = 26
        targetSdk = 36
        versionCode = versionCodeValue
        versionName = versionNameValue
    }

    // ⚠ 与原 Avalonia 版（.NET Android 的 debug key）签名不同 ⇒ 覆盖安装会报
    //   INSTALL_FAILED_UPDATE_INCOMPATIBLE，需先 adb uninstall com.yierpai.savetool。
    signingConfigs {
        create("release") {
            storeFile = file("D:/Personal Files/Reverse/APK签名/lingcraft.jks")
            storePassword = "123456"
            keyAlias = "lingcraft"
            keyPassword = "123456"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }

    // 装备库 JSON **直接引用仓库根的数据目录** `../../装备`，不再往 app/src 里拷副本 ——
    // 与两个 C# 版做法一致：WPF/Avalonia 的 csproj 都是 <EmbeddedResource Include="..\装备\*.json">。
    // ⚠ 文件名必须保持裸名（打包进 assets/ 根目录）：Relief.kt 是按
    //   "伊尔装备图标数据.json" 这种名字用 assets.open(name) 取的。
    // ⚠ AGP 9：assets.srcDir(...) 已废弃，改用 directories（MutableSet<String>，路径相对本模块目录）；
    //   该类型也没有 filter/includes API，所以"只放行 json"改由下面的 ignoreAssetsPattern 承担。
    sourceSets {
        getByName("main") {
            assets.directories.add("../../装备")
        }
    }

    androidResources {
        // 把同目录下的 *.gd 脚本挡在 assets 外 —— 只有 *.json 进包，
        // 与 C# 版 <EmbeddedResource Include="..\装备\*.json"> 的语义等价。
        ignoreAssetsPattern = "*.gd"
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // 已升到 AGP 9.4.1 + compileSdk 37，故可用最新 AndroidX（旧组合上限见 git 历史：
    // AGP 8.13.2 + compileSdk 36 时只能用 compose-bom 2026.06.01 / core-ktx 1.18.0）。
    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    // MD3 图标（扩展集）。⚠ 该库已被官方冻结在 1.7.8（BOM 里也是这个版本），
    //   参考实现 InstallerX-Revived 同样用 1.7.8；release 走 R8 只保留用到的图标。
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.19.1")

    // ---- 压缩包**读取**支持（导入用；备份/导出只产出 zip，不需要它们）----
    // zip  → JDK 自带 `java.util.zip`
    // 7z   → commons-compress 的 SevenZFile（会连带引入 commons-io）
    // xz   → commons-compress 用来解 7z 的 LZMA/LZMA2（可选依赖，但缺了多数 7z 打不开）
    // rar  → junrar（纯 JVM，RAR4/RAR5 都支持）；它 runtime 依赖 slf4j-api，补 slf4j-nop 静音告警
    // ⚠ 这几个库都用到 `java.nio.file` ⇒ minSdk 必须 ≥ 26
    implementation("org.apache.commons:commons-compress:1.28.0")
    implementation("org.tukaani:xz:1.12")
    implementation("com.github.junrar:junrar:8.1.1")
    runtimeOnly("org.slf4j:slf4j-nop:2.0.17")
}
