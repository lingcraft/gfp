package com.yierpai.savetool.ui

import android.content.Context
import android.content.res.Configuration
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowDropDown
import androidx.compose.material.icons.rounded.AutoFixHigh
import androidx.compose.material.icons.rounded.Backup
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Error
import androidx.compose.material.icons.rounded.FileDownload
import androidx.compose.material.icons.rounded.FileUpload
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.FolderSpecial
import androidx.compose.material.icons.rounded.Help
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Restore
import androidx.compose.material.icons.rounded.SportsEsports
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
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
import kotlinx.coroutines.launch
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

/**
 * 导入时文件选择器接受的 MIME 类型（zip / 7z / rar）。
 * ⚠ 末尾那个「通配 MIME」（星号、斜杠、星号）不能省：部分文件管理器对 7z/rar 报的 MIME 不规范
 *   （或直接报 octet-stream），没有它用户会挑不到文件。
 * ⚠ 注意：MIME 通配串本身含「星号+斜杠」，**写进块注释会把注释提前结束**，所以这里只做文字描述。
 */
private val IMPORT_MIMES = arrayOf(
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
    "application/vnd.rar",
    "application/x-rar-compressed",
    "application/octet-stream",
    "*/*",
)

@Composable
fun MainScreen() {
    GfpTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surfaceContainer) {
            MainContent()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
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
    var dialog by remember { mutableStateOf<DialogState?>(null) }
    var pendingZip by remember { mutableStateOf<String?>(null) }

    val pathText = cur?.dir ?: Save.savesDir

    // 横竖屏自适应：**横屏**用原 Avalonia(C#) 版的紧凑排布（一行多项，充分利用横向空间），
    // **竖屏**用 MD3 纵向卡片布局（图标行 + 整行控件）。
    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE

    // ⚠ 底部状态条已删除（它和新 Snackbar 的内容 100% 重复，且占了底部一条位置）：
    //   原 showStatus 的三条"独占消息"已改道 —— 读取失败 → 弹窗、没有可用账号 → Snackbar、
    //   导入临时文件丢失 → 弹窗。日志镜像（println）挪到 showToast 里保留。
    // ⚠ 轻提示改用 MD3 官方 Snackbar（挂在 Scaffold.snackbarHost 上），替掉原来自绘的深色小条：
    //   ① 自带进出场动画（原来"啪"地出现/消失）；② 会自动避让右下角的 FAB（原来会压在 FAB 上）；
    //   ③ 形状/配色走 MD3（inverseSurface 底 + inverseOnSurface 字，与原来观感一致）；
    //   ④ 时长用 SnackbarDuration.Short（≈4s，原来硬编码 3s）。
    //   ⚠ 连点同一个/多个提示时不排队：先 dismiss 当前那条再显示新的（否则会一条条播完）。
    val snackbarHostState = remember { SnackbarHostState() }
    val uiScope = rememberCoroutineScope()

    val showToast: (String) -> Unit = { msg ->
        // 日志镜像（原来在 showStatus 里，状态条删掉后挪到这里）
        println("[GFP] " + msg.replace('\n', ' '))
        uiScope.launch {
            snackbarHostState.currentSnackbarData?.dismiss()
            snackbarHostState.showSnackbar(msg, duration = SnackbarDuration.Short)
        }
    }
    val showAlert: (String, String, MsgIcon) -> Unit = { t, m, i ->
        dialog = DialogState(t, m, i)
    }

    // ---------- 数据加载 ----------
    fun clearAll() {
        profiles = emptyList(); chars = emptyList(); backups = emptyList()
        cur = null; curChar = null; payload = Variant.nil()
        accIdx = 0; charIdx = 0; bakIdx = 0
        // ⚠ 这里**不要**再 showStatus("尚未授予…")：
        //   那条提示改为在渲染处由 `granted` 派生（见下方 statusText），否则授权后返回时
        //   它作为一次性 status 会一直残留（用户反馈的 bug）。
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
            // 错误信息可能很长（异常栈文案）⇒ 用弹窗（Snackbar 会省略号截断）
            showAlert("读取失败", "账号【${p.name}】读取失败：\n${e.message}", MsgIcon.Error)
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
            showToast("没有可用账号。")
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
            if (z == null) {
                showAlert("导入失败", "临时文件已丢失，请重新选择压缩包。", MsgIcon.Warn)
                return@DialogState
            }
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

    // ---------- 布局（Material 3：TopAppBar + 分组卡片 + 图标行 + 主操作 FAB）----------
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("存档工具", fontWeight = FontWeight.SemiBold) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surfaceContainer,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
            )
        },
        floatingActionButton = {
            // 主操作：开荒减负（工具的招牌功能）—— **横竖屏统一放右下角 FAB**
            ExtendedFloatingActionButton(
                onClick = { doRelief() },
                icon = { Icon(Icons.Rounded.AutoFixHigh, contentDescription = null) },
                text = { Text("减负") },
            )
        },
        // 轻提示统一走 SnackbarHost：位置由 Scaffold 计算（会主动避让上面的 FAB）。
        // ⚠ 这里**自定义了外观**（不用 M3 默认的整行 Snackbar）——做成"浮动胶囊"：
        //   贴合内容宽度（`widthIn(max=420dp)` + 内边距撑开）、全圆角、居中、带投影，
        //   观感更接近经典 Toast，但保留了 Snackbar 的动画与避让 FAB 的好处。
        //   ⚠ 必须自己套一层 `Box(fillMaxWidth, Center)`：SnackbarHost 内部 Box 不保证居中。
        snackbarHost = {
            SnackbarHost(snackbarHostState) { data ->
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Surface(
                        modifier = Modifier.padding(horizontal = 24.dp).widthIn(max = 420.dp),
                        shape = RoundedCornerShape(50),
                        color = MaterialTheme.colorScheme.inverseSurface,
                        contentColor = MaterialTheme.colorScheme.inverseOnSurface,
                        shadowElevation = 6.dp,
                    ) {
                        Text(
                            data.visuals.message,
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center,
                            maxLines = 3,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                        )
                    }
                }
            }
        },
        containerColor = MaterialTheme.colorScheme.surfaceContainer,
    ) { inner ->
        Box(Modifier.fillMaxSize().padding(inner)) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp)
                    // 底部留出右下角 FAB 的空间（横竖屏都有 FAB）
                    .padding(top = 4.dp, bottom = 96.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (!granted) {
                    PermissionCard(
                        onGrant = { Permission.openSettings() },
                        onRecheck = { granted = Permission.isGranted() },
                    )
                }

                // 存档位置 + 账号 + 角色
                SettingCard {
                    SettingRow(
                        icon = Icons.Rounded.Folder,
                        title = "存档位置",
                        description = pathText,
                    )
                    RowDivider()
                    if (landscape) {
                        // 横屏：账号 / 角色 并排（宽度比沿用原 Avalonia 版的 1 : 2.2）
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            DropdownField(
                                label = "账号",
                                icon = Icons.Rounded.Person,
                                items = profiles.map { it.name },
                                selectedIndex = accIdx,
                                enabled = profiles.isNotEmpty(),
                                modifier = Modifier.weight(1f),
                            ) { accIdx = it; loadAccount(it) }
                            DropdownField(
                                label = "角色",
                                icon = Icons.Rounded.SportsEsports,
                                items = chars.map { Relief.display(it) },
                                selectedIndex = charIdx,
                                enabled = chars.isNotEmpty(),
                                modifier = Modifier.weight(2.2f),
                            ) { charIdx = it; curChar = chars.getOrNull(it) }
                        }
                    } else {
                        Spacer(Modifier.height(6.dp))
                        DropdownField(
                            label = "账号",
                            icon = Icons.Rounded.Person,
                            items = profiles.map { it.name },
                            selectedIndex = accIdx,
                            enabled = profiles.isNotEmpty(),
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                        ) { accIdx = it; loadAccount(it) }
                        Spacer(Modifier.height(12.dp))
                        DropdownField(
                            label = "角色",
                            icon = Icons.Rounded.SportsEsports,
                            items = chars.map { Relief.display(it) },
                            selectedIndex = charIdx,
                            enabled = chars.isNotEmpty(),
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                        ) { charIdx = it; curChar = chars.getOrNull(it) }
                        Spacer(Modifier.height(16.dp))
                    }
                }

                // 导出 / 导入
                SettingCard {
                    if (landscape) {
                        // 横屏：与「减负」并排成一行两个按钮（原 Avalonia 版的排布）
                        Row(
                            Modifier.fillMaxWidth().padding(16.dp),
                            // ⚠ 形态（用户拍板）：**各按钮 weight(1f) 平分、铺满整行**，不留居中留白。
                            //   宽度演进：内容宽度（87dp，嫌小）→ 定宽 200/170dp 居中 → 铺满整行。
                            //   ⚠ 期间试过"把竖屏的一行点击项当按钮横排"，用户嫌丑已回退（见记忆 修正⑨）。
                            // ⚠ 若以后又改回"定宽"，必须写 `weight(1f, fill = false).width(...)`：
                            //   `fill = true`（默认）时父级下发 min=max=份额，width/widthIn 都压不下来（实测无效）。
                            // ⚠「减负」不在这里 —— 它是右下角的 FAB（与竖屏一致）。
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            // ⚠ 按钮宽（2 个各约 500dp），文案**不再简略**，与竖屏各行标题一字不差
                            ActionButton(
                                text = "导出存档",
                                icon = Icons.Rounded.FileUpload,
                                modifier = Modifier.weight(1f),
                            ) { doExport() }
                            ActionButton(
                                text = "导入存档",
                                icon = Icons.Rounded.FileDownload,
                                modifier = Modifier.weight(1f),
                            ) { importLauncher.launch(IMPORT_MIMES) }
                        }
                    } else {
                        SettingRow(
                            icon = Icons.Rounded.FileUpload,
                            title = "导出存档",
                            description = "打包当前账号的存档到 /storage/emulated/0/（文件名＝账号名.zip）",
                            onClick = { doExport() },
                            trailing = { TrailingChevron() },
                        )
                        RowDivider()
                        SettingRow(
                            icon = Icons.Rounded.FileDownload,
                            title = "导入存档",
                            description = "支持 zip / 7z / rar；电脑版存档会自动做兼容转换",
                            onClick = { importLauncher.launch(IMPORT_MIMES) },
                            trailing = { TrailingChevron() },
                        )
                    }
                }

                // 备份
                SettingCard {
                    if (landscape) {
                        // 横屏：备份下拉一行 + 三个按钮一行（原 Avalonia 版的排布）
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(top = 12.dp),
                        ) {
                            DropdownField(
                                label = "备份存档",
                                icon = Icons.Rounded.Backup,
                                items = backups.map { Backup.fmt(it) },
                                selectedIndex = bakIdx,
                                enabled = backups.isNotEmpty(),
                                modifier = Modifier.fillMaxWidth(),
                            ) { bakIdx = it }
                        }
                        // 横屏：备份下拉一行 + 三个按钮一行（原 Avalonia 版的排布）
                        Row(
                            Modifier.fillMaxWidth().padding(16.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            // ⚠ 文案与竖屏三行标题一字不差（"备份当前存档"/"恢复所选备份"/"删除所选备份"）
                            ActionButton(
                                text = "备份当前存档",
                                icon = Icons.Rounded.Backup,
                                modifier = Modifier.weight(1f),
                            ) { doBackup() }
                            ActionButton(
                                text = "恢复所选备份",
                                icon = Icons.Rounded.Restore,
                                modifier = Modifier.weight(1f),
                            ) { doRestore() }
                            ActionButton(
                                text = "删除所选备份",
                                icon = Icons.Rounded.Delete,
                                modifier = Modifier.weight(1f),
                                style = ActionButtonStyle.Danger,
                            ) { doDeleteBackup() }
                        }
                    } else {
                        Spacer(Modifier.height(6.dp))
                        DropdownField(
                            label = "备份存档",
                            icon = Icons.Rounded.Backup,
                            items = backups.map { Backup.fmt(it) },
                            selectedIndex = bakIdx,
                            enabled = backups.isNotEmpty(),
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                        ) { bakIdx = it }
                        Spacer(Modifier.height(12.dp))
                        SettingRow(
                            icon = Icons.Rounded.Backup,
                            title = "备份当前存档",
                            description = "按时间戳命名，存到 backups/<账号> 目录",
                            onClick = { doBackup() },
                            trailing = { TrailingChevron() },
                        )
                        RowDivider()
                        SettingRow(
                            icon = Icons.Rounded.Restore,
                            title = "恢复所选备份",
                            description = "用所选备份覆盖当前存档（会再确认一次）",
                            onClick = { doRestore() },
                            trailing = { TrailingChevron() },
                        )
                        RowDivider()
                        SettingRow(
                            icon = Icons.Rounded.Delete,
                            title = "删除所选备份",
                            description = "仅当该账号只剩 1 个备份时会二次确认",
                            tint = MaterialTheme.colorScheme.error,
                            onClick = { doDeleteBackup() },
                            trailing = { TrailingChevron(tint = MaterialTheme.colorScheme.error) },
                        )
                    }
                }

            }

            dialog?.let { d ->
                val single = d.single
                // ⚠ 仍然**自绘** Dialog（不用 M3 AlertDialog）：要的是参考实现那套「图标居中在标题上方
                //   + 整行宽的 tonal 按钮」；AlertDialog 的动作区固定在右下角 FlowRow，给不了这个形状。
                //   卡片几何仍按电脑版约束：宽 = 窗口宽 × 0.65，全屏半透明遮罩。
                Dialog(
                    onDismissRequest = { if (single) dialog = null },
                    properties = DialogProperties(usePlatformDefaultWidth = false),
                ) {
                    BoxWithConstraints(Modifier.fillMaxSize()) {
                        val cardW = maxWidth * 0.65f
                        // 正文可能很长（导入时列出兼容转换清单）⇒ 给卡片高度上限，正文可滚动
                        val cardMaxH = maxHeight * 0.85f

                        Box(
                            Modifier
                                .fillMaxSize()
                                .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.5f)),
                            contentAlignment = Alignment.Center,
                        ) {
                            Surface(
                                modifier = Modifier.width(cardW).heightIn(max = cardMaxH),
                                shape = RoundedCornerShape(28.dp),
                                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                                contentColor = MaterialTheme.colorScheme.onSurface,
                            ) {
                                Column(
                                    Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = 16.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                ) {
                                    // 图标：居中，在标题**上方**（对齐参考实现的 centerIcon 槽）
                                    DialogIcon(d.icon)
                                    Spacer(Modifier.height(12.dp))

                                    // 标题：居中
                                    Text(
                                        d.title,
                                        style = MaterialTheme.typography.headlineSmall,
                                        fontWeight = FontWeight.SemiBold,
                                        textAlign = TextAlign.Center,
                                        modifier = Modifier.padding(horizontal = 16.dp),
                                    )
                                    Spacer(Modifier.height(12.dp))

                                    // 正文：居中 + 超高时可滚动
                                    Box(
                                        Modifier
                                            .weight(1f, fill = false)
                                            .padding(horizontal = 16.dp),
                                    ) {
                                        Text(
                                            d.msg,
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            textAlign = TextAlign.Center,
                                            modifier = Modifier.verticalScroll(rememberScrollState()),
                                        )
                                    }
                                    Spacer(Modifier.height(16.dp))

                                    if (single) {
                                        // 单按钮：整行宽的「确定」
                                        DialogActionButton(
                                            text = "确定",
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .padding(horizontal = 16.dp),
                                        ) {
                                            val act = d.onYes
                                            dialog = null
                                            act()
                                        }
                                    } else {
                                        // ⚠ 按钮顺序仍按电脑版 MessageWindow：【是】在左、【否】在右
                                        Row(
                                            Modifier
                                                .fillMaxWidth()
                                                .padding(horizontal = 16.dp),
                                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                                        ) {
                                            DialogActionButton(text = "是", modifier = Modifier.weight(1f)) {
                                                val act = d.onYes
                                                dialog = null
                                                act()
                                            }
                                            DialogActionButton(text = "否", modifier = Modifier.weight(1f)) {
                                                dialog = null
                                                // 用户取消导入 → 临时包没用了
                                                try { pendingZip?.let { File(it).delete() } } catch (_: Exception) { }
                                                pendingZip = null
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 分组卡片（对应参考实现的 BaseItemContainer：亮色 surface + 大圆角） */
@Composable
private fun SettingCard(content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceBright),
    ) {
        Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), content = content)
    }
}

/** 卡片内的行分隔线（左右各留 16dp，与 MD3 列表一致） */
@Composable
private fun RowDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(horizontal = 16.dp),
        color = MaterialTheme.colorScheme.outlineVariant,
    )
}

/** 行尾的「>」箭头 */
@Composable
private fun TrailingChevron(tint: Color = MaterialTheme.colorScheme.onSurfaceVariant) {
    Icon(Icons.Rounded.KeyboardArrowRight, contentDescription = null, tint = tint)
}

/**
 * 设置行：图标 + 标题 + 说明（+ 右侧控件）。
 * 对齐参考实现的 BaseWidget：MP3 列表项尺寸，可点击整行。
 */
@Composable
private fun SettingRow(
    icon: ImageVector?,
    title: String,
    description: String? = null,
    // 横屏把这些行横排当按钮用：由调用方传 `weight(1f).fillMaxHeight()`
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    tint: Color = MaterialTheme.colorScheme.onSurface,
    trailing: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    val leading: (@Composable () -> Unit)? = icon?.let { iv ->
        { Icon(iv, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
    val supporting: (@Composable () -> Unit)? = description?.let { d ->
        {
            Text(
                d,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
    ListItem(
        headlineContent = {
            Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, color = tint)
        },
        supportingContent = supporting,
        leadingContent = leading,
        trailingContent = trailing,
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = modifier
            .alpha(if (enabled) 1f else 0.38f)
            .then(if (onClick != null) Modifier.clickable(enabled = enabled) { onClick() } else Modifier),
    )
}

/**
 * 下拉选择字段（MD3 OutlinedTextField + 下拉菜单）。
 * ⚠ readOnly 的文本框会自己吃掉点击（只聚焦、不展开），所以在同一 Box 里另铺一层
 *   透明可点击层来接管点击 —— 这比 ExposedDropdownMenuBox 的锚点/版本差异更稳。
 * ⚠ 菜单宽度必须**手动对齐输入框**：默认 DropdownMenu 只按内容宽撑开，会显得很短。
 *   （那正是 ExposedDropdownMenuBox 的 exposedDropdownSize() 在做的事，
 *     但我们没用那个组件，所以用 onGloballyPositioned 量出字段宽度再套给菜单。）
 */
@Composable
private fun DropdownField(
    label: String,
    icon: ImageVector,
    items: List<String>,
    selectedIndex: Int,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onSelect: (Int) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    var fieldWidthPx by remember { mutableIntStateOf(0) }
    val density = LocalDensity.current
    val text = items.getOrNull(selectedIndex) ?: if (items.isEmpty()) "—" else items.first()

    Box(modifier.onGloballyPositioned { fieldWidthPx = it.size.width }) {
        OutlinedTextField(
            value = text,
            onValueChange = { },
            readOnly = true,
            enabled = enabled,
            label = { Text(label) },
            leadingIcon = { Icon(icon, contentDescription = null, modifier = Modifier.size(22.dp)) },
            trailingIcon = { Icon(Icons.Rounded.ArrowDropDown, contentDescription = null) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyLarge,
            shape = RoundedCornerShape(8.dp),
            modifier = Modifier.fillMaxWidth(),
        )
        if (enabled) {
            Box(Modifier.matchParentSize().clickable { expanded = true })
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = if (fieldWidthPx > 0) {
                Modifier.width(with(density) { fieldWidthPx.toDp() })
            } else {
                Modifier
            },
            shape = RoundedCornerShape(16.dp),
        ) {
            if (items.isEmpty()) {
                DropdownMenuItem(text = { Text("（空）") }, onClick = { expanded = false })
            } else {
                items.forEachIndexed { i, s ->
                    val selected = i == selectedIndex
                    val lead: (@Composable () -> Unit)? = if (selected) {
                        { Icon(Icons.Rounded.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary) }
                    } else null
                    DropdownMenuItem(
                        text = { Text(s, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        leadingIcon = lead,
                        onClick = { expanded = false; onSelect(i) },
                        // 选中项带底色（对齐参考实现：选中项整行高亮）
                        // ⚠ 曾试过固定色 #DCC6F7（用户先嫌"有点浅"，改完后又说"有些深了"）⇒ 最终结论：
                        //   **就用 M3 主题的 secondaryContainer**，不要再硬编码固定色。
                        modifier = if (selected) {
                            Modifier.background(
                                MaterialTheme.colorScheme.secondaryContainer,
                                RoundedCornerShape(10.dp),
                            )
                        } else {
                            Modifier
                        },
                    )
                }
            }
        }
    }
}

/** 未授权时的引导卡片（tonal 卡片，醒目但不刺眼） */
@Composable
private fun PermissionCard(onGrant: () -> Unit, onRecheck: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer,
        ),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Icon(Icons.Rounded.FolderSpecial, contentDescription = null)
                Text(
                    "需要「所有文件访问权限」",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text(
                "读取游戏存档需要此权限。系统不会自动弹窗，请点下面按钮，在打开的设置页里打开开关后返回。",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onGrant) { Text("去授权") }
                OutlinedButton(onClick = onRecheck) { Text("重新检测") }
            }
        }
    }
}

/**
 * 弹窗按钮：对齐参考实现的 dialogButtons / InnerButton ——
 * **整行宽的 tonal 按钮**（primaryContainer 底 + onPrimaryContainer 字）、4dp 圆角、4dp 间距。
 */
@Composable
private fun DialogActionButton(
    text: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        modifier = modifier,
        shape = RoundedCornerShape(4.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
        ),
        contentPadding = PaddingValues(16.dp),
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

/** 横屏操作按钮的两种语义：普通操作 / 破坏性操作（删除） */
private enum class ActionButtonStyle { Primary, Danger }

/**
 * 横屏的操作按钮 —— **样式照搬参考实现（InstallerX）的按钮配方**：
 * `TextButton` + `containerColor = primaryContainer`（淡色填充）+ `shape = 4dp 圆角`
 * + `contentPadding = 16dp`（全仓用了 197 次的那套，见其 `dialog/DialogButtons.kt:InnerButton`）。
 * 内容 = 18dp 图标 + 8dp + 文案，图标与竖屏各行一致。
 * ⚠ 横屏只借原 Avalonia 版的**控件位置**（一行放几个），样式一律用这套 MD3。
 */
@Composable
private fun ActionButton(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    style: ActionButtonStyle = ActionButtonStyle.Primary,
    onClick: () -> Unit,
) {
    val container = when (style) {
        ActionButtonStyle.Primary -> MaterialTheme.colorScheme.primaryContainer
        ActionButtonStyle.Danger -> MaterialTheme.colorScheme.errorContainer
    }
    val contentColor = when (style) {
        ActionButtonStyle.Primary -> MaterialTheme.colorScheme.onPrimaryContainer
        ActionButtonStyle.Danger -> MaterialTheme.colorScheme.onErrorContainer
    }
    val content: @Composable RowScope.() -> Unit = {
        Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(text, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
    TextButton(
        onClick = onClick,
        modifier = modifier,
        shape = RoundedCornerShape(4.dp),
        colors = ButtonDefaults.textButtonColors(
            containerColor = container,
            contentColor = contentColor,
        ),
        contentPadding = PaddingValues(16.dp),
        content = content,
    )
}

/** 弹窗图标：圆底 + MD3 图标（对齐电脑版的信息/警告/错误/询问四态） */
@Composable
private fun DialogIcon(icon: MsgIcon) {
    val (bg, fg, iv) = when (icon) {
        MsgIcon.Warn -> Triple(
            MaterialTheme.colorScheme.tertiaryContainer,
            MaterialTheme.colorScheme.onTertiaryContainer,
            Icons.Rounded.Warning,
        )
        MsgIcon.Error -> Triple(
            MaterialTheme.colorScheme.errorContainer,
            MaterialTheme.colorScheme.onErrorContainer,
            Icons.Rounded.Error,
        )
        MsgIcon.Question -> Triple(
            MaterialTheme.colorScheme.primaryContainer,
            MaterialTheme.colorScheme.onPrimaryContainer,
            Icons.Rounded.Help,
        )
        MsgIcon.Info -> Triple(
            MaterialTheme.colorScheme.secondaryContainer,
            MaterialTheme.colorScheme.onSecondaryContainer,
            Icons.Rounded.Info,
        )
    }
    Box(
        Modifier.size(32.dp).background(bg, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Icon(iv, contentDescription = null, tint = fg, modifier = Modifier.size(20.dp))
    }
}

/**
 * SAF content:// → 临时文件。
 * ⚠ 文件名必须同时保留**原始主干**（Analyze 靠它推导 encryption_id/账号名）和**原始扩展名**
 *   （决定用哪个解压器）。此前一律写成 `"$safe.zip"`，导致 7z/rar 被当成 zip 去读，
 *   报 `zip END header not found`。
 */
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
    // 保留原扩展名（zip / 7z / rar）；取不到就退回 zip（Analyze 另有文件头嗅探兜底）
    val ext = displayName?.substringAfterLast('.', "")?.lowercase()
        ?.takeIf { it.isNotBlank() && it.length <= 5 && it.all { ch -> ch.isLetterOrDigit() } }

    val dir = File(AppCtx.cacheDir)
    dir.mkdirs()
    val out = File(dir, if (ext != null) "$safe.$ext" else "$safe.zip")
    ctx.contentResolver.openInputStream(uri).use { ins ->
        requireNotNull(ins) { "无法打开所选文件" }
        out.outputStream().use { ins.copyTo(it) }
    }
    return PickedZip(out.path, stem)
}
