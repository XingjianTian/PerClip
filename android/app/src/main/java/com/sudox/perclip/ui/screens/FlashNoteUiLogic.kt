package com.sudox.perclip.ui.screens

object FlashNoteUiLogic {
    fun emptyPrimaryActionEnabled(isRecording: Boolean): Boolean = !isRecording

    fun canSaveText(text: String): Boolean = text.isNotBlank()

    fun shouldClearDraftAfterSave(savedLocally: Boolean): Boolean = savedLocally

    fun primaryActionLabel(): String = "保存闪记"
}
