package com.sudox.perclip.ui.recall

import android.app.ActivityManager
import android.content.Context
import android.os.PowerManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.delay

@Stable
internal class MemoryPlanetMotionClock(initialElapsedMillis: Long = 0L) {
    var elapsedMillis by mutableLongStateOf(initialElapsedMillis.coerceAtLeast(0L))
        private set

    fun advance(deltaMillis: Long, running: Boolean = true) {
        if (running && deltaMillis > 0L) elapsedMillis += deltaMillis
    }
}

internal object MemoryPlanetClockPolicy {
    fun shouldRun(
        lifecycleActive: Boolean,
        planetVisible: Boolean,
        graphExpanded: Boolean,
        contentState: MemoryPlanetContentState,
        quality: MemoryPlanetQuality,
        reducedMotion: Boolean,
        browsingAll: Boolean,
        menuOpen: Boolean,
        filterOverlayOpen: Boolean,
        snackbarOpen: Boolean,
        suppressionSheetOpen: Boolean,
    ): Boolean = lifecycleActive &&
        planetVisible &&
        graphExpanded &&
        contentState == MemoryPlanetContentState.NORMAL &&
        quality != MemoryPlanetQuality.STATIC &&
        !reducedMotion &&
        !browsingAll &&
        !menuOpen &&
        !filterOverlayOpen &&
        !snackbarOpen &&
        !suppressionSheetOpen
}

@Composable
internal fun rememberMemoryPlanetQuality(
    reducedMotion: Boolean,
    systemAnimationsDisabled: Boolean,
    debugOverride: MemoryPlanetQuality? = null,
): MemoryPlanetQuality {
    val context = LocalContext.current
    return remember(reducedMotion, systemAnimationsDisabled, debugOverride) {
        val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
        MemoryPlanetQualityPolicy.select(
            MemoryPlanetPerformanceInputs(
                lowRamDevice = activityManager?.isLowRamDevice == true,
                powerSaveMode = powerManager?.isPowerSaveMode == true,
                reducedMotion = reducedMotion,
                systemAnimationsDisabled = systemAnimationsDisabled,
                debugOverride = debugOverride,
            ),
        )
    }
}

@Composable
internal fun rememberMemoryPlanetLifecycleActive(): Boolean {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var active by remember(lifecycle) {
        mutableStateOf(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
    }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, _ ->
            active = lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    return active
}

@Composable
internal fun MemoryPlanetMotionClockDriver(
    clock: MemoryPlanetMotionClock,
    running: Boolean,
    lastInteractionAt: Long,
) {
    LaunchedEffect(clock, running, lastInteractionAt) {
        if (!running) return@LaunchedEffect
        val remainingPause = RecallOrbitPolicy.remainingPauseMillis(
            lastInteractionAt = lastInteractionAt,
            now = System.currentTimeMillis(),
        )
        if (remainingPause > 0L) delay(remainingPause)
        var previousFrame = withFrameNanos { it }
        while (true) {
            val currentFrame = withFrameNanos { it }
            clock.advance((currentFrame - previousFrame).coerceAtLeast(0L) / 1_000_000L)
            previousFrame = currentFrame
        }
    }
}

internal fun MemoryPlanetMotionClock.orbitDegrees(cycleMillis: Int): Float =
    ((elapsedMillis % cycleMillis).toFloat() / cycleMillis) * 360f
