package com.yierpai.savetool.ui

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.yierpai.savetool.Permission
import com.yierpai.savetool.SaveOrigin
import com.yierpai.savetool.Workflow
import com.yierpai.savetool.core.AppCtx
import com.yierpai.savetool.core.Backup
import com.yierpai.savetool.core.BackupEntry
import com.yierpai.savetool.core.CharInfo
import com.yierpai.savetool.core.Profile
import com.yierpai.savetool.core.Relief
import com.yierpai.savetool.core.Save
import com.yierpai.savetool.core.Variant
import kotlinx.coroutines.delay
import java.io.File

private enum class MsgIcon { Info, Warn, Error, Question }

private data class DialogState(
    val title: String,
    val msg: String,
    val icon: MsgIcon = MsgIcon.Warn,
    /** true = 单按钮弹窗（只显示「确定」）；false = 「是」/「否」双按钮 */
    val single: Boolean = true,
    val onYes: () -> Unit = {},
)

private data class PickedZip(val path: String, val stem: String)

private val ILLEGAL_NAME_CHARS = setOf('/', '\\', ':', '*', '?', '"', '<', '>', '|')

@Composable
fun MainScreen() {
    MaterialTheme(colorScheme = lightColorScheme()) {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            MainContent()
        }
    }
}

@Composable
private fun MainContent() {
    val ctx = LocalContext.current

    // ---------- 状态 ----------
    var granted by remember { mutableStateOf(Permission.isGranted()) }
    var profiles by remember { mutableStateOf<List<Profile>>(emptyList()) }
    var chars by remember { mutableStateOf<List<CharInfo>>(emptyList()) }
    var backups by remember { mutableStateOf<List<BackupEntry>>(emptyList()) }
    var cur by remember { mutableStateOf<Profile?>(null) }
    var curChar by remember { mutableStateOf<CharInfo?>(null) }
    var payload by remember { mutableStateOf(Variant.nil()) }
    var accIdx by remember { mutableIntStateOf(0) }
    var charIdx by remember { mutableIntStateOf(0) }
    var bakIdx by remember { mutableIntStateOf(0) }
    var status by remember { mutableStateOf("") }
    var toast by remember { mutableStateOf<String?>(null) }
    var toastSeq by remember { mutableIntStateOf(0) }
    var dialog by remember { mutableStateOf<DialogState?>(null) }
    var pendingZip by remember { mutableStateOf<String?>(null) }

    val pathText = "存档位置：" + (cur?.dir ?: Save.savesDir)

    val showStatus: (String) -> Unit = { msg ->
        status = msg
        println("[GFP] " + msg.replace('\n', ' '))
    }
    val showToast: (String) -> Unit = { msg ->
        showStatus(msg)
        toast = msg
        toastSeq++
    }
    val showAlert: (String, String, MsgIcon) -> Unit = { t, m, i ->
        dialog = DialogState(t, m, i)
    }

    // Toast 3 秒自动消失
    LaunchedEffect(toastSeq) {
        if (toast != null) {
            delay(3000)
            toast = null
        }
    }

    // ---------- 数据加载 ----------
    fun clearAll() {
        profiles = emptyList(); chars = emptyList(); backups = emptyList()
        cur = null; curChar = null; payload = Variant.nil()
        accIdx = 0; charIdx = 0; bakIdx = 0
        showStatus("尚未授予「所有文件访问权限」，无法读取存档目录。")
    }

    fun refreshBackups() {
        val p = cur
        if (p == null) { backups = emptyList(); bakIdx = 0; return }
        val list = Backup.list(p.name)
        backups = list
        bakIdx = 0
    }

    fun loadAccount(index: Int) {
        if (index < 0 || index >= profiles.size) return
        val p = profiles[index]
        cur = p
        val pl = try {
            Save.loadPayload(p)
        } catch (e: Exception) {
            chars = emptyList(); backups = emptyList(); curChar = null
            showStatus("账号【${p.name}】读取失败：${e.message}")
            return
        }
        payload = pl
        val list = Relief.chars(pl)
        chars = list
        charIdx = 0
        curChar = list.firstOrNull()
        println("[GFP] 账号 ${p.name}（${p.encryptionId()}）：${list.size} 个有效角色")
        refreshBackups()
    }

    fun reloadProfiles(select: String?) {
        val list = Save.listProfiles()
        // PC 版会把"当前游戏账号"提到第一位（读 login_credentials.cfg），移动端保持一致
        val active = Save.activeProfileName()
        if (active != null) {
            val k = list.indexOfFirst { it.name == active }
            if (k > 0) { val p = list.removeAt(k); list.add(0, p) }
        }
        profiles = list
        if (list.isEmpty()) {
            chars = emptyList(); backups = emptyList(); cur = null; curChar = null
            accIdx = 0; charIdx = 0; bakIdx = 0
            showStatus("没有可用账号。")
            return
        }
        var idx = 0
        if (select != null) {
            val k = list.indexOfFirst { it.name == select }
            if (k >= 0) idx = k
        }
        accIdx = idx
        loadAccount(idx)
    }

    // 权限变化时重载
    LaunchedEffect(granted) {
        if (granted) reloadProfiles(null) else clearAll()
    }

    // 从系统设置页返回时重新检测
    DisposableEffect(Unit) {
        Permission.onResumed = { granted = Permission.isGranted() }
        onDispose { Permission.onResumed = null }
    }

    // 启动自检：验证装备库 assets + org.json 这条链路没被裁坏
    LaunchedEffect(Unit) {
        try {
            for (role in listOf("伊尔", "派派", "大竹", "敖天")) {
                println("[GFP-SELF] 装备库 $role：鲲鹏 id 数 = ${Relief.kunpengIds(role).size}")
            }
            println("[GFP-SELF] GenUid() = ${Relief.genUid()}")
        } catch (e: Exception) {
            println("[GFP-SELF] 自检失败：$e")
        }
    }

    // ---------- 功能 ----------
    fun doRelief() {
        val p = cur
        if (p == null) { showToast("请先选择有效账号"); return }
        val c = curChar
        if (c == null) { showToast("请选择角色"); return }

        val keep = c.idx
        val r = Workflow.applyRelief(p, c)
        if (r.ok) {
            payload = r.payload
            val list = Relief.chars(payload)
            chars = list
            charIdx = list.indexOfFirst { it.idx == keep }.coerceAtLeast(0)
            curChar = list.getOrNull(charIdx)
            // ⚠ 与 PySide6 版对齐：只有"完成"走 Toast，其余（等级过高 / 已拥有）都是弹窗
            if (r.title == "完成") showToast(r.msg) else showAlert(r.title, r.msg, MsgIcon.Warn)
        } else {
            showAlert(r.title, r.msg, MsgIcon.Error)
        }
    }

    fun doBackup() {
        val p = cur ?: run { showToast("请先选择有效账号"); return }
        val r = Workflow.makeBackup(p)
        if (r.ok) { refreshBackups(); showToast(r.msg) } else showAlert(r.title, r.msg, MsgIcon.Error)
    }

    fun doRestore() {
        val p = cur ?: run { showToast("请先选择有效账号"); return }
        if (backups.isEmpty()) { showToast("该账号还没有备份"); return }
        val b = backups.getOrNull(bakIdx) ?: run { showToast("请选择要恢复的备份"); return }
        if (!File(b.path).exists()) { showAlert("错误", "备份文件不存在。", MsgIcon.Error); refreshBackups(); return }

        dialog = DialogState(
            "确认恢复",
            "将恢复账号【${p.name}】的备份存档【${Backup.fmt(b)}】，是否确定？",
            MsgIcon.Question,
            single = false,
        ) {
            val r = Workflow.restore(p, b)
            if (r.ok) { loadAccount(accIdx); showToast(r.msg) } else showAlert(r.title, r.msg, MsgIcon.Error)
        }
    }

    fun deleteBackupNow(p: Profile, b: BackupEntry) {
        val r = Workflow.deleteBackup(p, b)
        if (r.ok) { refreshBackups(); showToast(r.msg) } else showAlert(r.title, r.msg, MsgIcon.Error)
    }

    fun doDeleteBackup() {
        val p = cur ?: run { showToast("请先选择有效账号"); return }
        if (backups.isEmpty()) { showToast("该账号还没有备份"); return }
        val b = backups.getOrNull(bakIdx) ?: run { showToast("请选择要删除的备份"); return }
        if (!File(b.path).exists()) { showAlert("错误", "备份文件不存在。", MsgIcon.Error); refreshBackups(); return }

        // ⚠ 仅当只剩最后 1 个备份时才弹窗确认，避免误删全部备份
        if (backups.size == 1) {
            dialog = DialogState(
                "确认删除",
                "【${Backup.fmt(b)}】是账号【${p.name}】的最后一个备份存档，是否删除？",
                MsgIcon.Question,
                single = false,
            ) { deleteBackupNow(p, b) }
            return
        }
        deleteBackupNow(p, b)
    }

    fun doExport() {
        val p = cur ?: run { showToast("请先选择有效账号"); return }
        val prep = Workflow.prepareExport(p)
        if (!prep.ok) { showAlert("导出失败", prep.msg, MsgIcon.Error); return }

        if (!prep.exists) {
            val r = Workflow.exportSave(p, prep.path)
            showAlert(r.title, r.msg, if (r.ok) MsgIcon.Info else MsgIcon.Error)
            return
        }
        dialog = DialogState(
            "确认覆盖",
            "导出位置已存在存档文件【${File(prep.path).name}】，是否覆盖？",
            MsgIcon.Question,
            single = false,
        ) {
            val r = Workflow.exportSave(p, prep.path)
            showAlert(r.title, r.msg, if (r.ok) MsgIcon.Info else MsgIcon.Error)
        }
    }

    fun doImportPlan(zip: String, stem: String) {
        val res = Workflow.analyze(zip, stem)
        if (!res.ok) {
            try { File(zip).delete() } catch (_: Exception) { }
            pendingZip = null
            showAlert("无法导入", res.msg, MsgIcon.Warn)
            return
        }
        val plan = res.plan
        pendingZip = zip

        val sb = StringBuilder()
        sb.append(
            if (plan.targetExists) "将覆盖账号【${plan.name}】的当前存档（覆盖前会自动备份一次），是否确定？"
            else "将新建账号【${plan.name}】，是否确定？"
        )
        if (plan.origin == SaveOrigin.Desktop) {
            sb.append("\n\n⚠ 检测到这是电脑版存档，导入时会自动做兼容处理：")
            plan.conversions.forEach { sb.append("\n   · ").append(it) }
        }
        dialog = DialogState("确认导入", sb.toString(), MsgIcon.Question, single = false) {
            val z = pendingZip
            pendingZip = null
            if (z == null) { showStatus("导入失败：临时文件已丢失。"); return@DialogState }
            plan.zipPath = z
            val r = Workflow.importSave(plan)
            try { File(z).delete() } catch (_: Exception) { }
            if (r.ok) {
                reloadProfiles(plan.name)
                // ⚠ 导入说明里含电脑版兼容转换清单，用弹窗才能看全
                showAlert(r.title, r.msg, MsgIcon.Info)
            } else {
                showAlert(r.title, r.msg, MsgIcon.Error)
            }
        }
    }

    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) { showToast("已取消选择"); return@rememberLauncherForActivityResult }
        // ⚠ SAF 返回 content:// URI 拿不到真实路径 ⇒ 复制成临时文件；
        //   ⚠⚠ 临时文件名必须保留原始 zip 文件名（Analyze 靠文件名推导 encryption_id），
        //      之前固定用时间戳名会导致"导出的存档再导入必失败"。
        val picked = try {
            copyUriToTemp(ctx, uri, Backup.nowStamp())
        } catch (e: Exception) {
            showAlert("无法导入", "读取所选文件失败：${e.message}", MsgIcon.Warn)
            return@rememberLauncherForActivityResult
        }
        doImportPlan(picked.path, picked.stem)
    }

    // ---------- 布局 ----------
    Box(Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (!granted) {
                PermissionPanel(
                    onGrant = { Permission.openSettings() },
                    onRecheck = { granted = Permission.isGranted() },
                )
            }

            Text(pathText, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)

            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("账号", fontSize = 14.sp)
                FormDropdown(
                    items = profiles.map { it.name },
                    selectedIndex = accIdx,
                    enabled = profiles.isNotEmpty(),
                    modifier = Modifier.weight(1f).padding(start = 6.dp),
                ) { accIdx = it; loadAccount(it) }
                Text("角色", fontSize = 14.sp, modifier = Modifier.padding(start = 10.dp))
                // 宽度比 1 : 2.2 —— 角色名形如「喵喵喵喵喵（派派）Lv.6」比账号名长得多
                FormDropdown(
                    items = chars.map { Relief.display(it) },
                    selectedIndex = charIdx,
                    enabled = chars.isNotEmpty(),
                    modifier = Modifier.weight(2.2f).padding(start = 6.dp),
                ) { charIdx = it; curChar = chars.getOrNull(it) }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Button(onClick = { doRelief() }, modifier = Modifier.weight(1f)) { Text("减负") }
                Button(onClick = { doExport() }, modifier = Modifier.weight(1f)) { Text("导出") }
                Button(
                    onClick = {
                        importLauncher.launch(
                            arrayOf("application/zip", "application/x-zip-compressed", "application/octet-stream", "*/*")
                        )
                    },
                    modifier = Modifier.weight(1f),
                ) { Text("导入") }
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("备份", fontSize = 14.sp)
                FormDropdown(
                    items = backups.map { Backup.fmt(it) },
                    selectedIndex = bakIdx,
                    enabled = backups.isNotEmpty(),
                    modifier = Modifier.weight(1f).padding(start = 6.dp),
                ) { bakIdx = it }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Button(onClick = { doBackup() }, modifier = Modifier.weight(1f)) { Text("备份") }
                Button(onClick = { doRestore() }, modifier = Modifier.weight(1f)) { Text("恢复") }
                Button(onClick = { doDeleteBackup() }, modifier = Modifier.weight(1f)) { Text("删除") }
            }

            if (status.isNotEmpty()) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        status,
                        fontSize = 12.sp,
                        modifier = Modifier.padding(10.dp),
                    )
                }
            }
        }

        // Toast：底部浮出的轻提示，不阻塞操作，3 秒后自动消失
        toast?.let {
            Box(
                Modifier
                    .align(Alignment.BottomCenter)
                    .padding(start = 20.dp, end = 20.dp, bottom = 44.dp)
                    .background(Color(0xE0000000), RoundedCornerShape(20.dp))
                    .padding(horizontal = 16.dp, vertical = 10.dp),
            ) {
                Text(it, color = Color.White, fontSize = 13.sp)
            }
        }

        dialog?.let { d ->
            val single = d.single
            // ⚠ 必须自绘 Dialog，不能用 Material3 的 AlertDialog：
            //   ① AlertDialog 把 icon 放在标题**上方**，电脑版是「图标 + 标题**同排**」；
            //   ② AlertDialog 的 dismissButton 永远排在 confirmButton **左边**，
            //      于是「否」会跑到「是」左边，与电脑版 MessageWindow（是左否右）相反。
            Dialog(
                onDismissRequest = { if (single) dialog = null },
                properties = DialogProperties(usePlatformDefaultWidth = false),
            ) {
                BoxWithConstraints(Modifier.fillMaxSize()) {
                    // 卡片宽 = 窗口宽 × 0.65（对齐电脑版 ConfirmDialog.MaxWidth）
                    val cardW = maxWidth * 0.65f
                    // 单按钮「确定」宽度 = 与双按钮中单个按钮等宽（对齐电脑版 SingleButtonWidth()：
                    // 卡片内可用宽 = 卡片宽 - 左右 padding 32 - 双按钮间距 10，再取一半）
                    val singleBtnW = ((cardW - 32.dp - 10.dp) / 2f).coerceAtLeast(0.dp)

                    Box(
                        Modifier.fillMaxSize().background(Color(0x99000000)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(
                            Modifier
                                .width(cardW)
                                .background(Color.White, RoundedCornerShape(8.dp))
                                .padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            // 图标 + 标题同排
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                IconCircle(d.icon)
                                Text(
                                    d.title,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 16.sp,
                                    color = Color(0xFF222222),
                                )
                            }

                            Text(d.msg, color = Color(0xFF444444))

                            if (single) {
                                // 单按钮：只显示「确定」，右对齐 + 半宽
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                                    Button(
                                        onClick = {
                                            val act = d.onYes
                                            dialog = null
                                            act()
                                        },
                                        modifier = Modifier.width(singleBtnW),
                                    ) { Text("确定") }
                                }
                            } else {
                                // ⚠ 按钮顺序对齐电脑版 MessageWindow：【是】在左、【否】在右
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    Button(
                                        onClick = {
                                            val act = d.onYes
                                            dialog = null
                                            act()
                                        },
                                        modifier = Modifier.weight(1f),
                                    ) { Text("是") }
                                    OutlinedButton(
                                        onClick = {
                                            dialog = null
                                            // 用户取消导入 → 临时包没用了
                                            try { pendingZip?.let { File(it).delete() } } catch (_: Exception) { }
                                            pendingZip = null
                                        },
                                        modifier = Modifier.weight(1f),
                                    ) { Text("否") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PermissionPanel(onGrant: () -> Unit, onRecheck: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF4E5)),
        shape = RoundedCornerShape(6.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("⚠ 需要「所有文件访问权限」", fontWeight = FontWeight.SemiBold)
            Text(
                "读取游戏存档需要此权限。系统不会自动弹窗，请点下面按钮，在打开的设置页里打开开关后返回。",
                fontSize = 12.sp,
                color = Color(0xDD000000),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onGrant) { Text("去授权") }
                OutlinedButton(onClick = onRecheck) { Text("重新检测") }
            }
        }
    }
}

/** 简化版下拉框：OutlinedButton + DropdownMenu（避免 ExposedDropdownMenuBox 的锚点坑） */
@Composable
private fun FormDropdown(
    items: List<String>,
    selectedIndex: Int,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onSelect: (Int) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(
            onClick = { expanded = true },
            enabled = enabled,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                items.getOrElse(selectedIndex) { if (items.isEmpty()) "—" else items[0] },
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                fontSize = 13.sp,
                modifier = Modifier.weight(1f),
            )
            Text("▾", fontSize = 12.sp)
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            if (items.isEmpty()) {
                DropdownMenuItem(text = { Text("（空）") }, onClick = { expanded = false })
            } else {
                items.forEachIndexed { i, s ->
                    DropdownMenuItem(
                        text = { Text(s, fontSize = 13.sp) },
                        onClick = { expanded = false; onSelect(i) },
                    )
                }
            }
        }
    }
}

