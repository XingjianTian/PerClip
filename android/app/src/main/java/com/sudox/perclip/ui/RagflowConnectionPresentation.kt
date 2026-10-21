package com.sudox.perclip.ui

import com.sudox.perclip.knowledge.KnowledgeBaseApiResult
import com.sudox.perclip.knowledge.RagflowProbeSummary

enum class RagflowConnectionTone {
    NEUTRAL,
    SUCCESS,
    WARNING,
    ERROR,
}

data class RagflowConnectionStatus(
    val title: String,
    val detail: String,
    val tone: RagflowConnectionTone,
)

object RagflowConnectionPresentation {
    fun status(
        checking: Boolean,
        result: KnowledgeBaseApiResult<RagflowProbeSummary>?,
    ): RagflowConnectionStatus {
        if (checking) return RagflowConnectionStatus("正在检查", "通过 PerClip 服务端执行只读检查…", RagflowConnectionTone.NEUTRAL)
        if (result == null) return RagflowConnectionStatus("尚未检查", "不会在 Android 保存 RAGFlow 密钥。", RagflowConnectionTone.NEUTRAL)
        if (!result.ok || result.value == null) {
            return RagflowConnectionStatus(
                "检查失败",
                result.message.ifBlank { "当前无法读取 RAGFlow 状态。" },
                RagflowConnectionTone.ERROR,
            )
        }

        val summary = result.value
        val adapterStatus = summary.status.lowercase()
        val datasetList = summary.capabilities["dataset_list"].orEmpty().lowercase()
        return when {
            !summary.configured || adapterStatus == "disabled" -> RagflowConnectionStatus(
                "服务端未配置",
                "PerClip Core 可继续使用；RAGFlow 增强能力当前关闭。",
                RagflowConnectionTone.NEUTRAL,
            )
            adapterStatus == "reachable" || datasetList in setOf("true", "enabled", "reachable") -> RagflowConnectionStatus(
                "连接正常",
                "只读数据集检查已通过。",
                RagflowConnectionTone.SUCCESS,
            )
            adapterStatus == "unreachable" -> RagflowConnectionStatus(
                "无法连接 RAGFlow",
                "PerClip 服务端已配置，但当前无法访问 RAGFlow。",
                RagflowConnectionTone.ERROR,
            )
            adapterStatus == "unknown_api" -> RagflowConnectionStatus(
                "接口状态待确认",
                "已连接到目标服务，但只读数据集接口不兼容或响应未知。",
                RagflowConnectionTone.WARNING,
            )
            else -> RagflowConnectionStatus(
                "已配置，状态待确认",
                "检查入口可用，但尚未确认只读数据集能力。",
                RagflowConnectionTone.WARNING,
            )
        }
    }
}
