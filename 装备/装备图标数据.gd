extends Resource

class_name 装备图标数据

enum 部位类型{
	头 = 1, 
	项链 = 2, 
	护手 = 3, 
	武器 = 4, 
	戒指 = 5, 
	衣服 = 6, 
	腰带 = 7, 
	护腿 = 8, 
	鞋子 = 9, 
	玉佩 = 10
}

enum 角色类型{
	猴子 = 1, 
	兔子 = 2, 
	熊猫 = 3, 
	龙人 = 4
}

enum 质量类型{
	白色 = 1, 
	绿色 = 2, 
	蓝色 = 3, 
	紫色 = 4, 
	橙色 = 5, 
	红色 = 6, 
	金色 = 7
}

@export var 部位: 部位类型
@export var 角色: 角色类型
@export var 角色图标: Texture2D

@export var 装备图片: Texture2D
@export var id: int = 0
@export var 外观来源ID: int = 0
@export var 名称: String = ""
@export var 质量: 质量类型
@export var 攻击力最小值: int
@export var 攻击力最大值: int
@export var 使用等级: int

@export var 防御力: int
@export var 力量: int
@export var 敏捷: int
@export var 体质: int
@export var 气力: int
@export var HP: int
@export var HP恢复: int
@export var MP: int
@export var MP恢复: int
@export var 命中: int
@export var 闪避: int
@export var 致命一击: int

@export var 最大堆叠数量: int = 1
@export var 描述: String = ""
