class_name LocalSaveManagerNode
extends Node

const RECENT_LOGIN_HISTORY_SCRIPT: = preload("res://classes/recent_login_history.gd")

signal profile_opened(profile_name: String)
signal save_completed(save_path: String)
signal save_failed(message: String)
signal save_state_changed(has_unsaved_changes: bool, last_error: String)
signal quit_save_blocked(message: String)

const SAVE_ROOT: = "user://saves"
const SAVE_FILE_NAME: = "save.dat"
const TEMP_FILE_NAME: = "save.dat.tmp"
const BACKUP_FILE_NAME: = "save.dat.bak"
const PREVIOUS_FILE_NAME: = "save.dat.previous"
const CORRUPT_FILE_NAME: = "save.dat.corrupt"
const PRE_VERSION_UPGRADE_FILE_NAME: = "save.dat.pre_version_upgrade"
const PROFILE_METADATA_FILE_NAME: = "profile.cfg"
const PROFILE_METADATA_SECTION: = "Profile"
const PROFILE_METADATA_VERSION_KEY: = "version"
const PROFILE_METADATA_ENCRYPTION_ID_KEY: = "encryption_id"
const PROFILE_METADATA_VERSION: = 1
const SCHEMA_VERSION: = 2
const SAVE_CONTAINER_MAGIC: = "YIERPAI_ENCRYPTED_SAVE"
const SAVE_CONTAINER_VERSION: = 1
const SAVE_VERSION_METADATA_KEY: = "save_version"
const LEGACY_CLIENT_VERSION: = "V1.0.0"
const LEGACY_CLIENT_BUILD: = 10000
const CURRENT_CLIENT_VERSION: = "V1.0.2"
const CURRENT_CLIENT_BUILD: = 10002
const SAVE_ENCRYPTION_PEPPER: = "d8830e54d5a743a9815967d2a7a9bc48f89de2c145ef40c3b69607f948cf413e"
const CHARACTER_SLOT_COUNT: = 4
const SAVE_DEBOUNCE_SECONDS: = 0.75
const SAVE_RETRY_SECONDS: = 3.0
const MAX_PROFILE_NAME_LENGTH: = 64
const CHARACTER_NAME_MIN_LENGTH: = 1
const CHARACTER_NAME_MAX_LENGTH: = 12
const ALLOWED_ROLE_IDS: Array[String] = ["伊尔", "派派", "大竹", "敖天"]
const INVALID_CHARACTER_NAME_CHARS: Array[String] = [
	"\\", "/", ":", "*", "?", "\"", "<", ">", "|", "[", "]", "{", "}"
]
const INVALID_PROFILE_NAME_CHARS: Array[String] = ["\\", "/", ":", "*", "?", "\"", "<", ">", "|"]
const WINDOWS_RESERVED_PROFILE_NAMES: Array[String] = [
	"CON", "PRN", "AUX", "NUL", 
	"COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", 
	"LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9", 
]

var active_profile_name: String = ""
var active_profile_id: String = ""
var _encryption_profile_id: String = ""
var has_unsaved_changes: = false
var last_save_error: String = ""
var _save_data: Dictionary = {}
var _save_timer: Timer
var _save_in_progress: = false
var _save_pending: = false
var _loaded_from_recovery: = false
var _profile_load_error: String = ""
var _force_quit_requested: = false
var _compatibility_upgrade_pending: = false


func _ready() -> void :
	get_tree().auto_accept_quit = false
	_save_timer = Timer.new()
	_save_timer.name = "AutosaveTimer"
	_save_timer.one_shot = true
	_save_timer.wait_time = SAVE_DEBOUNCE_SECONDS
	_save_timer.process_mode = Node.PROCESS_MODE_ALWAYS
	_save_timer.timeout.connect(_flush_save_queue)
	add_child(_save_timer)


func _notification(what: int) -> void :
	if what != NOTIFICATION_WM_CLOSE_REQUEST:
		return
	if _force_quit_requested or not has_active_profile() or not has_unsaved_changes:
		get_tree().quit()
		return
	if flush_save():
		get_tree().quit()
		return
	quit_save_blocked.emit(last_save_error if not last_save_error.is_empty() else "存档尚未写入，已阻止退出")


