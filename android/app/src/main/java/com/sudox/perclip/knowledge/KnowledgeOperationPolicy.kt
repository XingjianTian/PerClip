package com.sudox.perclip.knowledge

import com.sudox.perclip.StartTab
import com.sudox.perclip.capabilities.AppCapabilityResult

object KnowledgeOperationPolicy {
    fun canBrowse(result: AppCapabilityResult?): Boolean = result?.supportsKnowledgeBases == true

    fun canCrud(result: AppCapabilityResult?): Boolean = canBrowse(result)

}

object KnowledgeBaseLoadPolicy {
    fun isRemoteListSurface(selectedTab: Int, managementOpen: Boolean): Boolean =
        selectedTab in setOf(StartTab.Recents.index, StartTab.Recall.index) && !managementOpen

    fun shouldLoad(
        isKnowledgeSurface: Boolean,
        knowledgeAvailable: Boolean,
        configurationFingerprint: String,
        loadedFingerprint: String,
        loading: Boolean,
    ): Boolean = isKnowledgeSurface && knowledgeAvailable && !loading && configurationFingerprint != loadedFingerprint
}
