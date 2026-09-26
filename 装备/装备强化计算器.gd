class_name 装备强化计算器
extends RefCounted

const 最高强化等级: = 12
const 旧装备最低品质: = 装备图标数据.质量类型.绿色
const 旧装备最高品质: = 装备图标数据.质量类型.橙色
const DEF_ADDED_UNTURN: = [
	2902.8, 
	3483.3, 
	4180.0, 
	5016.0, 
	6019.2, 
	7223.1, 
	8667.7, 
	10401.2, 
	11441.3, 
	12585.5, 
	13844.0, 
]
const HP_ADDED_UNTURN: = [
	101597, 
	121917, 
	146300, 
	175560, 
	210672, 
	252807, 
	303368, 
	364042, 
	400446, 
	440491, 
	484540, 
]

const 防具部位系数: = {
	装备图标数据.部位类型.头: 0.2, 
	装备图标数据.部位类型.护手: 0.15, 
	装备图标数据.部位类型.衣服: 0.2, 
	装备图标数据.部位类型.腰带: 0.13, 
	装备图标数据.部位类型.护腿: 0.17, 
	装备图标数据.部位类型.鞋子: 0.15, 
}


static func 规范使用等级(使用等级: int) -> int:
	return 120 if 使用等级 > 115 else 使用等级


static func 获取品质最高强化等级(品质等级: int) -> int:
	match 品质等级:
		装备图标数据.质量类型.绿色:
			return 4
		装备图标数据.质量类型.蓝色:
			return 8
		装备图标数据.质量类型.紫色, 装备图标数据.质量类型.橙色:
			return 12
	return 0


static func 计算等级系数(使用等级: int) -> float:
	var 等级: = 规范使用等级(使用等级)
	if 等级 < 45:
		return 1.0
	return sqrt(float(等级 - 28) / 18.0)


static func 计算武器攻击加成(使用等级: int, 品质等级: int, 强化等级: int) -> int:
	if not _是旧版可强化品质(品质等级):
		return 0

	var 等级: = 规范使用等级(使用等级)
	var 当前强化等级: = clampi(强化等级, 0, 最高强化等级)
	var 累计加成: = 0
	for 当前等级 in range(1, 当前强化等级 + 1):
		累计加成 += 计算武器单级攻击加成(等级, 品质等级, 当前等级)
	return 累计加成


static func 计算武器单级攻击加成(使用等级: int, 品质等级: int, 强化等级: int) -> int:
	if not _是旧版可强化品质(品质等级):
		return 0
	var 等级: = 规范使用等级(使用等级)
	return _计算武器每级攻击加成(等级, 品质等级, 强化等级)


static func 计算武器奖励属性(使用等级: int, 品质等级: int, 强化等级: int) -> Dictionary:
	var 奖励: = {
		"敏捷": 0, 
		"力量": 0, 
		"命中": 0, 
	}
	if not _是旧版可强化品质(品质等级):
		return 奖励

	var 等级: = 规范使用等级(使用等级)
	var 当前强化等级: = clampi(强化等级, 0, 最高强化等级)
	var 敏捷系数: = 0.32
	var 力量系数: = 0.48
	var 命中系数: = 0.64
	var 等级倍率: = 1.0
	if 品质等级 != 装备图标数据.质量类型.绿色:
		敏捷系数 = 0.4
		力量系数 = 0.6
		命中系数 = 0.8
		if 等级 >= 45:
			等级倍率 = 计算等级系数(等级)

	if 当前强化等级 >= 4:
		奖励["敏捷"] = maxi(1, floori(等级倍率 * float(等级) * 敏捷系数))
	if 当前强化等级 >= 8:
		奖励["力量"] = maxi(1, floori(等级倍率 * float(等级) * 力量系数))
	if 当前强化等级 >= 12:
		奖励["命中"] = maxi(1, floori(等级倍率 * float(等级) * 命中系数))
	return 奖励


static func 计算防具奖励属性(使用等级: int, 品质等级: int, 强化等级: int) -> Dictionary:
	var 奖励: = {
		"体质": 0, 
		"HP恢复": 0, 
		"闪避": 0, 
	}
	if not _是旧版可强化品质(品质等级):
		return 奖励

	var 等级: = 规范使用等级(使用等级)
	var 当前强化等级: = clampi(强化等级, 0, 最高强化等级)
	var 体质系数: = 0.12
	var HP恢复系数: = 0.18
	var 闪避系数: = 0.24
	var 等级倍率: = 1.0
	if 品质等级 != 装备图标数据.质量类型.绿色:
		体质系数 = 0.15
		HP恢复系数 = 0.225
		闪避系数 = 0.3
		if 等级 >= 45:
			等级倍率 = 计算等级系数(等级)

	if 当前强化等级 >= 4:
		奖励["体质"] = maxi(1, floori(等级倍率 * float(等级) * 体质系数))
	if 当前强化等级 >= 8:
		奖励["HP恢复"] = maxi(1, floori(等级倍率 * float(等级) * HP恢复系数))
	if 当前强化等级 >= 12:
		奖励["闪避"] = maxi(1, floori(等级倍率 * float(等级) * 闪避系数))
	return 奖励