func open_profile(profile_name: String) -> bool:
	var normalized_name: = profile_name.strip_edges()
	if not get_profile_name_error(normalized_name).is_empty():
		return false

	if has_active_profile() and has_unsaved_changes and not flush_save():
		return false

	var previous_profile_name: = active_profile_name
	var previous_profile_id: = active_profile_id
	var previous_encryption_profile_id: = _encryption_profile_id
	var previous_save_data: = _save_data.duplicate(true)
	var previous_loaded_from_recovery: = _loaded_from_recovery
	var previous_compatibility_upgrade_pending: = _compatibility_upgrade_pending
	if _save_timer != null:
		_save_timer.stop()
	_save_pending = false
	active_profile_name = normalized_name
	active_profile_id = normalized_name
	_encryption_profile_id = _load_profile_encryption_id()
	_save_data = _load_profile_data()
	if not _profile_load_error.is_empty():
		var load_error: = _profile_load_error
		_restore_profile(
			previous_profile_name, 
			previous_profile_id, 
			previous_encryption_profile_id, 
			previous_save_data, 
			previous_loaded_from_recovery, 
			previous_compatibility_upgrade_pending
		)
		_report_save_failure(load_error, false)
		return false
	_compatibility_upgrade_pending = _requires_compatibility_upgrade(_save_data)
	_normalize_save_data()
	_mark_unsaved()
	if not flush_save():
		var open_error: = last_save_error
		_restore_profile(
			previous_profile_name, 
			previous_profile_id, 
			previous_encryption_profile_id, 
			previous_save_data, 
			previous_loaded_from_recovery, 
			previous_compatibility_upgrade_pending
		)
		_set_save_state(false, open_error)
		return false
	profile_opened.emit(active_profile_name)
	return true


func close_profile() -> bool:
	if has_active_profile() and has_unsaved_changes and not flush_save():
		return false
	if _save_timer != null:
		_save_timer.stop()
	active_profile_name = ""
	active_profile_id = ""
	_encryption_profile_id = ""
	_save_data.clear()
	_save_pending = false
	_loaded_from_recovery = false
	_compatibility_upgrade_pending = false
	_set_save_state(false, "")
	return true


func has_active_profile() -> bool:
	return not active_profile_id.is_empty()


func get_profile_display_name() -> String:
	return active_profile_name


func get_profile_name_error(profile_name: String) -> String:
	var normalized_name: = profile_name.strip_edges()
	if normalized_name.is_empty():
		return "请输入本地用户名"
	if normalized_name.length() > MAX_PROFILE_NAME_LENGTH:
		return "本地用户名最多只能包含%d个字符" % MAX_PROFILE_NAME_LENGTH
	if normalized_name == "." or normalized_name == ".." or normalized_name.ends_with("."):
		return "本地用户名不能以句点结尾"
	for invalid_char: String in INVALID_PROFILE_NAME_CHARS:
		if normalized_name.contains(invalid_char):
			return "本地用户名不能包含字符：%s" % invalid_char
	for index: int in range(normalized_name.length()):
		if normalized_name.unicode_at(index) < 32:
			return "本地用户名不能包含控制字符"
	var windows_base_name: = normalized_name.get_slice(".", 0).to_upper()
	if windows_base_name in WINDOWS_RESERVED_PROFILE_NAMES:
		return "该本地用户名是系统保留名称，请更换名称"
	return ""


func get_character_slots() -> Array:
	if not has_active_profile():
		return _build_empty_character_slots()
	return (_save_data.get("characters", []) as Array).duplicate(true)


func get_character(slot_index: int) -> Dictionary:
	var slots: = _save_data.get("characters", []) as Array
	if slot_index < 0 or slot_index >= slots.size():
		return {}
	var value: Variant = slots[slot_index]
	return (value as Dictionary).duplicate(true) if value is Dictionary else {}


func create_character(slot_index: int, identity: Dictionary) -> Dictionary:
	if not has_active_profile():
		return {"success": false, "error_code": "profile_not_open"}
	if slot_index < 0 or slot_index >= CHARACTER_SLOT_COUNT:
		return {"success": false, "error_code": "slot_index_out_of_range"}

	var role_id: = str(identity.get("role_id", "")).strip_edges()
	if role_id not in ALLOWED_ROLE_IDS:
		return {"success": false, "error_code": "unsupported_role", "role_id": role_id}
	var character_name: = str(identity.get("name", "")).strip_edges()
	var name_error: = _get_character_name_error(character_name)
	if not name_error.is_empty():
		return {"success": false, "error_code": name_error}
	var normalized_identity: = identity.duplicate(true)
	normalized_identity["name"] = character_name
	normalized_identity["role_id"] = role_id
	if str(normalized_identity.get("role", "")).strip_edges().is_empty():
		normalized_identity["role"] = role_id

	var slots: = _save_data["characters"] as Array
	if slots[slot_index] is Dictionary and not (slots[slot_index] as Dictionary).is_empty():
		return {"success": false, "error_code": "slot_occupied"}

	var character: = _build_default_character(normalized_identity, slot_index)
	slots[slot_index] = character
	request_save(true)
	return {"success": true, "character": character["identity"].duplicate(true)}


func rename_character(slot_index: int, new_name: String) -> Dictionary:
	if not has_active_profile():
		return {"success": false, "error_code": "profile_not_open"}
	if slot_index < 0 or slot_index >= CHARACTER_SLOT_COUNT:
		return {"success": false, "error_code": "slot_index_out_of_range"}

	var normalized_name: = new_name.strip_edges()
	var name_error: = _get_character_name_error(normalized_name)
	if not name_error.is_empty():
		return {"success": false, "error_code": name_error}

	var slots: = _save_data["characters"] as Array
	if not (slots[slot_index] is Dictionary) or (slots[slot_index] as Dictionary).is_empty():
		return {"success": false, "error_code": "character_slot_empty"}

	var character: = slots[slot_index] as Dictionary
	var identity_variant: Variant = character.get("identity", {})
	if not (identity_variant is Dictionary):
		return {"success": false, "error_code": "character_identity_invalid"}

	var identity: = identity_variant as Dictionary
	identity["name"] = normalized_name
	request_save()
	return {"success": true, "character": identity.duplicate(true)}


