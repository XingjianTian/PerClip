package com.sudox.perclip.ui.recall

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RecallConfigurationReloadTest {
    @Test
    fun configurationChangeInvalidatesOverviewOnce() {
        val holder = RecallStateHolder()
        assertTrue(holder.prepareOverviewForConfiguration("server-a|1"))
        assertFalse(holder.prepareOverviewForConfiguration("server-a|1"))
        assertTrue(holder.prepareOverviewForConfiguration("server-b|2"))
        assertTrue(holder.state.overview.isEmpty)
    }

    @Test
    fun capabilityTransitionInvalidatesOverviewExactlyOnce() {
        val holder = RecallStateHolder()
        assertTrue(holder.prepareOverviewForConfiguration("server|UNAVAILABLE"))
        assertFalse(holder.prepareOverviewForConfiguration("server|UNAVAILABLE"))
        assertTrue(holder.prepareOverviewForConfiguration("server|AVAILABLE"))
        assertFalse(holder.prepareOverviewForConfiguration("server|AVAILABLE"))
    }

    @Test fun fakeRepositoryIsCalledOnceForAutomaticLoadAndOnceForManualRefresh() {
        val holder = RecallStateHolder()
        var calls = 0
        val fakeRepository = { calls += 1 }
        assertTrue(RecallOverviewLoadPolicy.requestIfNeeded(holder.state, fakeRepository))
        holder.update(RecallUiReducer::overviewLoading)
        assertFalse(RecallOverviewLoadPolicy.requestIfNeeded(holder.state, fakeRepository))
        assertEquals(1, calls)
        fakeRepository()
        assertEquals(2, calls)
    }
}
