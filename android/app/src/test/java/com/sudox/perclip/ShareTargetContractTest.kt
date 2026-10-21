package com.sudox.perclip

import com.sudox.perclip.share.SharingShortcutPublisher
import java.nio.file.Paths
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element
import org.w3c.dom.Node

class ShareTargetContractTest {
    @Test
    fun manifestReceivesMvpSingleShareMimeTypes() {
        val sendFilter = manifestIntentFilters()
            .single { filter -> filter.hasAction("android.intent.action.SEND") }

        assertEquals(
            setOf(
                "text/plain",
                "image/*",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/octet-stream",
                "*/*",
            ),
            sendFilter.mimeTypes(),
        )
        assertTrue(sendFilter.hasCategory("android.intent.category.DEFAULT"))
    }

    @Test
    fun manifestReceivesMvpMultiShareMimeTypes() {
        val sendMultipleFilter = manifestIntentFilters()
            .single { filter -> filter.hasAction("android.intent.action.SEND_MULTIPLE") }

        assertEquals(
            setOf(
                "image/*",
                "application/pdf",
                "application/octet-stream",
                "*/*",
            ),
            sendMultipleFilter.mimeTypes(),
        )
        assertTrue(sendMultipleFilter.hasCategory("android.intent.category.DEFAULT"))
    }

    @Test
    fun shortcutShareTargetMatchesDynamicShareShortcutCategory() {
        val shareTarget = shortcutsElements("share-target").single()

        assertEquals(
            "com.sudox.perclip.ShareCaptureActivity",
            shareTarget.androidAttribute("targetClass"),
        )
        assertEquals(
            SharingShortcutPublisher.SAVE_TO_PERSONALCLIPS_CATEGORY,
            shareTarget.childElements("category").single().androidAttribute("name"),
        )
        assertEquals(
            setOf(
                "text/plain",
                "image/*",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/octet-stream",
                "*/*",
            ),
            shareTarget.childElements("data").mapTo(mutableSetOf()) { it.androidAttribute("mimeType") },
        )
    }

    @Test
    fun staticShortcutsRouteToExpectedAppActions() {
        val shortcutsById = shortcutsElements("shortcut")
            .associateBy { shortcut -> shortcut.androidAttribute("shortcutId") }

        assertEquals(
            PerClipActions.ACTION_NEW_NOTE,
            shortcutsById.getValue("quick_note").childElements("intent").single().androidAttribute("action"),
        )
        assertEquals(
            PerClipActions.ACTION_RECENTS,
            shortcutsById.getValue("recents").childElements("intent").single().androidAttribute("action"),
        )
        assertEquals(
            PerClipActions.ACTION_SETTINGS,
            shortcutsById.getValue("settings").childElements("intent").single().androidAttribute("action"),
        )
    }

    @Test
    fun clipboardBridgeActivityUsesTransparentPrivateTask() {
        val bridgeActivity = document("src/main/AndroidManifest.xml")
            .getElementsByTagName("activity")
            .asElements()
            .single { activity ->
                activity.androidAttribute("name") == ".ClipboardBridgeActivity"
            }

        assertEquals("false", bridgeActivity.androidAttribute("exported"))
        assertEquals("true", bridgeActivity.androidAttribute("excludeFromRecents"))
        assertEquals("true", bridgeActivity.androidAttribute("noHistory"))
        assertEquals("singleTask", bridgeActivity.androidAttribute("launchMode"))
        assertEquals("com.sudox.perclip.capture", bridgeActivity.androidAttribute("taskAffinity"))
        assertEquals("@style/Theme.PerClip.TransparentBridge", bridgeActivity.androidAttribute("theme"))
    }

    @Test
    fun systemShareUsesDedicatedTransientActivity() {
        val activities = document("src/main/AndroidManifest.xml")
            .getElementsByTagName("activity")
            .asElements()
        val mainActivity = activities.single { it.androidAttribute("name") == ".MainActivity" }
        val shareActivity = activities.single { it.androidAttribute("name") == ".ShareCaptureActivity" }

        assertTrue(mainActivity.childElements("intent-filter").none { it.hasAction("android.intent.action.SEND") })
        assertTrue(mainActivity.childElements("intent-filter").none { it.hasAction("android.intent.action.SEND_MULTIPLE") })
        assertEquals("true", shareActivity.androidAttribute("exported"))
        assertEquals("true", shareActivity.androidAttribute("excludeFromRecents"))
        assertEquals("true", shareActivity.androidAttribute("noHistory"))
        assertEquals("", shareActivity.androidAttribute("taskAffinity"))
        assertEquals("@style/Theme.PerClip.TransparentBridge", shareActivity.androidAttribute("theme"))
        assertTrue(shareActivity.childElements("intent-filter").any { it.hasAction("android.intent.action.SEND") })
        assertTrue(shareActivity.childElements("intent-filter").any { it.hasAction("android.intent.action.SEND_MULTIPLE") })
    }

    private fun manifestIntentFilters(): List<Element> {
        return document("src/main/AndroidManifest.xml")
            .getElementsByTagName("intent-filter")
            .asElements()
    }

    private fun shortcutsElements(tagName: String): List<Element> {
        return document("src/main/res/xml/shortcuts.xml")
            .getElementsByTagName(tagName)
            .asElements()
    }

    private fun document(path: String) = DocumentBuilderFactory.newInstance().apply {
        isNamespaceAware = true
    }
        .newDocumentBuilder()
        .parse(Paths.get(path).toFile())

    private fun Element.hasAction(action: String): Boolean {
        return childElements("action").any { element ->
            element.androidAttribute("name") == action
        }
    }

    private fun Element.hasCategory(category: String): Boolean {
        return childElements("category").any { element ->
            element.androidAttribute("name") == category
        }
    }

    private fun Element.mimeTypes(): Set<String> {
        return childElements("data").mapTo(mutableSetOf()) { element ->
            element.androidAttribute("mimeType")
        }
    }

    private fun Element.childElements(tagName: String): List<Element> {
        return getElementsByTagName(tagName).asElements()
    }

    private fun Element.androidAttribute(name: String): String {
        return attributes.getNamedItemNS(ANDROID_NAMESPACE, name).nodeValue
    }

    private fun org.w3c.dom.NodeList.asElements(): List<Element> {
        return (0 until length).mapNotNull { index ->
            item(index).takeIf { node -> node.nodeType == Node.ELEMENT_NODE } as? Element
        }
    }

    companion object {
        private const val ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
    }
}
