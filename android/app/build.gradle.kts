plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

val debugApplicationIdSuffix = providers.gradleProperty("perclipDebugApplicationIdSuffix").orNull
val debugAppName = providers.gradleProperty("perclipDebugAppName").orNull
val pinnedDebugBuild = providers.gradleProperty("perclipPinnedBuild").orNull?.toBooleanStrictOrNull() ?: false

if (!pinnedDebugBuild && (debugApplicationIdSuffix != null || debugAppName != null)) {
    error(
        "Custom debug package/name properties are reserved for pinned builds. " +
            "Add -PperclipPinnedBuild=true, or omit them to build the replaceable PerClip Dev app.",
    )
}

if (pinnedDebugBuild) {
    require(!debugApplicationIdSuffix.isNullOrBlank()) {
        "Pinned builds require -PperclipDebugApplicationIdSuffix=<unique-stage-suffix>."
    }
    require(!debugAppName.isNullOrBlank()) {
        "Pinned builds require -PperclipDebugAppName=<clear-stage-name>."
    }
}

android {
    namespace = "com.sudox.perclip"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.sudox.perclip"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "0.3.0"
        manifestPlaceholders["launcherIcon"] = "@mipmap/ic_launcher"
        manifestPlaceholders["launcherRoundIcon"] = "@mipmap/ic_launcher_round"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            if (pinnedDebugBuild) {
                val suffix = debugApplicationIdSuffix!!.trim()
                applicationIdSuffix = if (suffix.startsWith(".")) suffix else ".$suffix"
                resValue("string", "app_name", debugAppName!!.trim())
            } else {
                applicationIdSuffix = ".dev"
                resValue("string", "app_name", "PerClip Dev")
                manifestPlaceholders["launcherIcon"] = "@mipmap/ic_launcher_dev"
                manifestPlaceholders["launcherRoundIcon"] = "@mipmap/ic_launcher_dev_round"
            }
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.06.00"))
    implementation("androidx.activity:activity-compose:1.12.0")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.core:core-ktx:1.18.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.work:work-runtime-ktx:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:5.3.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")

    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}
