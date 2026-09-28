// AGP 9 内置 Kotlin：默认带 KGP 2.2.10，这里显式抬到 2.4.20（官方文档指定的升级方式）。
// ⚠ buildscript 的仓库要单独声明（pluginManagement 的仓库不作用于 buildscript）。 
buildscript {
    repositories {
        maven("https://maven.aliyun.com/repository/gradle-plugin")
        maven("https://maven.aliyun.com/repository/public")
        google()
        mavenCentral()
    }
    dependencies {
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.20")
    }
}

plugins {
    id("com.android.application") version "9.4.1" apply false
    // Compose 编译器插件在 Kotlin 2.0+ 是必需的（AGP 内置 Kotlin 也一样），版本须与 KGP 一致
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20" apply false
}