func delete_character(slot_index: int) -> Dictionary:
	if not has_active_profile():
		return {"success": false, "error": "本地档案未打开"}
	if slot_index < 0 or slot_index >= CHARACTER_SLOT_COUNT:
		return {"success": false, "error": "角色槽位无效"}

	var slots: = _save_data["characters"] as Array
	if not (slots[slot_index] is Dictionary) or (slots[slot_index] as Dictionary).is_empty():
		return {"success": false, "error": "character slot is empty"}
	slots[slot_index] = null
	if int(_save_data.get("selected_character_slot", -1)) == slot_index:
		_save_data["selected_character_slot"] = -1
	request_save(true)
	return {"success": true}


func select_character(slot_index: int) -> bool:
	if get_character(slot_index).is_empty():
		return false
	_save_data["selected_character_slot"] = slot_index
	request_save()
	return true


func get_selected_character_slot() -> int:
	return int(_save_data.get("selected_character_slot", -1))


func get_character_section(section_name: String, slot_index: int = -1, default_value: Variant = {}) -> Variant:
	var resolved_slot: = _resolve_slot_index(slot_index)
	var character: = get_character(resolved_slot)
	if character.is_empty():
		return _duplicate_value(default_value)
	return _duplicate_value(character.get(section_name, default_value))


func set_character_section(section_name: String, value: Variant, slot_index: int = -1, immediate: = false) -> bool:
	var resolved_slot: = _resolve_slot_index(slot_index)
	var slots: = _save_data.get("characters", []) as Array
	if resolved_slot < 0 or resolved_slot >= slots.size() or not (slots[resolved_slot] is Dictionary):
		return false
	var character: = slots[resolved_slot] as Dictionary
	character[section_name] = _duplicate_value(value)
	request_save(immediate)
	return true


func get_account_section(section_name: String, default_value: Variant = {}) -> Variant:
	return _duplicate_value(_save_data.get(section_name, default_value))


func set_account_section(section_name: String, value: Variant, immediate: = false) -> void :
	_save_data[section_name] = _duplicate_value(value)
	request_save(immediate)


func update_last_safe_location(scene_id: String, entry_point: String, position: Vector2, direction: int) -> void :
	if scene_id.strip_edges().is_empty():
		return
	set_character_section("last_safe_location", {
		"scene_id": scene_id, 
		"entry_point": entry_point, 
		"position": {"x": position.x, "y": position.y}, 
		"direction": -1 if direction < 0 else 1, 
	})


func get_last_safe_location(slot_index: int = -1) -> Dictionary:
	return get_character_section("last_safe_location", slot_index, _default_safe_location()) as Dictionary


func request_save(immediate: = false) -> void :
	if not has_active_profile():
		return
	_save_pending = true
	_mark_unsaved()
	if immediate:
		flush_save()
	elif _save_timer != null:
		_save_timer.start(SAVE_DEBOUNCE_SECONDS)


func flush_save() -> bool:
	if not has_active_profile() or _save_data.is_empty():
		return false
	if _save_in_progress:
		_save_pending = true
		return false

	_save_in_progress = true
	_save_pending = false
	var success: = _write_save_file()
	_save_in_progress = false
	if success and not _save_pending:
		_set_save_state(false, "")
		save_completed.emit(_get_profile_file_path(SAVE_FILE_NAME))
	elif success:
		_mark_unsaved()
		if _save_timer != null:
			_save_timer.start(SAVE_DEBOUNCE_SECONDS)
	else:
		_save_pending = true
		_mark_unsaved()
		if _save_timer != null:
			_save_timer.start(SAVE_RETRY_SECONDS)
	return success


func retry_save_now() -> bool:
	if _save_timer != null:
		_save_timer.stop()
	return flush_save()


func force_quit_without_saving() -> void :
	_force_quit_requested = true
	get_tree().quit()


func _flush_save_queue() -> void :
	flush_save()


