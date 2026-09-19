# -*- coding: utf-8 -*-
"""全局常量与配色。

从 warlords.py 拆出：屏幕尺寸、地形枚举、规则数值、玩家与阵营、配置文件名、配色。
纯数据，不 import pygame——config.py / ai.py 因此可以脱离图形环境单独测试。
"""
from collections import namedtuple
from pathlib import Path

GRID = 10           # 10x10 格子
CELL = 64           # 每格像素
MARGIN = 20
SIDEBAR = 320
BOARD = GRID * CELL
WIN_W = BOARD + MARGIN * 3 + SIDEBAR
WIN_H = BOARD + MARGIN * 2
FPS = 60

# 地形枚举（未来加第 4 种：追加常量 + 补 TERRAIN_NAME/REGEN/配色）
OBSTACLE, PLAIN, CITY = 0, 1, 2
TERRAIN_NAME = {OBSTACLE: "障碍", PLAIN: "通路", CITY: "城池"}

TURN_LIMIT = 100         # 总回合数上限（双方各行动一次算 2 回合）
MAX_STAMINA = 100
MOVE_POINTS = 3         # 每回合移动力：最多走 3 格，每次一格（与体力无关）
CELL_CAPACITY = 2       # 同一格最多站几名同阵营武将（敌我永远不能同格）
RETREAT_MAX = MOVE_POINTS   # 一次撤退最多退几格；同一回合累计撤退格数封顶 MOVE_POINTS
REGEN = {OBSTACLE: 0, PLAIN: 2, CITY: 3}

MAX_STAT = 22           # generals.txt 里武力/智力的上限（下限 1）

# 粮草：城池每方回合结束产 1 石，堆在城池那一格上。粮草**没有归属**——
# 谁站到那一格都能取用。武将只是脚夫：搬的时候从出发格取、到落点格当场卸下，
# 身上不存粮（见 Game.walk），所以粮草永远只存在于格子上。
GRAIN_PER_CITY = 1       # 每座城池、每方回合结束时产出几石
GRAIN_HEAL = 10          # 吃 1 石回多少体力
GRAIN_EAT_MAX = 3        # 一口最多吃几石（吃 k 石要花 k 点移动力，所以这也是花费上限）
GRAIN_PER_STONE = "石"    # 单位，只用于显示

# 守城加成：防守方脚下是城池时，开打前体力 ×CITY_DEFENSE_MULT（四舍五入），
# 打完 ÷CITY_DEFENSE_MULT 还原（同样四舍五入）。两次取整在 0-120 内可精确还原。
CITY_DEFENSE_MULT = 1.2

# 电脑的粮草性子
AI_EAT_BELOW = 0.7       # 体力掉到上限的这个比例以下就考虑吃粮
AI_GRAIN_SCORE = 8       # 走位时落脚点有粮草的加分（带伤时更愿意往粮上靠）
# 电脑路过粮堆时一次最多搬几石（搬 = 从出发格挪到落点格，见 Game.walk）。
# 只在自己带伤、或要进城时才搬，所以这个数不必很大。
AI_GRAIN_CARRY = 6

# 交战时每回合掉的体力：只看**对方**武力，取闭区间 [1, LOSS_MAX_PER_MIGHT * 对方武力]
# 里的一个随机整数。武力上限 22 -> 单回合最多掉 44 点，所以体力 100 的武将大约 3-6 回合
# 就会见底；又因为双方每回合至少掉 1 点，单挑最迟 100 回合内必定分出结果，不会无限拖下去。
LOSS_MAX_PER_MIGHT = 2

P1, P2 = 0, 1
PLAYER_NAME = {P1: "玩家一（红·蜀）", P2: "玩家二（蓝·魏）"}
PLAYER_COLOR = {P1: (206, 74, 62), P2: (72, 124, 214)}
PLAYER_COLOR_DARK = {P1: (128, 42, 36), P2: (40, 74, 136)}

