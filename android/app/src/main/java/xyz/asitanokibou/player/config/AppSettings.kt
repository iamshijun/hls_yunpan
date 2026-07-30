package xyz.asitanokibou.player.config

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/**
 * 应用配置（对齐 Python `config/settings.py`）。
 * 手机端不需要 Redis；port=0 表示自动选择空闲端口。
 */
data class AppConfig(
    val accessToken: String? = null,
    val cacheTtlSec: Long = 3600,
    val cacheEnabled: Boolean = true,
    val cacheSegments: Boolean = false,
    val port: Int = 0,
)

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

class AppSettings(private val context: Context) {

    val configFlow: Flow<AppConfig> = context.dataStore.data.map { p ->
        AppConfig(
            accessToken = p[KEY_TOKEN],
            cacheTtlSec = p[KEY_TTL] ?: 3600,
            cacheEnabled = p[KEY_CACHE_ENABLED] ?: true,
            cacheSegments = p[KEY_CACHE_SEGMENTS] ?: false,
            port = p[KEY_PORT] ?: 0,
        )
    }

    /** 读取一次当前配置快照 */
    suspend fun get(): AppConfig = configFlow.first()

    suspend fun setAccessToken(token: String) {
        context.dataStore.edit { it[KEY_TOKEN] = token }
    }

    suspend fun update(config: AppConfig) {
        context.dataStore.edit { p ->
            config.accessToken?.let { p[KEY_TOKEN] = it }
            p[KEY_TTL] = config.cacheTtlSec
            p[KEY_CACHE_ENABLED] = config.cacheEnabled
            p[KEY_CACHE_SEGMENTS] = config.cacheSegments
            p[KEY_PORT] = config.port
        }
    }

    companion object {
        private val KEY_TOKEN = stringPreferencesKey("access_token")
        private val KEY_TTL = longPreferencesKey("cache_ttl_sec")
        private val KEY_CACHE_ENABLED = booleanPreferencesKey("cache_enabled")
        private val KEY_CACHE_SEGMENTS = booleanPreferencesKey("cache_segments")
        private val KEY_PORT = intPreferencesKey("port")
    }
}
