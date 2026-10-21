package com.sudox.perclip.ui

import com.sudox.perclip.knowledge.KnowledgeBaseApiResult
import com.sudox.perclip.knowledge.RagflowProbeSummary
import org.junit.Assert.assertEquals
import org.junit.Test

class RagflowConnectionPresentationTest {
    @Test fun reachableProbeIsPresentedAsConnected() {
        val result = success("reachable", configured = true, datasetList = "true")
        val status = RagflowConnectionPresentation.status(checking = false, result = result)

        assertEquals("连接正常", status.title)
        assertEquals(RagflowConnectionTone.SUCCESS, status.tone)
    }

    @Test fun disabledProbeDoesNotMisreportCoreAsDisconnected() {
        val result = success("disabled", configured = false, datasetList = "not_configured")
        val status = RagflowConnectionPresentation.status(checking = false, result = result)

        assertEquals("服务端未配置", status.title)
        assertEquals(RagflowConnectionTone.NEUTRAL, status.tone)
        assertEquals(true, status.detail.contains("PerClip Core 可继续使用"))
    }

    @Test fun unreachableAndUnknownApiRemainDistinct() {
        assertEquals(
            "无法连接 RAGFlow",
            RagflowConnectionPresentation.status(false, success("unreachable", true, "unknown")).title,
        )
        assertEquals(
            "接口状态待确认",
            RagflowConnectionPresentation.status(false, success("unknown_api", true, "unknown")).title,
        )
    }

    @Test fun endpointFailureUsesSafeMessage() {
        val status = RagflowConnectionPresentation.status(
            checking = false,
            result = KnowledgeBaseApiResult.failure("当前服务未提供检查入口"),
        )
        assertEquals("检查失败", status.title)
        assertEquals("当前服务未提供检查入口", status.detail)
        assertEquals(RagflowConnectionTone.ERROR, status.tone)
    }

    private fun success(status: String, configured: Boolean, datasetList: String) =
        KnowledgeBaseApiResult.success(
            RagflowProbeSummary(
                status = status,
                configured = configured,
                capabilities = mapOf("dataset_list" to datasetList),
            ),
        )
}
