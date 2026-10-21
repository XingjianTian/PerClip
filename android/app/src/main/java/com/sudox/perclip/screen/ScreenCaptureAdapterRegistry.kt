package com.sudox.perclip.screen

import com.sudox.perclip.screen.adapters.XhsShareLinkAdapter

object ScreenCaptureAdapterRegistry {
    private val adapters: List<AppScreenAdapter> = listOf(
        XhsShareLinkAdapter(),
    )

    fun adapterFor(packageName: String): AppScreenAdapter? {
        return adapters.firstOrNull { it.canHandle(packageName) }
    }
}
