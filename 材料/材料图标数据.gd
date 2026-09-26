extends Resource

class_name 材料图标数据

enum 质量类型{
	白色 = 1, 
	绿色 = 2, 
	蓝色 = 3, 
	紫色 = 4, 
	橙色 = 5, 
	红色 = 6, 
	金色 = 7
}

@export var 材料图片: Texture2D
@export var id: int = 0
@export var 名称: String = ""
@export var 质量: 质量类型

@export var 描述: String = ""
@export var 最大堆叠数量: int = 9999
