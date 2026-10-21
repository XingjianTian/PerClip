package com.sudox.perclip.ui.recall

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin

internal enum class MemoryPlanetQuality { FULL, LITE, STATIC }

internal enum class MemoryPlanetContentState { NORMAL, LOADING, EMPTY, API_UNAVAILABLE }

internal data class MemoryPlanetPerformanceInputs(
    val lowRamDevice: Boolean = false,
    val powerSaveMode: Boolean = false,
    val reducedMotion: Boolean = false,
    val systemAnimationsDisabled: Boolean = false,
    val debugOverride: MemoryPlanetQuality? = null,
)

internal object MemoryPlanetQualityPolicy {
    fun select(inputs: MemoryPlanetPerformanceInputs): MemoryPlanetQuality = when {
        inputs.reducedMotion || inputs.systemAnimationsDisabled -> MemoryPlanetQuality.STATIC
        inputs.debugOverride != null -> inputs.debugOverride
        inputs.lowRamDevice || inputs.powerSaveMode -> MemoryPlanetQuality.LITE
        else -> MemoryPlanetQuality.FULL
    }
}

internal data class MemoryPlanetStarSpec(
    val seed: Int,
    val xRatio: Float,
    val yRatio: Float,
    val radiusDp: Float,
    val major: Boolean,
    val minAlpha: Float,
    val maxAlpha: Float,
    val periodMillis: Int,
    val initialPhase: Float,
    val peakPosition: Float,
    val driftPx: Float = 0f,
    val driftPeriodMillis: Int = 10_000,
)

internal data class MemoryPlanetStarFrame(
    val spec: MemoryPlanetStarSpec,
    val alpha: Float,
    val driftX: Float,
    val driftY: Float,
)

internal object MemoryPlanetStarfieldSpecs {
    const val LIGHT_FULL_COUNT = 22
    const val LIGHT_MAJOR_COUNT = 5
    const val DARK_FULL_COUNT = 18
    const val DARK_MAJOR_COUNT = 4
    const val LITE_COUNT = 10
    const val API_UNAVAILABLE_COUNT = 8

    val majorPeriods = setOf(1_900, 2_400, 2_900, 3_400)
    val minorPeriods = setOf(1_300, 1_700, 2_100, 2_600)

    private val lightCoordinates = listOf(
        .061f to .104f, .944f to .090f, .506f to .270f, .629f to .654f, .260f to .838f,
        .134f to .056f, .447f to .072f, .598f to .080f, .897f to .240f, .047f to .288f,
        .158f to .352f, .283f to .404f, .405f to .364f, .609f to .420f, .950f to .408f,
        .252f to .544f, .665f to .532f, .066f to .720f, .194f to .708f, .293f to .736f,
        .609f to .760f, .055f to .928f,
    )

    private val darkCoordinates = listOf(
        .067f to .106f, .931f to .094f, .512f to .267f, .645f to .660f,
        .151f to .058f, .441f to .076f, .603f to .083f, .884f to .244f,
        .052f to .296f, .281f to .407f, .413f to .369f, .941f to .414f,
        .247f to .548f, .674f to .536f, .071f to .724f, .201f to .712f,
        .301f to .742f, .615f to .766f,
    )

    fun full(dark: Boolean): List<MemoryPlanetStarSpec> {
        val coordinates = if (dark) darkCoordinates else lightCoordinates
        val majorCount = if (dark) DARK_MAJOR_COUNT else LIGHT_MAJOR_COUNT
        return coordinates.mapIndexed { index, (x, y) ->
            val major = index < majorCount
            val seed = 37 + index * 19
            val periodPool = if (major) majorPeriods.sorted() else minorPeriods.sorted()
            val minAlpha = when {
                dark && major -> .10f
                dark -> .06f
                major -> .18f
                else -> .08f
            }
            val maxAlpha = when {
                dark && major && index == 0 -> .58f
                dark && major -> .52f
                dark -> .24f
                major && index == 0 -> .74f
                major -> .68f
                else -> .30f
            }
            val minorIndex = (index - majorCount).coerceAtLeast(0)
            val drifting = !major && minorIndex % 6 == 2
            MemoryPlanetStarSpec(
                seed = seed,
                xRatio = x,
                yRatio = y,
                radiusDp = if (major) if (index == 0) 2.1f else 1.6f else .85f,
                major = major,
                minAlpha = minAlpha,
                maxAlpha = maxAlpha,
                periodMillis = periodPool[index.mod(periodPool.size)],
                initialPhase = ((index * 17).mod(100)) / 100f,
                peakPosition = .42f + ((index * 13).mod(27)) / 100f,
                driftPx = if (drifting) .5f + (minorIndex.mod(3) * .25f) else 0f,
                driftPeriodMillis = 8_000 + minorIndex.mod(5) * 1_000,
            )
        }
    }

    fun select(
        dark: Boolean,
        quality: MemoryPlanetQuality,
        content: MemoryPlanetContentState,
    ): List<MemoryPlanetStarSpec> {
        val full = full(dark)
        val count = when (content) {
            MemoryPlanetContentState.API_UNAVAILABLE -> API_UNAVAILABLE_COUNT
            MemoryPlanetContentState.LOADING, MemoryPlanetContentState.EMPTY -> LITE_COUNT
            MemoryPlanetContentState.NORMAL -> if (quality == MemoryPlanetQuality.LITE) LITE_COUNT else full.size
        }
        return full.take(count).mapIndexed { index, star ->
            if (quality != MemoryPlanetQuality.LITE) star else star.copy(
                periodMillis = 2_400 + index.mod(5) * 400,
                driftPx = 0f,
            )
        }
    }

