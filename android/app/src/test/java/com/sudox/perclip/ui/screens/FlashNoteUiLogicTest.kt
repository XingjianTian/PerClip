package com.sudox.perclip.ui.screens

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FlashNoteUiLogicTest {
    @Test
    fun emptyPrimaryActionStaysEnabledForInlineGuidance() {
        assertTrue(FlashNoteUiLogic.emptyPrimaryActionEnabled(isRecording = false))
        assertFalse(FlashNoteUiLogic.canSaveText("   "))
    }

    @Test
    fun recordingTemporarilyDisablesPrimaryAction() {
        assertFalse(FlashNoteUiLogic.emptyPrimaryActionEnabled(isRecording = true))
    }

    @Test
    fun nonBlankTextCanBeSaved() {
        assertTrue(FlashNoteUiLogic.canSaveText("一条闪记"))
    }

    @Test
    fun primaryActionExplainsLocalQueueUntilNasIsConfigured() {
        assertEquals("保存闪记", FlashNoteUiLogic.primaryActionLabel())
    }

    @Test
    fun localFailurePreservesDraftAndSuccessClearsIt() {
        assertFalse(FlashNoteUiLogic.shouldClearDraftAfterSave(savedLocally = false))
        assertTrue(FlashNoteUiLogic.shouldClearDraftAfterSave(savedLocally = true))
    }
}
