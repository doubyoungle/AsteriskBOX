// Copyright 2026, AsteriskBOX contributors
// SPDX-License-Identifier: GPL-3.0

package features.updater

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UpdateReleaseTest {
    private val repository = "example/AsteriskBOX"
    private val tag = "v1.2.1-r.1"
    private val abis = listOf("arm64-v8a", "armeabi-v7a")
    private val digest = "sha256:${"a".repeat(64)}"

    @Test
    fun comparesVersionCodesAndPrefersDeviceAbis() {
        val arm = apk("arm64-v8a")
        val secondary = apk("armeabi-v7a")
        val universal = apk("universal")
        val metadata = release(universal, secondary, arm)
        assertEquals("arm64-v8a", select(metadata, 659)?.abi)
        assertEquals("armeabi-v7a", select(release(universal, secondary), 659)?.abi)
        assertEquals("universal", select(release(universal), 659)?.abi)
        assertNull(select(release(apk("x86")), 659))
        assertNull(select(metadata, 660))
        assertNull(select(metadata, 661))
    }

    @Test
    fun rejectsDifferentBuildsAndInvalidDownloadMetadata() {
        val valid = release(apk("arm64-v8a"))
        assertNull(select(valid.replace("AsteriskBOX_", "AsteriskBOX_meow-"), 659))
        assertNull(select(valid.replace("https://github.com", "https://example.com"), 659))
        assertNull(select(valid.replace(digest, ""), 659))
        assertNull(select(valid.replace("\"versionCode\":660", "\"versionCode\":661"), 659))
        assertNull(select(valid.replace("\"tag_name\"", "\"prerelease\":true,\"tag_name\""), 659))
    }

    @Test
    fun usesStaticManifestWhenTheApiIsRateLimited() {
        for (status in listOf(403, 429)) {
            val urls = mutableListOf<String>()
            val metadata = loadUpdateMetadata(repository) { url ->
                urls.add(url)
                if (urls.size == 1) MetadataResponse(status)
                else MetadataResponse(200, release(apk("arm64-v8a")))
            }
            assertEquals(
                listOf(
                    "https://api.github.com/repos/$repository/releases/latest",
                    "https://github.com/$repository/releases/latest/download/update-manifest.json",
                ),
                urls,
            )
            assertEquals(660L, select(requireNotNull(metadata), 659)?.versionCode)
        }
        assertNull(loadUpdateMetadata(repository) { MetadataResponse(404) })
    }

    private fun select(metadata: String, installed: Long) = selectUpdate(metadata, repository, installed, abis)

    private fun release(vararg assets: String) =
        """{"versionCode":660,"tag_name":"$tag","assets":[${assets.joinToString(",")}]}"""

    private fun apk(abi: String): String {
        val name = "AsteriskBOX_${tag.removePrefix("v")}-660-$abi.apk"
        return """{"name":"$name","size":42,"digest":"$digest","browser_download_url":"https://github.com/$repository/releases/download/$tag/$name"}"""
    }
}
