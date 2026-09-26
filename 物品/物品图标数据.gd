extends Resource

class_name 物品图标数据

enum 质量类型{
	白色 = 1, 
	绿色 = 2, 
	蓝色 = 3, 
	紫色 = 4, 
	橙色 = 5, 
	红色 = 6, 
	金色 = 7
}

enum 功效类型{
	HP = 1, 
	MP = 2, 
	HP和MP = 3
}

@export var 材料图片: Texture2D
@export var id: int = 0
@export var 名称: String = ""
@export var 质量: 质量类型
@export var 使用等级: int = 1
@export var 功效: 功效类型
@export var 功效数值: float
@export var HP功效数值: float
@export var MP功效数值: float
@export var 功效时间: int
@export var cd: int

@export var 描述: String = ""
@export var 最大堆叠数量: int = 999
