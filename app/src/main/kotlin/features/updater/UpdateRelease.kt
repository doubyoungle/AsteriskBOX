// Copyright 2026, AsteriskMETA contributors
// SPDX-License-Identifier: GPL-3.0

package features.updater

import java.io.IOException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import utils.booleanOrNull
import utils.stringOrNull

internal data class UpdateAsset(
    val name: String,
    val versionName: String,
    val versionCode: Long,
    val abi: String,
    val url: String,
    val size: Long,
    val sha256: String,
)

private val apkName = Regex(
    """AsteriskBOX_([0-9]+\.[0-9]+\.[0-9]+-r\.[1-9][0-9]*)-([1-9][0-9]*)-(arm64-v8a|armeabi-v7a|x86_64|x86|universal)\.apk""",
)
private val sha256Digest = Regex("""sha256:([a-fA-F0-9]{64})""")
private val tagPattern = Regex("""v[0-9]+\.[0-9]+\.[0-9]+-r\.[1-9][0-9]*""")
private const val MaxVersionCode = 2_100_000_000L

internal fun selectUpdate(
    metadata: String,
    repository: String,
    installedVersion: Long,
    supportedAbis: List<String>,
): UpdateAsset? {
    val release = Json.parseToJsonElement(metadata) as? JsonObject
        ?: throw IOException("Invalid release metadata")
    if (release.booleanOrNull("draft") == true || release.booleanOrNull("prerelease") == true) return null
    val tag = release.stringOrNull("tag_name")
        ?.takeIf(tagPattern::matches) ?: throw IOException("Missing or invalid release tag")
    val assets = release["assets"] as? JsonArray ?: throw IOException("Missing release assets")
    val manifestVersion = release.stringOrNull("versionCode")?.toLongOrNull()
    if (release.containsKey("versionCode") && (manifestVersion == null || manifestVersion !in 1..MaxVersionCode)) {
        throw IOException("Invalid manifest version code")
    }
    val preferredAbis = (supportedAbis + "universal").distinct()
    return assets.mapNotNull { element ->
        val asset = element as? JsonObject ?: return@mapNotNull null
        val name = asset.stringOrNull("name") ?: return@mapNotNull null
        val match = apkName.matchEntire(name) ?: return@mapNotNull null
        val (versionName, code, abi) = match.destructured
        if (versionName != tag.removePrefix("v") || abi !in preferredAbis) return@mapNotNull null
        val versionCode = code.toLongOrNull() ?: return@mapNotNull null
        if (versionCode <= installedVersion || versionCode > MaxVersionCode ||
            (manifestVersion != null && versionCode != manifestVersion)
        ) {
            return@mapNotNull null
        }
        val url = "https://github.com/$repository/releases/download/$tag/$name"
        if (asset.stringOrNull("browser_download_url") != url) return@mapNotNull null
        val size = asset.stringOrNull("size")?.toLongOrNull()?.takeIf { it > 0 } ?: return@mapNotNull null
        val sha256 = asset.stringOrNull("digest")?.let(sha256Digest::matchEntire)
            ?.groupValues?.get(1)?.lowercase() ?: return@mapNotNull null
        UpdateAsset(name, versionName, versionCode, abi, url, size, sha256)
    }.maxWithOrNull(compareBy<UpdateAsset> { it.versionCode }.thenBy { -preferredAbis.indexOf(it.abi) })
}

internal fun loadUpdateMetadata(
    repository: String,
    request: (String) -> MetadataResponse,
): String? {
    val latest = request("https://api.github.com/repos/$repository/releases/latest")
    val response = if (latest.status == 403 || latest.status == 429) {
        request("https://github.com/$repository/releases/latest/download/update-manifest.json")
    } else {
        latest
    }
    return when {
        response.status == 200 -> response.body
        latest.status == 404 -> null
        else -> throw IOException("Release metadata request failed (HTTP ${response.status})")
    }
}

internal data class MetadataResponse(val status: Int, val body: String = "")
