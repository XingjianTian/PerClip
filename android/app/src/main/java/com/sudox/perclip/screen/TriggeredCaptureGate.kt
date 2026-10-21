package com.sudox.perclip.screen

internal class TriggeredCaptureGate {
    private var active = false
    private var completed = false

    @Synchronized
    fun tryStart(): Boolean {
        if (active) return false
        active = true
        completed = false
        return true
    }

    @Synchronized
    fun tryComplete(): Boolean {
        if (!active || completed) return false
        completed = true
        return true
    }

    @Synchronized
    fun release() {
        active = false
        completed = false
    }

    @Synchronized
    fun isActive(): Boolean = active
}
