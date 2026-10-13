plugins {
    id("com.android.application")
}

val appVersionName = providers.gradleProperty("VERSION_NAME").orElse("0.4.1")
val appVersionCode = providers.gradleProperty("VERSION_CODE").orElse("401")
val signingStore = System.getenv("ANDROID_KEYSTORE_PATH")
val signingPassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
val signingAlias = System.getenv("ANDROID_KEY_ALIAS")
val signingKeyPassword = System.getenv("ANDROID_KEY_PASSWORD")
val hasReleaseSigning = listOf(
    signingStore,
    signingPassword,
    signingAlias,
    signingKeyPassword
).all { !it.isNullOrBlank() }

android {
    namespace = "com.sal0.voz"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.sal0.voz"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode.get().toInt()
        versionName = appVersionName.get()

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(signingStore!!)
                storePassword = signingPassword
                keyAlias = signingAlias
                keyPassword = signingKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                // Mantém o APK público instalável quando nenhuma chave privada
                // de lançamento estiver configurada no ambiente de CI.
                signingConfig = signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    testOptions {
        unitTests.isIncludeAndroidResources = false
    }
}

dependencies {
    implementation("androidx.activity:activity:1.13.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