/** 圆底 + ASCII 符号的图标（⬤ i / ? / ! / x），与原 Avalonia 版一致 */
@Composable
private fun IconCircle(icon: MsgIcon) {
    val (fill, glyph) = when (icon) {
        MsgIcon.Warn -> Color(0xFFFAC832) to "!"
        MsgIcon.Error -> Color(0xFFD63C3C) to "x"
        MsgIcon.Question -> Color(0xFF2E7CB3) to "?"
        MsgIcon.Info -> Color(0xFF2E7CB3) to "i"
    }
    Box(
        Modifier
            .size(28.dp)
            .background(fill, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(glyph, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold)
    }
}

/** SAF content:// → 临时文件（保留原始文件名，供 Analyze 推导 encryption_id） */
private fun copyUriToTemp(ctx: Context, uri: Uri, fallbackStamp: String): PickedZip {
    var displayName: String? = null
    try {
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) displayName = c.getString(idx)
        }
    } catch (_: Exception) { }

    var stem = displayName?.substringBeforeLast('.') ?: ""
    if (stem.isBlank()) stem = "gfp_import_$fallbackStamp"
    val safe = stem.map { if (it in ILLEGAL_NAME_CHARS || it.code < 32) '_' else it }.joinToString("")

    val dir = File(AppCtx.cacheDir)
    dir.mkdirs()
    val out = File(dir, "$safe.zip")
    ctx.contentResolver.openInputStream(uri).use { ins ->
        requireNotNull(ins) { "无法打开所选文件" }
        out.outputStream().use { ins.copyTo(it) }
    }
    return PickedZip(out.path, stem)
}