func _load_profile_data() -> Dictionary:
	_profile_load_error = ""
	_loaded_from_recovery = false
	var candidates: Array[Dictionary] = [
		{"file_name": SAVE_FILE_NAME, "recovery": false}, 
		{"file_name": TEMP_FILE_NAME, "recovery": true}, 
		{"file_name": PREVIOUS_FILE_NAME, "recovery": true}, 
		{"file_name": BACKUP_FILE_NAME, "recovery": true}, 
	]
	var existing_candidates: Array[Dictionary] = []
	for candidate: Dictionary in candidates:
		var file_name: = str(candidate.get("file_name", ""))
		if FileAccess.file_exists(_get_profile_file_path(file_name)):
			existing_candidates.append(candidate)
	if existing_candidates.is_empty():
		return _build_default_save_data()

	var original_encryption_profile_id: = _encryption_profile_id
	var encryption_profile_ids: = _get_encryption_profile_id_candidates()
	var invalid_files: Array[String] = []

	for candidate: Dictionary in existing_candidates:
		var file_name: = str(candidate.get("file_name", ""))
		var candidate_error: = "无法解密或内容无效"
		for encryption_profile_id: String in encryption_profile_ids:
			_encryption_profile_id = encryption_profile_id
			var loaded: = _read_save_file(_get_profile_file_path(file_name))
			if not loaded.is_empty():
				var compatibility_error: = _get_client_compatibility_error(loaded)
				if not compatibility_error.is_empty():
					_encryption_profile_id = original_encryption_profile_id
					_profile_load_error = compatibility_error
					return {}
			var validation_error: = _get_save_validation_error(loaded)
			if not validation_error.is_empty():
				candidate_error = validation_error
				continue
			_loaded_from_recovery = bool(candidate.get("recovery", false))
			if encryption_profile_id != original_encryption_profile_id:
				push_warning(
					"已使用旧档案名恢复手动改名后的存档：%s -> %s"
					%[encryption_profile_id, active_profile_id]
				)
			return loaded
		invalid_files.append("%s：%s" % [file_name, candidate_error])

	_encryption_profile_id = original_encryption_profile_id
	_profile_load_error = "档案中存在损坏、不兼容或改名后无法解密的存档，未覆盖原文件：%s" % "；".join(invalid_files)
	return {}


