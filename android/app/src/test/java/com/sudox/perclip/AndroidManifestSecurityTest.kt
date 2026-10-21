package com.sudox.perclip

import java.nio.file.Paths
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class AndroidManifestSecurityTest {
    @Test
    fun disablesAppDataBackupBecauseSettingsContainMobileToken() {
        val document = manifestDocument()
        val application = document.getElementsByTagName("application").item(0)
        val attributes = application.attributes

        assertEquals(
            "false",
            attributes.getNamedItemNS(ANDROID_NAMESPACE, "allowBackup").nodeValue,
        )
        assertEquals(
            "false",
            attributes.getNamedItemNS(ANDROID_NAMESPACE, "fullBackupContent").nodeValue,
        )
    }

    @Test
    fun declaresAccessibilityServiceBehindBindPermission() {
        val document = manifestDocument()
        val services = document.getElementsByTagName("service")
        var accessibilityService: org.w3c.dom.Node? = null
        for (index in 0 until services.length) {
            val service = services.item(index)
            if (service.attributes.getNamedItemNS(ANDROID_NAMESPACE, "name").nodeValue == ".screen.PerClipAccessibilityService") {
                accessibilityService = service
                break
            }
        }

        assertNotNull(accessibilityService)
        requireNotNull(accessibilityService)
        assertEquals(
            "android.permission.BIND_ACCESSIBILITY_SERVICE",
            accessibilityService.attributes.getNamedItemNS(ANDROID_NAMESPACE, "permission").nodeValue,
        )
    }

    @Test
    fun captureTriggerReceiverIsInternalOnly() {
        val document = manifestDocument()
        val receivers = document.getElementsByTagName("receiver")
        var captureReceiver: org.w3c.dom.Node? = null
        for (index in 0 until receivers.length) {
            val receiver = receivers.item(index)
            if (receiver.attributes.getNamedItemNS(ANDROID_NAMESPACE, "name").nodeValue == ".screen.CaptureTriggerReceiver") {
                captureReceiver = receiver
                break
            }
        }

        assertNotNull(captureReceiver)
        requireNotNull(captureReceiver)
        assertEquals(
            "false",
            captureReceiver.attributes.getNamedItemNS(ANDROID_NAMESPACE, "exported").nodeValue,
        )
    }

    private fun manifestDocument() = DocumentBuilderFactory.newInstance().apply {
        isNamespaceAware = true
    }
        .newDocumentBuilder()
        .parse(Paths.get("src/main/AndroidManifest.xml").toFile())

    companion object {
        private const val ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
    }
}
