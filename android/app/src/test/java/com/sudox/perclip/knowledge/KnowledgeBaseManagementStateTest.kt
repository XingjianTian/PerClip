package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeBaseManagementStateTest {
    @Test
    fun capabilityFailureDoesNotHideSuccessfulList() {
        val list = listOf(KnowledgeBaseSummary("default", "我的知识库", isDefault = true))
        val state = KnowledgeBaseManagementState(listLoading = true, capabilitiesLoading = true)
            .withListResult(KnowledgeBaseApiResult.success(KnowledgeBaseListResponse(true, list)), 123L)
            .withCapabilitiesResult(KnowledgeBaseApiResult.failure("暂不可用"))

        assertEquals(list, state.knowledgeBases)
        assertEquals("暂不可用", state.capabilitiesError)
        assertFalse(state.showEmpty)
        assertEquals("我的知识库", state.defaultName)
    }

    @Test
    fun emptyRequiresSuccessfulListResponse() {
        assertFalse(KnowledgeBaseManagementState(listError = "404").showEmpty)
        assertTrue(KnowledgeBaseManagementState(listLoadedSuccessfully = true).showEmpty)
    }

    @Test fun mutationSuccessAndListFailureAlwaysStopsLoadingAndKeepsCachedList() {
        val cached = listOf(KnowledgeBaseSummary("cached", "缓存"))
        val state = KnowledgeBaseManagementState(listLoading = true, knowledgeBases = cached)
            .finishMutation("知识库已更新。", KnowledgeBaseApiResult.failure("列表失败"), 1L)
        assertFalse(state.listLoading)
        assertEquals(cached, state.knowledgeBases)
        assertEquals("知识库已更新。", state.mutationMessage)
        assertEquals("列表失败", state.listError)
    }

    @Test fun mutationFailureAndListFailurePreserveBothMessages() {
        val state = KnowledgeBaseManagementState(listLoading = true)
            .finishMutation("操作失败", KnowledgeBaseApiResult.failure("列表失败"), 1L)
        assertFalse(state.listLoading)
        assertEquals("操作失败", state.mutationMessage)
        assertEquals("列表失败", state.listError)
    }

    @Test fun mutationAndRefreshSuccessConvergeWithFreshList() {
        val fresh = listOf(KnowledgeBaseSummary("fresh", "新列表"))
        val state = KnowledgeBaseManagementState(listLoading = true)
            .finishMutation("操作成功", KnowledgeBaseApiResult.success(KnowledgeBaseListResponse(true, fresh)), 2L)
        assertFalse(state.listLoading)
        assertEquals(fresh, state.knowledgeBases)
        assertEquals("", state.listError)
    }
}