func _read_save_file(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file: = FileAccess.open_encrypted(
		path, 
		FileAccess.READ, 
		_get_save_key()
	)
	if file == null:
		return {}
	var envelope_value: Variant = file.get_var(false)
	file.close()
	if not (envelope_value is Dictionary):
		return {}
	var envelope: = envelope_value as Dictionary
	if str(envelope.get("magic", "")) != SAVE_CONTAINER_MAGIC:
		return {}
	if int(envelope.get("container_version", 0)) != SAVE_CONTAINER_VERSION:
		return {}
	var payload: Variant = envelope.get("payload")
	return (payload as Dictionary).duplicate(true) if payload is Dictionary else {}


func _write_save_file() -> bool:
	_strip_nonpersistent_process_data()
	var profile_dir: = _get_profile_directory()
	var absolute_dir: = ProjectSettings.globalize_path(profile_dir)
	var dir_error: = DirAccess.make_dir_recursive_absolute(absolute_dir)
	if dir_error != OK and dir_error != ERR_ALREADY_EXISTS:
		_report_save_failure("无法创建存档目录：%s（错误码 %d）" % [profile_dir, dir_error])
		return false
	if not _ensure_profile_metadata():
		return false

	var temp_path: = _get_profile_file_path(TEMP_FILE_NAME)
	var temp_file: = FileAccess.open_encrypted(
		temp_path, 
		FileAccess.WRITE, 
		_get_save_key()
	)
	if temp_file == null:
		_report_save_failure("无法写入临时存档：%s（错误码 %d）" % [temp_path, FileAccess.get_open_error()])
		return false
	temp_file.store_var({
		"magic": SAVE_CONTAINER_MAGIC, 
		"container_version": SAVE_CONTAINER_VERSION, 
		"payload": _save_data, 
	}, false)
	temp_file.flush()
	var write_error: = temp_file.get_error()
	temp_file.close()
	if write_error != OK:
		_report_save_failure("临时存档写入不完整（错误码 %d）" % write_error)
		return false

	var temp_validation_error: = _get_save_validation_error(_read_save_file(temp_path))
	if not temp_validation_error.is_empty():
		_report_save_failure("临时存档校验失败：%s" % temp_validation_error)
		return false

	var dir: = DirAccess.open(profile_dir)
	if dir == null:
		_report_save_failure("无法打开存档目录：%s" % profile_dir)
		return false
	var replace_success: = false
	if _compatibility_upgrade_pending:
		replace_success = _replace_main_save_for_compatibility_upgrade(dir)
	elif _loaded_from_recovery:
		replace_success = _install_recovered_save(dir)
	else:
		replace_success = _replace_main_save(dir)
	if replace_success:
		_compatibility_upgrade_pending = false
	return replace_success


func _replace_main_save_for_compatibility_upgrade(dir: DirAccess) -> bool:


	for recovery_file_name: String in [PREVIOUS_FILE_NAME, BACKUP_FILE_NAME]:
		if dir.file_exists(recovery_file_name):
			var remove_error: = dir.remove(recovery_file_name)
			if remove_error != OK:
				_report_save_failure("无法刷新版本升级恢复文件 %s（错误码 %d）" % [recovery_file_name, remove_error])
				return false
		var copy_error: = DirAccess.copy_absolute(
			ProjectSettings.globalize_path(_get_profile_file_path(TEMP_FILE_NAME)), 
			ProjectSettings.globalize_path(_get_profile_file_path(recovery_file_name))
		)
		if copy_error != OK:
			_report_save_failure("无法生成版本升级恢复文件 %s（错误码 %d）" % [recovery_file_name, copy_error])
			return false

	if dir.file_exists(PRE_VERSION_UPGRADE_FILE_NAME):
		var remove_archive_error: = dir.remove(PRE_VERSION_UPGRADE_FILE_NAME)
		if remove_archive_error != OK:
			_report_save_failure("无法清理旧的升级前存档副本（错误码 %d）" % remove_archive_error)
			return false

	var archived_main: = false
	if dir.file_exists(SAVE_FILE_NAME):
		var archive_error: = dir.rename(SAVE_FILE_NAME, PRE_VERSION_UPGRADE_FILE_NAME)
		if archive_error != OK:
			_report_save_failure("无法保留版本升级前的主存档（错误码 %d）" % archive_error)
			return false
		archived_main = true

	var install_error: = dir.rename(TEMP_FILE_NAME, SAVE_FILE_NAME)
	if install_error != OK:
		if archived_main:
			dir.rename(PRE_VERSION_UPGRADE_FILE_NAME, SAVE_FILE_NAME)
		_report_save_failure("无法安装版本升级后的主存档（错误码 %d）" % install_error)
		return false
	_loaded_from_recovery = false
	return true


func _install_recovered_save(dir: DirAccess) -> bool:
	var moved_corrupt_main: = false
	if dir.file_exists(SAVE_FILE_NAME):
		if dir.file_exists(CORRUPT_FILE_NAME):
			var remove_corrupt_error: = dir.remove(CORRUPT_FILE_NAME)
			if remove_corrupt_error != OK:
				_report_save_failure("无法清理旧的损坏存档副本（错误码 %d）" % remove_corrupt_error)
				return false
		var preserve_error: = dir.rename(SAVE_FILE_NAME, CORRUPT_FILE_NAME)
		if preserve_error != OK:
			_report_save_failure("无法保留损坏的主存档（错误码 %d）" % preserve_error)
			return false
		moved_corrupt_main = true

	var install_error: = dir.rename(TEMP_FILE_NAME, SAVE_FILE_NAME)
	if install_error != OK:
		if moved_corrupt_main:
			dir.rename(CORRUPT_FILE_NAME, SAVE_FILE_NAME)
		_report_save_failure("无法从备份恢复主存档（错误码 %d）" % install_error)
		return false
	_loaded_from_recovery = false
	return true


func _replace_main_save(dir: DirAccess) -> bool:
	if dir.file_exists(PREVIOUS_FILE_NAME):
		var stale_previous_error: = OK
		if dir.file_exists(BACKUP_FILE_NAME):
			stale_previous_error = dir.remove(PREVIOUS_FILE_NAME)
		else:
			stale_previous_error = dir.rename(PREVIOUS_FILE_NAME, BACKUP_FILE_NAME)
		if stale_previous_error != OK:
			_report_save_failure("无法整理上次未完成的存档事务（错误码 %d）" % stale_previous_error)
			return false

	var moved_main: = false
	if dir.file_exists(SAVE_FILE_NAME):
		var preserve_error: = dir.rename(SAVE_FILE_NAME, PREVIOUS_FILE_NAME)
		if preserve_error != OK:
			_report_save_failure("无法保留当前主存档（错误码 %d）" % preserve_error)
			return false
		moved_main = true

	var install_error: = dir.rename(TEMP_FILE_NAME, SAVE_FILE_NAME)
	if install_error != OK:
		var rollback_error: = OK
		if moved_main:
			rollback_error = dir.rename(PREVIOUS_FILE_NAME, SAVE_FILE_NAME)
		var rollback_text: = ""
		if rollback_error != OK:
			rollback_text = "，且旧主存档回滚失败（错误码 %d）" % rollback_error
		_report_save_failure("无法替换主存档（错误码 %d）%s" % [install_error, rollback_text])
		return false

	if not moved_main:
		return true
	if dir.file_exists(BACKUP_FILE_NAME):
		var remove_backup_error: = dir.remove(BACKUP_FILE_NAME)
		if remove_backup_error != OK:
			_report_save_failure("主存档已写入，但无法更新备份（错误码 %d）" % remove_backup_error)
			return false
	var backup_error: = dir.rename(PREVIOUS_FILE_NAME, BACKUP_FILE_NAME)
	if backup_error != OK:
		_report_save_failure("主存档已写入，但无法生成备份（错误码 %d）" % backup_error)
		return false
	return true


func _get_save_validation_error(data: Dictionary) -> String:
	if data.is_empty():
		return "文件不是有效的加密二进制存档或内容为空"
	var schema_version: = int(data.get("schema_version", 0))
	if schema_version <= 0:
		return "缺少有效的 schema_version"
	if schema_version > SCHEMA_VERSION:
		return "存档版本 %d 高于当前支持版本 %d" % [schema_version, SCHEMA_VERSION]
	var save_version_value: Variant = data.get(SAVE_VERSION_METADATA_KEY, {})
	if data.has(SAVE_VERSION_METADATA_KEY) and not (save_version_value is Dictionary):
		return "%s 不是对象" % SAVE_VERSION_METADATA_KEY
	if save_version_value is Dictionary and not (save_version_value as Dictionary).is_empty():
		var minimum_client_build: = int(
			(save_version_value as Dictionary).get("minimum_client_build", 0)
		)
		if minimum_client_build <= 0:
			return "%s.minimum_client_build 无效" % SAVE_VERSION_METADATA_KEY
	var characters_value: Variant = data.get("characters")
	if not (characters_value is Array):
		return "characters 不是数组"
	var characters: = characters_value as Array
	if characters.size() > CHARACTER_SLOT_COUNT:
		return "角色槽数量超过 %d" % CHARACTER_SLOT_COUNT
	for slot_index: int in range(characters.size()):
		var character_value: Variant = characters[slot_index]
		if character_value == null:
			continue
		if not (character_value is Dictionary):
			return "角色槽 %d 不是对象" % slot_index
		var character: = character_value as Dictionary
		for section_name: String in ["identity", "progression", "equipment", "inventory", "hotbar", "skills", "tasks", "cards", "shenshou", "guardian", "last_safe_location"]:
			if character.has(section_name) and not (character.get(section_name) is Dictionary):
				return "角色槽 %d 的 %s 不是对象" % [slot_index, section_name]
		var inventory_value: Variant = character.get("inventory", {})
		if inventory_value is Dictionary:
			var inventory: = inventory_value as Dictionary
			for inventory_key: String in ["equipment", "items", "materials"]:
				if inventory.has(inventory_key) and not (inventory.get(inventory_key) is Array):
					return "角色槽 %d 的 inventory.%s 不是数组" % [slot_index, inventory_key]
	var storehouse_value: Variant = data.get("account_storehouse")
	if not (storehouse_value is Dictionary):
		return "account_storehouse 不是对象"
	if not ((storehouse_value as Dictionary).get("entries") is Array):
		return "account_storehouse.entries 不是数组"
	return ""


func _get_client_compatibility_error(data: Dictionary) -> String:
	var minimum_client_build: = _get_minimum_client_build(data)
	if CURRENT_CLIENT_BUILD >= minimum_client_build:
		return ""
	var save_version: = _get_last_client_version(data)
	return (
		"该存档已由 %s 或更高版本客户端使用，当前客户端 %s 无法打开，请使用新版本客户端"
		%[save_version, CURRENT_CLIENT_VERSION]
	)


func _get_minimum_client_build(data: Dictionary) -> int:
	var save_version_value: Variant = data.get(SAVE_VERSION_METADATA_KEY, {})
	if not (save_version_value is Dictionary):
		return LEGACY_CLIENT_BUILD
	return int((save_version_value as Dictionary).get("minimum_client_build", LEGACY_CLIENT_BUILD))


func _get_last_client_version(data: Dictionary) -> String:
	var save_version_value: Variant = data.get(SAVE_VERSION_METADATA_KEY, {})
	if not (save_version_value is Dictionary):
		return LEGACY_CLIENT_VERSION
	var version: = str(
		(save_version_value as Dictionary).get("last_client_version", LEGACY_CLIENT_VERSION)
	).strip_edges()
	return version if not version.is_empty() else LEGACY_CLIENT_VERSION


func _requires_compatibility_upgrade(data: Dictionary) -> bool:
	return (
		int(data.get("schema_version", 0)) < SCHEMA_VERSION
		or _get_minimum_client_build(data) < CURRENT_CLIENT_BUILD
	)


func _report_save_failure(message: String, mark_unsaved: = true) -> void :
	push_error(message)
	_set_save_state(has_unsaved_changes or mark_unsaved, message)
	save_failed.emit(message)


func _mark_unsaved() -> void :
	_set_save_state(true, last_save_error)


func _set_save_state(unsaved: bool, error_message: String) -> void :
	var changed: = has_unsaved_changes != unsaved or last_save_error != error_message
	has_unsaved_changes = unsaved
	last_save_error = error_message
	if changed:
		save_state_changed.emit(has_unsaved_changes, last_save_error)


func _restore_profile(
	profile_name: String, 
	profile_id: String, 
	encryption_profile_id: String, 
	save_data: Dictionary, 
	loaded_from_recovery: bool, 
	compatibility_upgrade_pending: bool
) -> void :
	if _save_timer != null:
		_save_timer.stop()
	active_profile_name = profile_name
	active_profile_id = profile_id
	_encryption_profile_id = encryption_profile_id
	_save_data = save_data.duplicate(true)
	_save_pending = false
	_loaded_from_recovery = loaded_from_recovery
	_compatibility_upgrade_pending = compatibility_upgrade_pending


func _normalize_save_data() -> void :
	_save_data["schema_version"] = SCHEMA_VERSION
	var save_version: Dictionary = {}
	var save_version_value: Variant = _save_data.get(SAVE_VERSION_METADATA_KEY, {})
	if save_version_value is Dictionary:
		save_version = (save_version_value as Dictionary).duplicate(true)
	save_version["last_client_version"] = CURRENT_CLIENT_VERSION
	save_version["last_client_build"] = CURRENT_CLIENT_BUILD
	save_version["minimum_client_build"] = maxi(
		_get_minimum_client_build(_save_data), 
		CURRENT_CLIENT_BUILD
	)
	_save_data[SAVE_VERSION_METADATA_KEY] = save_version
	_save_data["account"] = {
		"id": active_profile_id, 
		"display_name": active_profile_name, 
	}
	var slots: Array = _save_data.get("characters", [])
	slots.resize(CHARACTER_SLOT_COUNT)
	_save_data["characters"] = slots
	if not _save_data.has("selected_character_slot"):
		_save_data["selected_character_slot"] = -1
	if not (_save_data.get("account_storehouse", {}) is Dictionary):
		_save_data["account_storehouse"] = _default_storehouse()
	else:
		var storehouse: = _save_data["account_storehouse"] as Dictionary
		if not storehouse.has("entries") or not (storehouse.get("entries") is Array):
			storehouse["entries"] = []
	_strip_nonpersistent_process_data()


func _strip_nonpersistent_process_data() -> void :
	_save_data.erase("saved_at")
	var slots_value: Variant = _save_data.get("characters", [])
	if not (slots_value is Array):
		return

	for slot_value: Variant in slots_value as Array:
		if not (slot_value is Dictionary):
			continue
		var character: = slot_value as Dictionary
		var progression_value: Variant = character.get("progression", {})
		if progression_value is Dictionary:
			var progression: = progression_value as Dictionary
			progression.erase("hp")
			progression.erase("mp")

		var shenshou_value: Variant = character.get("shenshou", {})
		if shenshou_value is Dictionary:
			var pets_value: Variant = (shenshou_value as Dictionary).get("pets", {})
			if pets_value is Dictionary:
				for pet_value: Variant in (pets_value as Dictionary).values():
					if pet_value is Dictionary:
						(pet_value as Dictionary).erase("claimed_at")
						(pet_value as Dictionary).erase("evolved_at")

		var guardian_value: Variant = character.get("guardian", {})
		if guardian_value is Dictionary:
			var guardians_value: Variant = (guardian_value as Dictionary).get("guardians", {})
			if guardians_value is Dictionary:
				for guardian_data: Variant in (guardians_value as Dictionary).values():
					if guardian_data is Dictionary:
						(guardian_data as Dictionary).erase("claimed_at")


func _build_default_save_data() -> Dictionary:
	return {
		"schema_version": SCHEMA_VERSION, 
		SAVE_VERSION_METADATA_KEY: {
			"last_client_version": CURRENT_CLIENT_VERSION, 
			"last_client_build": CURRENT_CLIENT_BUILD, 
			"minimum_client_build": CURRENT_CLIENT_BUILD, 
		}, 
		"account": {"id": active_profile_id, "display_name": active_profile_name}, 
		"selected_character_slot": -1, 
		"characters": _build_empty_character_slots(), 
		"account_storehouse": _default_storehouse(), 
	}


func _build_empty_character_slots() -> Array:
	var slots: Array = []
	slots.resize(CHARACTER_SLOT_COUNT)
	return slots


func _build_default_character(identity: Dictionary, slot_index: int) -> Dictionary:
	var normalized_identity: = identity.duplicate(true)
	normalized_identity["slot_index"] = slot_index
	var role_id: = str(normalized_identity.get("role_id", ""))
	return {
		"identity": normalized_identity, 
		"progression": {
			"level": 1, 
			"exp": 0, 
			"total_exp": 0, 
			"max_hp": 10, 
			"max_mp": 10, 
		}, 
		"equipment": {}, 
		"inventory": {"equipment": [], "items": [], "materials": []}, 
		"hotbar": {"skills": ["", "", "", "", ""], "items": [0, 0, 0, 0, 0]}, 
		"skills": {
			"schema_version": 1, 
			"role_id": role_id, 
			"levels": _build_default_skill_levels(), 
		}, 
		"tasks": {"schema_version": 1, "tasks": {}, "claimed_reward_ids": []}, 
		"cards": {"activated_ids": []}, 
		"shenshou": {"pets": {}, "following_id": ""}, 
		"guardian": {"guardians": {}, "following_id": 0}, 
		"last_safe_location": _default_safe_location(), 
	}


func _build_default_skill_levels() -> Dictionary:
	var levels: Dictionary = {}
	for index: int in range(1, 16):
		levels["技能%02d" % index] = 1
	return levels


func _get_character_name_error(character_name: String) -> String:
	if character_name.is_empty():
		return "name_empty"
	if character_name.length() < CHARACTER_NAME_MIN_LENGTH:
		return "name_too_short"
	if character_name.length() > CHARACTER_NAME_MAX_LENGTH:
		return "name_too_long"
	for index: int in range(character_name.length()):
		var codepoint: = character_name.unicode_at(index)
		if String.chr(codepoint).strip_edges().is_empty():
			return "name_has_space"
	for index: int in range(character_name.length()):
		if character_name.unicode_at(index) < 32:
			return "name_has_invalid_chars"
	for invalid_char: String in INVALID_CHARACTER_NAME_CHARS:
		if character_name.contains(invalid_char):
			return "name_has_invalid_chars"
	return ""


func _default_safe_location() -> Dictionary:
	return {
		"scene_id": "一气学院", 
		"entry_point": "LoginPoint", 
		"position": {}, 
		"direction": 1, 
	}


func _default_storehouse() -> Dictionary:
	return {"entries": []}


func _resolve_slot_index(slot_index: int) -> int:
	if slot_index >= 0:
		return slot_index
	return int(_save_data.get("selected_character_slot", -1))


func _load_profile_encryption_id() -> String:
	var config: = ConfigFile.new()
	if config.load(_get_profile_metadata_path()) != OK:
		return active_profile_id
	var metadata_version: = int(
		config.get_value(PROFILE_METADATA_SECTION, PROFILE_METADATA_VERSION_KEY, 0)
	)
	if metadata_version <= 0 or metadata_version > PROFILE_METADATA_VERSION:
		return active_profile_id
	var encryption_profile_id: = str(
		config.get_value(PROFILE_METADATA_SECTION, PROFILE_METADATA_ENCRYPTION_ID_KEY, "")
	).strip_edges()
	return encryption_profile_id if not encryption_profile_id.is_empty() else active_profile_id


func _get_encryption_profile_id_candidates() -> Array[String]:
	var candidates: Array[String] = []
	_append_unique_encryption_profile_id(candidates, _encryption_profile_id)
	_append_unique_encryption_profile_id(candidates, active_profile_id)
	_append_unique_encryption_profile_id(candidates, RECENT_LOGIN_HISTORY_SCRIPT.load_profile_name())
	for account_data: Dictionary in RECENT_LOGIN_HISTORY_SCRIPT.load_recent_accounts():
		_append_unique_encryption_profile_id(candidates, str(account_data.get("account", "")))
	return candidates


func _append_unique_encryption_profile_id(candidates: Array[String], profile_id: String) -> void :
	var normalized_profile_id: = profile_id.strip_edges()
	if not normalized_profile_id.is_empty() and normalized_profile_id not in candidates:
		candidates.append(normalized_profile_id)


func _ensure_profile_metadata() -> bool:
	if _encryption_profile_id.is_empty():
		_encryption_profile_id = active_profile_id
	var metadata_path: = _get_profile_metadata_path()
	var config: = ConfigFile.new()
	if config.load(metadata_path) == OK:
		var stored_version: = int(
			config.get_value(PROFILE_METADATA_SECTION, PROFILE_METADATA_VERSION_KEY, 0)
		)
		var stored_encryption_id: = str(
			config.get_value(PROFILE_METADATA_SECTION, PROFILE_METADATA_ENCRYPTION_ID_KEY, "")
		).strip_edges()
		if stored_version == PROFILE_METADATA_VERSION and stored_encryption_id == _encryption_profile_id:
			return true

	config.set_value(PROFILE_METADATA_SECTION, PROFILE_METADATA_VERSION_KEY, PROFILE_METADATA_VERSION)
	config.set_value(
		PROFILE_METADATA_SECTION, 
		PROFILE_METADATA_ENCRYPTION_ID_KEY, 
		_encryption_profile_id
	)
	var save_error: = config.save(metadata_path)
	if save_error != OK:
		_report_save_failure("无法写入档案元数据：%s（错误码 %d）" % [metadata_path, save_error])
		return false
	return true


func _get_profile_directory() -> String:
	return "%s/%s" % [SAVE_ROOT, active_profile_id]


func _get_profile_metadata_path() -> String:
	return "%s/%s" % [_get_profile_directory(), PROFILE_METADATA_FILE_NAME]


func _get_profile_file_path(file_name: String) -> String:
	return "%s/%s" % [_get_profile_directory(), file_name]


func _get_save_key() -> PackedByteArray:
	var application_name: = str(ProjectSettings.get_setting("application/config/name", "YierPai"))
	var encryption_profile_id: = _encryption_profile_id
	if encryption_profile_id.is_empty():
		encryption_profile_id = active_profile_id
	return ("%s|%s|%s" % [SAVE_ENCRYPTION_PEPPER, application_name, encryption_profile_id]).sha256_buffer()


func _duplicate_value(value: Variant) -> Variant:
	if value is Dictionary or value is Array:
		return value.duplicate(true)
	return value
