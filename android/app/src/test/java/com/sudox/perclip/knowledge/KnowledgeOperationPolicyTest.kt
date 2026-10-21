package com.sudox.perclip.knowledge

import com.sudox.perclip.capabilities.AppCapabilities
import com.sudox.perclip.capabilities.AppCapabilityFailure
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppFeatures
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeOperationPolicyTest {
    @Test fun oldServerCannotCrud() {
        val old = AppCapabilityResult(false, failure = AppCapabilityFailure.CONTRACT_MISSING, message = "old")
        assertFalse(KnowledgeOperationPolicy.canCrud(old))
    }

    @Test fun partialKnowledgeContractCanBrowseAndCrud() {
        val partial = result(knowledge = true, routing = true, recall = false)
        assertTrue(KnowledgeOperationPolicy.canBrowse(partial))
        assertTrue(KnowledgeOperationPolicy.canCrud(partial))
    }

    private fun result(knowledge: Boolean, routing: Boolean, recall: Boolean) = AppCapabilityResult(
        true,
        AppCapabilities(AppCapabilities.EXPECTED_CONTRACT, AppCapabilities.EXPECTED_SERVICE, AppFeatures(knowledge, routing, recall, true, true, true, true)),
        if (knowledge && routing && recall) AppCapabilityFailure.NONE else AppCapabilityFailure.FEATURES_INCOMPLETE,
        "result",
    )
}
