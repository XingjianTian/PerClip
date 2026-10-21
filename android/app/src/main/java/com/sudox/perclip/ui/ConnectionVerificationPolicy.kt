package com.sudox.perclip.ui

import com.sudox.perclip.capabilities.AppCapabilityResult

data class ConnectionVerificationSummary(
    val shouldRequeue: Boolean,
    val advancedStatus: String,
)

object ConnectionVerificationPolicy {
    fun evaluate(healthOk: Boolean, capability: AppCapabilityResult?): ConnectionVerificationSummary {
        if (!healthOk) return ConnectionVerificationSummary(false, "保存连接失败")
        val advanced = when {
            capability == null -> "正在检查高级功能"
            capability.complete -> "完整功能可用"
            capability.contractValid -> "部分功能可用"
            else -> "版本不兼容，高级功能不可用"
        }
        return ConnectionVerificationSummary(true, advanced)
    }
}
