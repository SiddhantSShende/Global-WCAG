package com.a11yaudit.harness

import android.content.Intent
import android.graphics.Bitmap
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import com.google.android.apps.common.testing.accessibility.framework.AccessibilityCheckPreset
import com.google.android.apps.common.testing.accessibility.framework.AccessibilityHierarchyCheck
import com.google.android.apps.common.testing.accessibility.framework.AccessibilityHierarchyCheckResult
import com.google.android.apps.common.testing.accessibility.framework.uielement.AccessibilityHierarchyAndroid
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.Locale

/**
 * Black-box accessibility audit.
 *
 * Runs as an instrumentation test but audits ANOTHER app: it launches the target
 * package, then for each screen snapshots the foreground window's
 * AccessibilityNodeInfo tree via UiAutomation, builds an ATF AccessibilityHierarchy
 * from it, and runs Google's AccessibilityCheckPreset.LATEST checks. Results +
 * screenshots are written to the app's external files dir for adb to pull.
 *
 * Instrumentation args:  targetPackage, maxScreens
 *
 * Run (from atf.py):
 *   adb shell am instrument -w \
 *     -e targetPackage <pkg> -e maxScreens 20 \
 *     com.a11yaudit.harness.test/androidx.test.runner.AndroidJUnitRunner
 *
 * NOTE: exact ATF API signatures vary across versions — verified against the
 * 3.x/4.x line; [re-verify] AccessibilityHierarchyAndroid.newBuilder overloads if
 * the resolved ATF version differs.
 */
@RunWith(AndroidJUnit4::class)
class AtfAuditTest {

    private val instr = InstrumentationRegistry.getInstrumentation()
    private val args = InstrumentationRegistry.getArguments()
    private val ctx = instr.context
    private val device = UiDevice.getInstance(instr)

    @Test
    fun auditApp() {
        val targetPackage = args.getString("targetPackage").orEmpty()
        val maxScreens = (args.getString("maxScreens") ?: "20").toIntOrNull() ?: 20
        val outDir = File(ctx.getExternalFilesDir(null), "a11y").apply { mkdirs() }
        val uiAutomation = instr.uiAutomation

        if (targetPackage.isNotEmpty()) {
            ctx.packageManager.getLaunchIntentForPackage(targetPackage)?.let {
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                ctx.startActivity(it)
            }
            device.waitForIdle(3000)
        }

        val checks = AccessibilityCheckPreset
            .getAccessibilityHierarchyChecksForPreset(AccessibilityCheckPreset.LATEST)

        val screens = JSONArray()
        var index = 0

        fun auditCurrent() {
            val root: AccessibilityNodeInfo = uiAutomation.rootInActiveWindow ?: return
            val hierarchy = AccessibilityHierarchyAndroid.newBuilder(root, ctx).build()

            val results = JSONArray()
            for (check in checks) {
                val checkResults: List<AccessibilityHierarchyCheckResult> =
                    check.runCheckOnHierarchy(hierarchy)
                for (r in checkResults) {
                    val type = r.type.name  // ERROR / WARNING / INFO / NOT_RUN / SUPPRESSED / RESOLVED
                    if (type != "ERROR" && type != "WARNING") continue
                    val element = r.element
                    val obj = JSONObject()
                        .put("checkClass", check.javaClass.simpleName)
                        .put("type", type)
                        .put("message", r.getMessage(Locale.ENGLISH).toString())
                        .put("viewId", element?.resourceName?.orElse("") ?: "")
                    element?.boundsInScreen?.let { b ->
                        obj.put("bounds", JSONObject()
                            .put("left", b.left).put("top", b.top)
                            .put("right", b.right).put("bottom", b.bottom))
                    }
                    results.put(obj)
                }
            }

            val shot = File(outDir, "screen_$index.png")
            try {
                val bmp: Bitmap = uiAutomation.takeScreenshot()
                shot.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 90, it) }
            } catch (_: Exception) { }

            screens.put(JSONObject()
                .put("index", index)
                .put("package", root.packageName?.toString() ?: "")
                .put("screenshot", shot.absolutePath)
                .put("results", results))
            index++
        }

        auditCurrent()  // entry screen

        // Shallow crawl: tap each clickable node, audit, back out.
        val clickables = device.findObjects(By.clickable(true))
        for (obj in clickables) {
            if (index >= maxScreens) break
            try {
                obj.click()
                device.waitForIdle(2000)
                auditCurrent()
                device.pressBack()
                device.waitForIdle(1500)
            } catch (_: Exception) { }
        }

        File(outDir, "results.json").writeText(screens.toString())
    }
}