# 一方由谁操控（1P 模式下一人一机，2P 模式下都是人）
HUMAN, AI = "human", "ai"
FACTION_SHORT = {P1: "蜀", P2: "魏"}
AI_STEP_FRAMES = 24     # 电脑每步之间的停顿（帧，60fps 约 0.4 秒，让人看清它干了什么）
# 电脑的性子（见下面"电脑对手"一节）：
AI_ATTACK_EDGE = 1.0    # 对拼下来比对方后倒才动手（1.0 = 稳赢；调小就更爱冒险）
AI_RETREAT_EDGE = 1.0   # 预计能比对方后倒才继续缠斗，否则撤退
AI_CITY_SCORE = 5       # 走位时城池的加分（占城得分，驻守回血也快）
AI_THREAT_SCORE = 6     # 站到打得过的敌人旁边：下一步能冲锋
AI_DANGER_SCORE = -9    # 站到打不过的敌人旁边：白挨打

# 固定地图配置（不做随机生成）：每格写「地形:地名」，地形和地名同在一个文件里
MAP_FILE = Path(__file__).with_name("map.txt")
CITY_COUNT = 10                   # map.txt 里应正好有 10 座城池
NAME_SEP = ":"                    # 地形与地名的分隔符：.:樊城 / C:襄阳
OBSTACLE_CHAR = "#"               # 障碍格只写这一个字符，没有地名
CITY_CHAR = "C"                   # 城池格写成 C:城名
MAP_LEGEND = {                    # 配置字符（冒号前的那个字符）-> 地形
    ".": PLAIN,
    OBSTACLE_CHAR: OBSTACLE,
    CITY_CHAR: CITY,
}
# 出生点不写进地图：开局时玩家二（魏）占北半场（前 5 行）、玩家一（蜀）占南半场（后 5 行），
# 各自的武将再从本半场的通路/城池格里随机抽（障碍格不能站人）
SPAWN_ROWS = {P2: range(0, GRID // 2), P1: range(GRID // 2, GRID)}

# 武将配置（写在 generals.txt 里；武力/智力是固定值，不随机）
ROSTER_FILE = Path(__file__).with_name("generals.txt")
ROSTER_SIZE = 20                  # generals.txt 里每方应有 20 名武将
# 开局每方从本方 20 名里随机抽几名上阵：双方各配各的，不要求一样多。
# 上限是 ROSTER_SIZE；改大要考虑两件事——本方半场得放得下（validate_map 会拦），
# 以及侧边栏的武将总览够不够显示（见 Game.ROSTER_MAX_ROWS，超过就靠滚轮翻）。
DEPLOY_COUNT = {P1: 9, P2: 12}
FACTION_PLAYER = {"蜀": P1, "魏": P2}   # 配置里的阵营 -> 玩家

# 配置里的一名武将：姓名 + 固定武力/智力（体力是每局开始时满值）
GeneralSpec = namedtuple("GeneralSpec", "name might intellect")

# 配色
C_BG = (22, 24, 30)
C_PANEL = (32, 35, 44)
C_PLAIN = (58, 76, 58)
C_PLAIN_ALT = (52, 69, 52)
C_OBSTACLE = (44, 41, 39)
C_OBSTACLE_LINE = (72, 66, 62)
C_CITY = (128, 106, 72)
C_CITY_ALT = (114, 94, 64)
C_GRID = (30, 33, 30)
C_PLACE = (168, 182, 164)        # 地图上通路的地名
C_PLACE_CITY = (214, 190, 140)   # 地图上城池的地名
C_TEXT = (228, 231, 238)
C_TEXT_DIM = (150, 156, 170)
C_SELECT = (255, 236, 150)
C_ATTACK = (255, 96, 82)
C_BTN = (52, 57, 70)
C_BTN_HOVER = (74, 82, 100)
C_GOLD = (198, 168, 96)          # 交战界面：主要按钮 / 结算文字
C_WARN = (206, 106, 92)          # 交战界面：撤退按钮 / 阵亡
C_GRAIN = (226, 198, 122)        # 粮草：徽标文字 / 边框
C_GRAIN_BG = (62, 50, 24)        # 粮草：徽标底色（压在城墙等花哨地形上也看得清）
C_GRAIN_DIM = (150, 128, 78)     # 粮草：不可取用 / 次要说明
