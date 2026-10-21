package com.sudox.perclip

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StartTabTest {
    @Test
    fun usesStableFourTabIndices() {
        assertEquals(0, StartTab.Save.index)
        assertEquals(1, StartTab.Recents.index)
        assertEquals(2, StartTab.Recall.index)
        assertEquals(3, StartTab.Settings.index)
    }

    @Test
    fun mapsShortcutActionsToTabs() {
        assertEquals(StartTab.Save, StartTab.fromAction(null))
        assertEquals(StartTab.Save, StartTab.fromAction(PerClipActions.ACTION_NEW_NOTE))
        assertEquals(StartTab.Save, StartTab.fromAction(PerClipActions.ACTION_CAPTURE_SCREEN))
        assertEquals(StartTab.Save, StartTab.fromAction(PerClipActions.ACTION_COMPLETE_AUTO_CAPTURE))
        assertEquals(StartTab.Recents, StartTab.fromAction(PerClipActions.ACTION_RECENTS))
        assertEquals(StartTab.Settings, StartTab.fromAction(PerClipActions.ACTION_SETTINGS))
    }

    @Test
    fun appliesOnlyNewNavigationRevisions() {
        assertTrue(LaunchNavigationPolicy.shouldApply(navigationRevision = 1, appliedNavigationRevision = 0))
        assertFalse(LaunchNavigationPolicy.shouldApply(navigationRevision = 1, appliedNavigationRevision = 1))
        assertTrue(LaunchNavigationPolicy.shouldApply(navigationRevision = 2, appliedNavigationRevision = 1))
    }
}
