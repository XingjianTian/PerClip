package com.sudox.perclip.capabilities

data class AppFeatures(
    val knowledgeBases: Boolean,
    val routing: Boolean,
    val recall: Boolean,
    val recallDomain: Boolean,
    val mobileBatchStatus: Boolean,
    val ingestV1: Boolean,
    val ragflowCapabilities: Boolean,
    val qualityReadModel: Boolean = false,
    val memoryPlanet: Boolean = false,
    val knowledgeListV2: Boolean = false,
) {
    val complete: Boolean
        get() = knowledgeBases && routing && recall && recallDomain &&
            mobileBatchStatus && ingestV1 && ragflowCapabilities
}

data class AppContracts(
    val knowledgeList: String = "",
)

data class AppCapabilities(
    val apiContract: String,
    val service: String,
    val features: AppFeatures,
    val contracts: AppContracts = AppContracts(),
) {
    val isCurrentPerClipApi: Boolean
        get() = apiContract == EXPECTED_CONTRACT && service == EXPECTED_SERVICE

    companion object {
        const val EXPECTED_CONTRACT = "perclip.app.v1"
        const val EXPECTED_SERVICE = "perclip-ingest"
        const val EXPECTED_KNOWLEDGE_LIST = "perclip.knowledge-list.v2"
    }
}

enum class AppCapabilityFailure {
    NONE,
    CONFIGURATION,
    UNREACHABLE,
    AUTHENTICATION,
    CONTRACT_MISSING,
    CONTRACT_MISMATCH,
    FEATURES_INCOMPLETE,
    INVALID_RESPONSE,
    SERVER,
}

data class AppCapabilityResult(
    val ok: Boolean,
    val capabilities: AppCapabilities? = null,
    val failure: AppCapabilityFailure = AppCapabilityFailure.NONE,
    val message: String,
) {
    /** True only when the response is a valid current PerClip contract. */
    val contractValid: Boolean
        get() = ok && capabilities?.isCurrentPerClipApi == true

    val complete: Boolean
        get() = contractValid && capabilities?.features?.complete == true

    val supportsKnowledgeBases: Boolean
        get() = contractValid && capabilities?.features?.knowledgeBases == true

    val supportsRecall: Boolean
        get() = contractValid && capabilities?.features?.recall == true

    val supportsTopicReadModel: Boolean
        get() = contractValid && capabilities?.features?.qualityReadModel == true

    val supportsMemoryPlanet: Boolean
        get() = contractValid && capabilities?.features?.memoryPlanet == true

    val supportsKnowledgeListV2: Boolean
        get() = contractValid && capabilities?.features?.knowledgeListV2 == true &&
            capabilities.contracts.knowledgeList == AppCapabilities.EXPECTED_KNOWLEDGE_LIST
}

enum class AppFeatureAvailability {
    CHECKING,
    AVAILABLE,
    UNAVAILABLE,
}

fun AppCapabilityResult?.featureAvailability(feature: (AppFeatures) -> Boolean): AppFeatureAvailability = when {
    this == null -> AppFeatureAvailability.CHECKING
    contractValid && capabilities?.features?.let(feature) == true -> AppFeatureAvailability.AVAILABLE
    else -> AppFeatureAvailability.UNAVAILABLE
}

object AppCapabilitySummary {
    fun settings(result: AppCapabilityResult?): String = when {
        result == null -> "正在检查服务兼容状态"
        result.complete -> "完整 PerClip API 已兼容"
        result.contractValid -> "基础保存正常；部分功能可用"
        else -> "基础保存可用；完整功能不可用"
    }
}

fun combinedFeatureAvailability(vararg availability: AppFeatureAvailability): AppFeatureAvailability = when {
    availability.all { it == AppFeatureAvailability.AVAILABLE } -> AppFeatureAvailability.AVAILABLE
    availability.any { it == AppFeatureAvailability.CHECKING } -> AppFeatureAvailability.CHECKING
    else -> AppFeatureAvailability.UNAVAILABLE
}
