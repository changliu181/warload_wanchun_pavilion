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
# 侧边栏宽度：选中武将详情和「比分板」并排一行，所以比早先的 320 宽（见 Game.INFO_COL_GAP）
SIDEBAR = 460
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

# 分数：总分 = 将领分 + 控制地域分（侧边栏常驻一块比分板实时显示，见 Game.scoreboard）
# 将领分：本方每名**存活**武将各算 (SCORE_GENERAL_BASE + 体力) × 武力，逐名求和
# 控制地域分：每块可通行地域归**行动距离最近**的一方（两边一样近算争夺中，谁也不算），
#            一格的分数 = 地形分 + 格上物品（粮草）分。障碍不算地盘，不参与归属判定。
SCORE_GENERAL_BASE = 100
SCORE_TERRAIN = {OBSTACLE: 0, PLAIN: 200, CITY: 3000}
SCORE_GRAIN = 150        # 每石粮草值多少分（粮草堆在格子上，所以是"地域上的物品"）

MAX_STAT = 22           # generals.txt 里武力/智力的上限（下限 1）

# 粮草：每 GRAIN_EVERY_TURNS 个回合，各城池入库一次（见 Game.produce_grain），
# 具体落在 4 / 9 / 14 / 19 … 这些回合的**开头**（回合数 % 5 == 4），其余回合不产粮。
# 一局 100 回合下来共入库 20 批，不算堆积如山；开局先攒三回合兵，第 4 回合才见第一批粮。
# 粮草**没有归属**——谁站到那一格都能取用。武将只是脚夫：搬的时候从出发格取、
# 到落点格当场卸下，身上不存粮（见 Game.walk），所以粮草永远只存在于格子上。
GRAIN_EVERY_TURNS = 5    # 每几个回合入库一次
GRAIN_TURN_FIRST = 4     # 第一次入库在第几回合（之后每隔 GRAIN_EVERY_TURNS 回合再来一次）
GRAIN_PER_CITY = 1       # 每个入库回合，每座城池产几石
GRAIN_HEAL = 10          # 吃 1 石回多少体力
GRAIN_EAT_MAX = 3        # 一口最多吃几石（吃 k 石要花 k 点移动力，所以这也是花费上限）
GRAIN_PER_STONE = "石"    # 单位，只用于显示

# 守城加成：防守方脚下是城池时，开打前体力 ×CITY_DEFENSE_MULT（四舍五入），
# 打完 ÷CITY_DEFENSE_MULT 还原（同样四舍五入）。两次取整在 0-120 内可精确还原。
CITY_DEFENSE_MULT = 1.2

# 电脑的粮草性子：走位 / 打仗时一次最多搬几石（搬 = 从出发格挪到落点格，见 Game.walk）。
# 武将身上不存粮，所以这个数只管"顺手挪一趟"的量，不必很大。
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

# 电脑的性子（怎么算的见 ai.py）：它把一切都换算成**分数**——就是侧边栏比分板上那一套
# （将领分 = (100+体力)×武力；地盘分 = 每格地形分 + 格上粮草）。下面这些是各分项的权重，
# 改这几个数就能调它的攻击性和谨慎程度。
AI_KILL_WORTH = 1.4     # 打死一名敌将，按他身价的几倍算（死人不会再回来赚分、守土，所以比账面贵）
AI_DEATH_WORTH = 1.6    # 自己可能被打死的风险折算：按身价的这个比例扣分（阵亡是断崖，不是掉点体力）
AI_THREAT_WORTH = 0.9   # 站在对方刀口下、且退无可退时的追加扣分（按身价折算）
AI_SIEGE_WORTH = 0.35   # 堵断敌人退路的"铺垫"值多少分（退路一断，下次开打就是歼灭）
AI_CITY_PULL = 0.5      # 落脚点本身的分（地形分 + 粮草分）按几成计入走位分
AI_GRAIN_PULL = 0.5     # 走到有粮的格子上，那堆粮按几成计入走位分
AI_IDLE_PENALTY = 6     # 走位时"离最近的敌人还差几格"，每格扣几分（推着全军往前压）
AI_TAKE_EDGE = 5        # 走位门槛：新落脚点要比原地不动好这么多分才值得挪（免得原地打转）
AI_EAT_BELOW = 0.8      # 体力掉到上限这个比例以下，路过粮堆就顺手搬一点
AI_DEBT_WORTH = 4       # 撤退欠下的一点行动力值多少分（下回合动弹不得的代价）
# 走位候选里精算前几名（精算要临时改局面按计分板算，只用在头几名上，省时间）
AI_LOOKAHEAD = 8

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
DEPLOY_COUNT = {P1: 7, P2: 10}
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
