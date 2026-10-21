package com.sudox.perclip.capabilities

import com.sudox.perclip.config.PerClipSettings
import java.security.MessageDigest

data class AppCapabilityUiState(
    val configurationFingerprint: String,
    val loading: Boolean,
    val result: AppCapabilityResult?,
    val generation: Long,
)

data class AppCapabilityRequest(val configurationFingerprint: String, val generation: Long)

/** Owns request identity so stale configuration responses cannot win a race. */
class AppCapabilityCoordinator {
    var state = AppCapabilityUiState("", loading = false, result = null, generation = 0)
        private set

    fun begin(settings: PerClipSettings, force: Boolean = false): AppCapabilityRequest? {
        val normalized = settings.normalized()
        val fingerprint = capabilityConfigurationFingerprint(normalized)
        if (!normalized.hasUploadConfig) {
            state = AppCapabilityUiState(
                fingerprint,
                loading = false,
                result = AppCapabilityResult(
                    ok = false,
                    failure = AppCapabilityFailure.CONFIGURATION,
                    message = "请先完成连接设置。",
                ),
                generation = state.generation + 1,
            )
            return null
        }
        if (state.configurationFingerprint == fingerprint && state.loading) return null
        if (!force && state.configurationFingerprint == fingerprint && state.result != null) return null
        val request = AppCapabilityRequest(fingerprint, state.generation + 1)
        state = AppCapabilityUiState(fingerprint, loading = true, result = null, generation = request.generation)
        return request
    }

    fun accept(request: AppCapabilityRequest, result: AppCapabilityResult): Boolean {
        if (request.generation != state.generation || request.configurationFingerprint != state.configurationFingerprint) return false
        state = state.copy(loading = false, result = result)
        return true
    }
}

/** Only this irreversible digest may identify a persisted configuration cache; raw inputs are never stored there. */
fun capabilityConfigurationFingerprint(settings: PerClipSettings): String {
    val normalized = settings.normalized()
    val bytes = MessageDigest.getInstance("SHA-256")
        .digest((normalized.apiUrl + "\u0000" + normalized.ingestToken).toByteArray(Charsets.UTF_8))
    return bytes.joinToString("") { "%02x".format(it) }
}
