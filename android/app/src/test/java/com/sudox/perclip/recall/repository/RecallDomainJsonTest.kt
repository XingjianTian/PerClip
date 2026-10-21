package com.sudox.perclip.recall.repository

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecallDomainJsonTest {
    @Test fun parsesCanonicalDomainWithoutLayoutFields() {
        val domain = RecallDomainJson.parseDomain("""{"ok":true,"window":{"days":30,"start":"2026-07-01","end":"2026-07-31"},"canonical_snapshot_key":"canonical-safe-key","snapshot_key":"safe-key","topics":[{"id":"topic:ai","label":"AI","short_label":"AI","clip_count":1,"weight":0.8,"size_weight":0.7,"color_slot":2,"icon_slot":"education","label_priority":0.9,"rotation_seed":12,"viewed_count":4,"deferred_count":2,"opened_original_count":1,"last_recalled_at":"2026-07-30T00:00:00Z"}],"memories":[{"id":"clip:42","clip_id":"42","primary_topic_id":"topic:ai","topic_ids":["topic:ai"],"label":"A safe title","safe_excerpt":"safe","weight":0.4,"size_weight":0.3,"label_priority":0.5,"rotation_seed":13,"view_count":3,"defer_count":1,"opened_original_count":2,"last_viewed_at":"2026-07-29T00:00:00Z","last_deferred_at":"2026-07-28T00:00:00Z"}],"relations":[{"source":"topic:ai","target":"clip:42","type":"contains","weight":1.0}],"presentation_defaults":{"visible_label_count":3,"label_rotation_seconds":8,"default_days":14,"include_memory_labels":false,"client_owns_layout":true,"client_owns_animation":true}}""")
        assertEquals("topic:ai", domain.topics.single().id)
        assertEquals("clip:42", domain.memories.single().id)
        assertTrue(domain.memories.single().id.startsWith("clip:"))
        assertEquals("contains", domain.relations.single().type)
        assertEquals(14, domain.presentationDefaults.defaultDays)
        assertFalse(domain.presentationDefaults.includeMemoryLabels)
        assertEquals("canonical-safe-key", domain.canonicalSnapshotKey)
        assertEquals(4, domain.topics.single().viewedCount)
        assertEquals(2, domain.topics.single().deferredCount)
        assertEquals("2026-07-30T00:00:00Z", domain.topics.single().lastRecalledAt)
        assertEquals(3, domain.memories.single().viewCount)
        assertEquals(1, domain.memories.single().deferCount)
        assertEquals(2, domain.memories.single().openedOriginalCount)
        assertEquals("2026-07-29T00:00:00Z", domain.memories.single().lastViewedAt)
        assertFalse(RecallDomainSnapshot::class.java.declaredFields.any { it.name.contains("coordinate", true) || it.name.contains("orbit", true) || it.name.contains("angle", true) })
    }

    @Test fun parsesResurfaceAndPreferencesAndCreatesSafeBodies() {
        val page = RecallDomainJson.parseResurface("""{"ok":true,"snapshot_key":"safe","cursor":"first","next_cursor":"next","items":[{"clip_id":"7","topic_id":"topic:a","title":"Safe","reason_codes":["topic_diversity"]}]}""")
        val preferences = RecallDomainJson.parsePreferences("""{"ok":true,"preferences":{"visible_label_count":4,"label_rotation_seconds":10,"default_days":14,"preferred_topic_ids":["topic:a"],"muted_topic_ids":["topic:b"],"include_memory_labels":false}}""")
        val interaction = JSONObject(RecallDomainJson.interactionBody(RecallInteractionRequest("graph", "open_memory", nodeId = "clip:7", metadata = RecallInteractionMetadata(position = 2, source = "recall_graph"))))
        val patch = JSONObject(RecallDomainJson.preferencesPatchBody(RecallPreferencesPatch(visibleLabelCount = 4, mutedTopicIds = listOf("topic:b"))))
        assertEquals("7", page.items.single().clipId); assertEquals("topic_diversity", page.items.single().reasonCodes.single())
        assertEquals(4, preferences.visibleLabelCount); assertFalse(preferences.includeMemoryLabels)
        assertEquals("clip:7", interaction.getString("node_id")); assertEquals(2, interaction.getJSONObject("metadata").getInt("position"))
        assertEquals(4, patch.getInt("visible_label_count")); assertFalse(patch.toString().contains("authorization", true))
    }

    @Test fun parsesBothInteractionResponseShapes() {
        val current = RecallDomainJson.parseInteraction("""{"ok":true,"event_id":9,"replayed":true,"target":{"node_id":"clip:7","topic_id":"topic:a","clip_id":"7"}}""")
        val legacy = RecallDomainJson.parseInteraction("""{"ok":true,"replay":true,"interaction":{"id":"legacy-1"}}""")
        assertEquals("9", current.eventId); assertTrue(current.replayed); assertEquals("clip:7", current.target.nodeId)
        assertEquals("legacy-1", legacy.eventId); assertTrue(legacy.replayed)
    }

    @Test fun suppressionPageKeepsBoundedCursorMetadataAndPublicIdentity() {
        val page = RecallDomainJson.parseSuppressions(
            """{"ok":true,"cursor":"kc_current","previous_cursor":"kc_previous","next_cursor":"kc_next","limit":50,"items":[{"clip_id":"pc_00000000000000000000000000000001","title":"可恢复"}]}""",
        )
        assertEquals(50, page.limit)
        assertEquals("kc_previous", page.previousCursor)
        assertEquals("kc_next", page.nextCursor)
        assertEquals("可恢复", page.items.single().title)
        assertTrue(
            runCatching {
                RecallDomainJson.parseSuppressions(
                    """{"ok":true,"items":[{"clip_id":"internal-1","title":"bad"}]}""",
                )
            }.isFailure,
        )
    }

    @Test fun malformedDomainJsonFails() {
        assertTrue(runCatching { RecallDomainJson.parseDomain("{bad") }.isFailure)
    }

    @Test fun missingNewDomainFieldsRemainBackwardCompatible() {
        val domain = RecallDomainJson.parseDomain("""{"ok":true,"window":{},"snapshot_key":"legacy"}""")
        assertEquals("", domain.canonicalSnapshotKey)
        assertTrue(domain.topics.isEmpty())
        assertTrue(domain.memories.isEmpty())
    }
}