    fun frame(
        specs: List<MemoryPlanetStarSpec>,
        elapsedMillis: Long,
        dark: Boolean,
        static: Boolean,
        reducedMotion: Boolean,
    ): List<MemoryPlanetStarFrame> {
        val raw = specs.map { spec ->
            val alpha = when {
                reducedMotion && spec.major -> if (dark) .22f else .30f
                reducedMotion -> if (dark) .10f else .14f
                static -> spec.minAlpha + (spec.maxAlpha - spec.minAlpha) * .46f
                else -> animatedAlpha(spec, elapsedMillis)
            }
            val driftPhase = if (spec.driftPx > 0f && !static && !reducedMotion) {
                ((elapsedMillis % spec.driftPeriodMillis).toFloat() / spec.driftPeriodMillis) * (2f * PI.toFloat())
            } else {
                0f
            }
            MemoryPlanetStarFrame(
                spec = spec,
                alpha = alpha,
                driftX = if (spec.driftPx > 0f && !static && !reducedMotion) cos(driftPhase) * spec.driftPx else 0f,
                driftY = if (spec.driftPx > 0f && !static && !reducedMotion) sin(driftPhase * .83f) * spec.driftPx else 0f,
            )
        }
        if (static || reducedMotion) return raw
        val overPeak = raw.withIndex()
            .filter { (_, frame) -> frame.spec.major && normalizedBrightness(frame) >= .92f }
            .sortedByDescending { (_, frame) -> normalizedBrightness(frame) }
        if (overPeak.size <= 2) return raw
        val allowed = overPeak.take(2).map { it.index }.toSet()
        return raw.mapIndexed { index, frame ->
            if (!frame.spec.major || index in allowed || normalizedBrightness(frame) < .92f) frame else {
                frame.copy(alpha = frame.spec.minAlpha + (frame.spec.maxAlpha - frame.spec.minAlpha) * .88f)
            }
        }
    }

    fun peakMajorCount(frames: List<MemoryPlanetStarFrame>): Int =
        frames.count { it.spec.major && normalizedBrightness(it) >= .92f }

    fun normalizedBrightness(frame: MemoryPlanetStarFrame): Float {
        val range = frame.spec.maxAlpha - frame.spec.minAlpha
        return if (range <= 0f) 0f else ((frame.alpha - frame.spec.minAlpha) / range).coerceIn(0f, 1f)
    }

    private fun animatedAlpha(spec: MemoryPlanetStarSpec, elapsedMillis: Long): Float {
        val elapsedPhase = (elapsedMillis % spec.periodMillis).toFloat() / spec.periodMillis
        val phase = (elapsedPhase + spec.initialPhase).mod(1f)
        val brightness = if (phase <= spec.peakPosition) {
            (phase / spec.peakPosition).coerceIn(0f, 1f).pow(.72f)
        } else {
            (1f - (phase - spec.peakPosition) / (1f - spec.peakPosition))
                .coerceIn(0f, 1f)
                .pow(1.28f)
        }
        return spec.minAlpha + (spec.maxAlpha - spec.minAlpha) * brightness
    }
}

internal object MemoryPlanetStarExclusions {
    private data class Circle(val x: Float, val y: Float, val radius: Float)

    private val topicNodes = listOf(
        Circle(.308f, .208f, .098f),
        Circle(.757f, .272f, .098f),
        Circle(.124f, .519f, .098f),
        Circle(.850f, .624f, .098f),
        Circle(.460f, .744f, .118f),
    )
    private val core = Circle(.50f, .48f, .105f)

    fun insideTopicNode(star: MemoryPlanetStarSpec): Boolean = topicNodes.any { circle ->
        val dx = star.xRatio - circle.x
        val dy = star.yRatio - circle.y
        dx * dx + dy * dy < circle.radius * circle.radius
    }

    fun majorAllowed(star: MemoryPlanetStarSpec): Boolean {
        if (!star.major || insideTopicNode(star)) return !insideTopicNode(star)
        if (star.yRatio >= .79f && star.xRatio >= .43f) return false
        val dx = star.xRatio - core.x
        val dy = star.yRatio - core.y
        return dx * dx + dy * dy >= core.radius * core.radius
    }
}

@Composable
internal fun MemoryPlanetStarfield(
    elapsedMillis: Long,
    dark: Boolean,
    quality: MemoryPlanetQuality,
    content: MemoryPlanetContentState,
    reducedMotion: Boolean,
    modifier: Modifier = Modifier,
) {
    val specs = MemoryPlanetStarfieldSpecs.select(dark, quality, content)
    val frames = MemoryPlanetStarfieldSpecs.frame(
        specs = specs,
        elapsedMillis = elapsedMillis,
        dark = dark,
        static = quality == MemoryPlanetQuality.STATIC || content != MemoryPlanetContentState.NORMAL,
        reducedMotion = reducedMotion,
    )
    val color = if (dark) Color(0xFFC5B6FF) else Color(0xFF765BFF)
    Canvas(modifier.clearAndSetSemantics { }) {
        frames.forEach { frame ->
            val center = Offset(
                x = size.width * frame.spec.xRatio + frame.driftX,
                y = size.height * frame.spec.yRatio + frame.driftY,
            )
            val radius = frame.spec.radiusDp.dp.toPx()
            if (frame.spec.major) {
                drawCircle(color.copy(alpha = frame.alpha * .16f), radius * 2.15f, center)
            }
            drawCircle(color.copy(alpha = frame.alpha), radius, center)
        }
    }
}