static func 计算防具基础表索引(使用等级: int, 品质等级: int) -> int:
	var 等级: = maxi(规范使用等级(使用等级), 30)
	var 品质: = maxi(品质等级, 2)
	return floori(float(等级 + 品质 * 10 - 20) / 10.0) - 3


static func 计算防具强化系数(强化等级: int) -> float:
	if 强化等级 <= 34:
		return 0.02 + float(强化等级) * 0.02
	return 0.71 + float(强化等级 - 35) * 0.01


static func 计算防具主强化倍率(部位: int, 强化等级: int) -> float:
	var 部位倍率: = float(防具部位系数.get(部位, 0.0))
	return 计算防具强化系数(强化等级) * 0.2 * 部位倍率


static func 计算防具主强化加成(
	使用等级: int, 
	品质等级: int, 
	部位: int, 
	强化等级: int, 
	防御基础表: Array = [], 
	_HP基础表: Array = []
) -> Dictionary:
	var 实际防御基础表: Array = DEF_ADDED_UNTURN if 防御基础表.is_empty() else 防御基础表
	var 表索引: = 计算防具基础表索引(使用等级, 品质等级)
	if (
		表索引 < 0
		or 表索引 >= 实际防御基础表.size()
		or not 防具部位系数.has(部位)
	):
		return {}

	var 强化倍率: = 计算防具主强化倍率(部位, 强化等级)
	return {
		"防御力": float(实际防御基础表[表索引]) * 强化倍率, 
		"表索引": 表索引, 
	}


static func 计算装备强化加成(
	装备资源: 装备图标数据, 
	强化等级: int, 
	防御基础表: Array = [], 
	HP基础表: Array = []
) -> Dictionary:
	var 总加成: = {
		"攻击力最小值": 0, 
		"攻击力最大值": 0, 
		"防御力": 0.0, 
		"力量": 0, 
		"敏捷": 0, 
		"体质": 0, 
		"HP": 0.0, 
		"HP恢复": 0, 
		"命中": 0, 
		"闪避": 0, 
	}
	if 装备资源 == null or not _是旧版可强化品质(int(装备资源.质量)):
		return 总加成

	var 使用等级: = int(装备资源.使用等级)
	var 品质等级: = int(装备资源.质量)
	if int(装备资源.部位) == 装备图标数据.部位类型.武器:
		var 攻击加成: = 计算武器攻击加成(使用等级, 品质等级, 强化等级)
		总加成["攻击力最小值"] = 攻击加成
		总加成["攻击力最大值"] = 攻击加成
		_累加属性(总加成, 计算武器奖励属性(使用等级, 品质等级, 强化等级))
		return 总加成

	if not 防具部位系数.has(int(装备资源.部位)):
		return 总加成

	_累加属性(总加成, 计算防具奖励属性(使用等级, 品质等级, 强化等级))
	var 主强化加成: = 计算防具主强化加成(
		使用等级, 
		品质等级, 
		int(装备资源.部位), 
		强化等级, 
		防御基础表, 
		HP基础表
	)
	_累加属性(总加成, 主强化加成)
	return 总加成


static func _计算武器每级攻击加成(等级: int, 品质等级: int, 强化等级: int) -> int:
	if 品质等级 == 装备图标数据.质量类型.绿色:
		match 强化等级:
			1, 2, 4, 5:
				return floori(float(等级) / 5.0)
			3, 6:
				return floori(float(等级) * 0.6)
			7:
				return floori(float(等级) * 0.3)
			8:
				return floori(float(等级) / 4.0)
			9:
				return floori(float(等级) * 0.9)
			10, 11:
				return floori(float(等级) * 0.4)
			12:
				return floori(float(等级) * 1.2)
		return 0

	var 等级值: = float(等级)
	if 等级 >= 45:
		等级值 *= 计算等级系数(等级)
		match 强化等级:
			1, 2, 4, 5:
				return floori(等级值 / 4.0)
			3, 9:
				return floori(等级值)
			6, 7:
				return floori(等级值 * 3.0 / 8.0)
			8:
				return floori(等级值 * 1.5)
			10, 11:
				return floori(等级值 / 2.0)
			12:
				return floori(等级值 * 2.0)
		return 0

	match 强化等级:
		1, 2, 4, 5:
			return floori(等级值 / 4.0)
		3, 6:
			return floori(等级值)
		7, 8:
			return floori(等级值 * 3.0 / 8.0)
		9:
			return floori(等级值 * 1.5)
		10, 11:
			return floori(等级值 / 2.0)
		12:
			return floori(等级值 * 2.0)
	return 0


static func _是旧版可强化品质(品质等级: int) -> bool:
	return 品质等级 >= 旧装备最低品质 and 品质等级 <= 旧装备最高品质


static func _累加属性(目标: Dictionary, 来源: Dictionary) -> void :
	for 属性名 in 来源:
		if not 目标.has(属性名):
			continue
		目标[属性名] = 目标[属性名] + 来源[属性名]
