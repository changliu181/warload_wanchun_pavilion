# -*- coding: utf-8 -*-
"""
三国战棋 —— 10x10 格子地图上的双人回合制对战小游戏（Pygame）

规则概要
--------
* 地图 10x10，每格一种地形：障碍(不可通行) / 通路 / 城池(可通行，驻守回血更多)
  地形用整数枚举定义，以后想加第 4 种（如"树林"）只需在 TERRAIN_* 后面追加并把
  TERRAIN_NAME / REGEN 里补一条即可。
* 地图不做随机生成，固定写在与本文件同目录的 map.txt 里：10 行 x 10 列、正好 10 座城池。
  每一格写成「地形:地名」（如 .:樊城 / C:襄阳），障碍格只写 #——地形和地名在同一个文件里，
  不再分两个文件，也就不存在"两份配置对不上"这回事；出生点不写进地图，
  开局时每方上阵的武将随机落在自己半场的通路或城池上
  （玩家二（魏）在北、玩家一（蜀）在南，两半场分界由 warlords.py 的 SPAWN_ROWS 决定）。
  地图上每格底部会写出地名，鼠标悬停还会弹出「地名（地形）」，
  选中武将和交战界面也都会写明所在地。改完地图保存后，在游戏里按 R 即可按新地图重开。
* 武将写在同目录的 generals.txt 里，魏蜀各 10 名（武力/智力都是固定值）：每局开局时
  每方从本方 10 名里随机抽 5 名上阵，抽中的武将再随机落到本方半场。改完按 R 即可重开。
* 每名武将的属性（都在 generals.txt 里配置）：
    - 武力 might     ：固定值，1-MAX_STAT，决定交战每回合掉多少体力（掉血只看对方武力）
    - 智力 intellect ：固定值，1-MAX_STAT，目前只作展示，不参与计算
    - 体力 stamina   ：可变值，上限 100。只有交战会消耗体力；
                       每回合开始时按所在地形恢复（通路 +8 / 城池 +16）
* 移动：每名武将有 MOVE_POINTS 点移动力，回合开始时重置为 3，每挪到相邻一格花 1 点，
        所以一回合最多走 3 格。移动力与体力完全脱钩：移动不消耗体力，
        体力见底也能照走 3 格。
* 回合制：双方轮流行动；只要移动力还没花完，这名武将就能继续行动（继续走或继续交战），
        移动力花完了本回合才动不了。
* 交战：把己方武将的移动目标点成"相邻的敌方武将格子"（踏进去）即触发交战，消耗 1 点移动力。
        必须从相邻格踏入，不能隔着格子冲锋。
        交战时切到**单独的一屏**（Battle），打一场至少 1 回合、可主动撤退的单挑：
          - 每回合双方同时掉体力，掉多少只看对方武力，取 [1, 2*对方武力] 里的随机整数；
          - 每回合结束时双方都能选择撤退，由攻方先选，撤退的一方算败方；
          - 体力掉到 0 或以下即阵亡，同样算败方，也可能双方同归于尽。
        打完时双方剩多少体力，就是这场交战的伤害结算结果（不再有额外的伤害公式）；
        战果落回地图：败方让出这一格（攻方败则原地不动），阵亡的从棋盘上移除。
* 胜负：一方武将全灭即败；回合数达到上限时按 存活武将*100 + 总体力 + 占据城池*50 比总分。

操作
----
* 鼠标左键：点高亮格移动（走到那儿，己方已经站了一人也照样能走过去）/
  点自己的武将换选（同一格有两人就轮着选，轮完再点一下取消选中）/
  点相邻的敌人格子发动进攻 / 点侧边栏按钮
* 空格 或 回车：结束回合
* R：重新开局（重新读取 map.txt / generals.txt，重新抽将）      ESC：退出
* 交战界面（单独一屏，键盘鼠标都归它管；战斗中 ESC / R 故意不生效）：
    鼠标点按钮交手 / 继续缠斗 / 撤退 / 返回战场；
    空格、回车 = 第一个按钮（不会误触"撤退"）；滚轮、↑↓、PageUp/PageDown 翻看战斗过程。
"""

import random
import sys
from collections import deque, namedtuple
from pathlib import Path

import pygame

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
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

TURN_LIMIT = 40         # 总回合数上限（双方各行动一次算 2 回合）
MAX_STAMINA = 100
MOVE_POINTS = 3         # 每回合移动力：最多走 3 格，每次一格（与体力无关）
CELL_CAPACITY = 2       # 同一格最多站几名同阵营武将（敌我永远不能同格）
RETREAT_MAX = MOVE_POINTS   # 一次撤退最多退几格；同一回合累计撤退格数封顶 MOVE_POINTS
REGEN = {OBSTACLE: 0, PLAIN: 8, CITY: 16}

MAX_STAT = 22           # generals.txt 里武力/智力的上限（下限 1）

# 交战时每回合掉的体力：只看**对方**武力，取闭区间 [1, LOSS_MAX_PER_MIGHT * 对方武力]
# 里的一个随机整数。武力上限 22 -> 单回合最多掉 44 点，所以体力 100 的武将大约 3-6 回合
# 就会见底；又因为双方每回合至少掉 1 点，单挑最迟 100 回合内必定分出结果，不会无限拖下去。
LOSS_MAX_PER_MIGHT = 2

P1, P2 = 0, 1
PLAYER_NAME = {P1: "玩家一（红·蜀）", P2: "玩家二（蓝·魏）"}
PLAYER_COLOR = {P1: (206, 74, 62), P2: (72, 124, 214)}
PLAYER_COLOR_DARK = {P1: (128, 42, 36), P2: (40, 74, 136)}

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
ROSTER_SIZE = 10                  # generals.txt 里每方应有 10 名武将
DEPLOY_COUNT = 5                  # 开局每方从本方 10 名里随机抽几名上阵
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

_font_cache = {}


def get_font(size, bold=False):
    """挑一个能显示中文的字体（macOS / Windows / Linux 常见字体依次尝试）。"""
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    for name in ("PingFang SC", "Hiragino Sans GB", "Heiti SC", "STHeiti",
                 "Songti SC", "Arial Unicode MS", "Microsoft YaHei", "SimHei",
                 "Noto Sans CJK SC", "WenQuanYi Micro Hei"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            font = pygame.font.Font(path, size)
            break
    else:
        font = pygame.font.SysFont(None, size)
    _font_cache[key] = font
    return font


def fit_font(text, max_width, start=14, min_size=8, bold=True):
    """挑一个能把 text 塞进 max_width 的字号：从 start 往下试，都不行就用 min_size。"""
    for size in range(start, min_size - 1, -1):
        font = get_font(size, bold=bold)
        if font.size(text)[0] <= max_width:
            return font
    return get_font(min_size, bold=bold)


# --------------------------------------------------------------------------
# 配置文件（map.txt / generals.txt）
# --------------------------------------------------------------------------
class ConfigError(Exception):
    """配置文件有问题。"""


class MapConfigError(ConfigError):
    """map.txt 有问题（行数 / 每行格数 / 格内容 / 城池数 / 重名 / 连通性 / 半场放不下武将）。"""


class RosterConfigError(ConfigError):
    """generals.txt 有问题（字段数 / 阵营 / 数值范围 / 人数 / 重名）。"""


def neighbors(r, c):
    """四邻格（不越界）。"""
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < GRID and 0 <= nc < GRID:
            yield nr, nc


def read_config_lines(path):
    """读取配置文件：去掉空行和 // 注释行（行内空格制表符保留，由各自的解析器处理）。"""
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"读不到配置文件 {path}：{exc}") from exc
    return [(no, text) for no, text in enumerate(raw, 1)
            if text.strip() and not text.lstrip().startswith("//")]


def parse_map(path):
    """读取地图配置 -> (grid, places)；格式不对抛 MapConfigError。

    一格写一项：可通行格写「地形:地名」（如 .:樊城 / C:襄阳），障碍格只写 #。
    地形和地名是同一次解析出来的，所以两者不可能对不上。
    """
    # 每格是一项、项间用空白分隔，所以直接按空白切
    lines = [(no, text.split()) for no, text in read_config_lines(path)]
    if len(lines) != GRID:
        raise MapConfigError(f"地图应有 {GRID} 行，实际 {len(lines)} 行。")

    grid = [[PLAIN] * GRID for _ in range(GRID)]
    places = {}
    seen = {}
    cities = 0
    for r, (no, tokens) in enumerate(lines):
        if len(tokens) != GRID:
            raise MapConfigError(
                f"第 {no} 行应有 {GRID} 格，实际 {len(tokens)} 格：{' '.join(tokens)}")
        for c, token in enumerate(tokens):
            head, sep, name = token.partition(NAME_SEP)
            if head not in MAP_LEGEND:
                raise MapConfigError(
                    f"第 {no} 行第 {c + 1} 格写成了 {token!r}，地形字符应是 "
                    f"{' '.join(MAP_LEGEND)} 之一，格式为 地形{NAME_SEP}地名"
                    f"（障碍格只写 {OBSTACLE_CHAR}）。")
            if head == OBSTACLE_CHAR:
                if sep:
                    raise MapConfigError(
                        f"第 {no} 行第 {c + 1} 格是障碍，不能起名"
                        f"（请只写 {OBSTACLE_CHAR}）：{token}")
                grid[r][c] = OBSTACLE
                continue
            if not name or OBSTACLE_CHAR in name:
                raise MapConfigError(
                    f"第 {no} 行第 {c + 1} 格写成了 {token!r}，"
                    f"可通行格必须写成 地形{NAME_SEP}地名（如 .{NAME_SEP}樊城 / C{NAME_SEP}襄阳），"
                    f"且地名不能为空、不能用 {OBSTACLE_CHAR}。")
            if name in seen:
                raise MapConfigError(
                    f"地名 {name!r} 在地图里出现了两次："
                    f"({seen[name][0]},{seen[name][1]}) 和 ({r},{c})。")
            seen[name] = (r, c)
            grid[r][c] = MAP_LEGEND[head]
            places[(r, c)] = name
            if head == CITY_CHAR:
                cities += 1

    if cities != CITY_COUNT:
        raise MapConfigError(f"地图应有 {CITY_COUNT} 座城池，实际 {cities} 座。")
    validate_map(grid)
    return grid, places


def walkable_in(grid, rows):
    """rows 这些行里的可通行格（通路或城池，障碍不能站人）。"""
    return [(r, c) for r in rows for c in range(GRID) if grid[r][c] != OBSTACLE]


def validate_map(grid):
    """地形本身要能用：所有可通行格连成一片，且每个半场放得下要上阵的武将。"""
    walkable = walkable_in(grid, range(GRID))
    if not walkable:
        raise MapConfigError("地图上一格可通行的地形都没有。")

    seen = {walkable[0]}
    q = deque([walkable[0]])
    while q:
        r, c = q.popleft()
        for cell in neighbors(r, c):
            if cell in walkable and cell not in seen:
                seen.add(cell)
                q.append(cell)
    islands = sorted(set(walkable) - seen)
    if islands:
        raise MapConfigError(f"地图有被墙隔开的孤岛格：{islands}。")

    for player in (P1, P2):
        cells = walkable_in(grid, SPAWN_ROWS[player])
        if len(cells) < DEPLOY_COUNT:
            half = "上" if player == P1 else "下"
            raise MapConfigError(
                f"{half}半场只有 {len(cells)} 格可通行，"
                f"放不下 {PLAYER_NAME[player]} 的 {DEPLOY_COUNT} 名武将。")


def pick_spawns(grid, rng):
    """开局时按地形随机分出生点（map.txt 里没有出生点）。

    玩家一从上半场的通路/城池里抽 DEPLOY_COUNT 格、玩家二从下半场抽同样多格，
    同一方互不重复；每次开局（含按 R 重开）都重新抽，所以同一张地图每局站位都不一样。
    """
    return {player: rng.sample(walkable_in(grid, SPAWN_ROWS[player]), DEPLOY_COUNT)
            for player in (P1, P2)}


def parse_roster(path):
    """读取武将配置 -> {玩家: [GeneralSpec, ...]}；格式不对抛 RosterConfigError。

    每行 4 项：阵营 姓名 武力 智力（例：蜀 关羽 21 14）。只解析，不抽将——
    哪 5 名上阵由 Game.create_generals 在开局时随机抽。
    """
    roster = {P1: [], P2: []}
    seen_names = {P1: set(), P2: set()}
    for no, text in read_config_lines(path):
        parts = text.split()
        if len(parts) != 4:
            raise RosterConfigError(
                f"武将配置第 {no} 行应有 4 项（阵营 姓名 武力 智力），"
                f"实际 {len(parts)} 项：{text.strip()}")
        faction, name, *numbers = parts
        if faction not in FACTION_PLAYER:
            raise RosterConfigError(
                f"武将配置第 {no} 行的阵营是 {faction!r}"
                f"（可用：{' '.join(FACTION_PLAYER)}）。")
        player = FACTION_PLAYER[faction]
        stats = []
        for label, value in zip(("武力", "智力"), numbers):
            if not value.isdigit() or not 1 <= int(value) <= MAX_STAT:
                raise RosterConfigError(
                    f"武将配置第 {no} 行 {name} 的{label}应是 1-{MAX_STAT} 的整数，实际 {value!r}。")
            stats.append(int(value))
        if name in seen_names[player]:
            raise RosterConfigError(
                f"武将配置第 {no} 行 {name} 在{PLAYER_NAME[player]}里重复了。")
        seen_names[player].add(name)
        roster[player].append(GeneralSpec(name, *stats))

    for player in (P1, P2):
        got = len(roster[player])
        if got != ROSTER_SIZE:
            raise RosterConfigError(
                f"{PLAYER_NAME[player]}应有 {ROSTER_SIZE} 名武将，实际 {got} 名。")
    if not 1 <= DEPLOY_COUNT <= ROSTER_SIZE:
        raise RosterConfigError(
            f"DEPLOY_COUNT 应在 1-{ROSTER_SIZE} 之间，实际 {DEPLOY_COUNT}。")
    return roster


# --------------------------------------------------------------------------
# 武将
# --------------------------------------------------------------------------
class General:
    def __init__(self, name, might, intellect, owner, row, col, stamina=None):
        self.name = name
        self.might = might                # 武力（固定）
        self.intellect = intellect        # 智力（固定）
        self.max_stamina = MAX_STAMINA
        self.stamina = MAX_STAMINA if stamina is None else stamina
        self.owner = owner
        self.row = row
        self.col = col
        self.alive = True
        self.move_points = MOVE_POINTS    # 本回合剩余移动力，每走相邻一格 -1（交战也 -1）
        self.move_debt = 0                # 本回合累计撤退了几格 = 下回合要还的行动力

    @property
    def pos(self):
        return (self.row, self.col)

    @property
    def exhausted(self):
        """本回合移动力已用尽，不能再走也不能交战。"""
        return self.move_points <= 0

    def reset_turn(self):
        """回合开始重置移动力：先扣掉上回合撤退透支的部分，不够扣就是 0。"""
        self.move_points = max(0, MOVE_POINTS - self.move_debt)
        self.move_debt = 0

    @property
    def retreat_room(self):
        """这一回合还允许再撤几格：累计撤退格数封顶 MOVE_POINTS。

        退满之后就没得退了——不是"透支封顶"，而是那种撤退根本不允许，
        所以撤退选项里压根不会出现超过剩余额度的落脚点。
        """
        return max(0, MOVE_POINTS - self.move_debt)

    def add_move_debt(self, steps):
        """记一笔撤退透支（本回合累计撤退格数），下回合要还。

        调用方必须先用 retreat_room 确认 steps 不超额度——这是一条规则，
        不是可以夹一下就算了的事。
        """
        self.move_debt += steps

    def add_stamina(self, amount):
        self.stamina = max(0, min(self.max_stamina, self.stamina + amount))


# --------------------------------------------------------------------------
# 游戏主体
# --------------------------------------------------------------------------
class Game:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.new_game()

    # ---------------- 开局 ----------------
    def new_game(self):
        # 配置都先读好、校好，再动对局状态；配置有问题时当前对局原样保留
        grid, places = self.load_map()
        roster = self.load_roster()
        spawns = pick_spawns(grid, self.rng)   # 出生点不在地图里，开局随机分
        self.grid, self.roster, self.places, self.spawns = grid, roster, places, spawns
        self.generals = []
        self.current = P1
        self.turn = 1
        self.selected = None
        self.reachable = {}
        self.attackable = set()
        self.log = []
        self.over = False                 # 对局是否已结束（平局也算结束，那时 winner 是 None）
        self.winner = None                # 胜方；None 有可能是"还没结束"，也可能是"平局"
        self.banner = None                # (文本, 剩余帧数)；帧数是 None 表示常驻不消失
        self.battle = None                # 正在进行的交战（Battle），非 None 时是交战界面
        self.push_log("新的一局开始，玩家一先行。")
        self.create_generals()
        self.start_turn(regen=False)

    def load_map(self, path=None):
        """读地图配置 -> (grid, places)：地形和地名都来自同一个文件。

        校验不过抛 MapConfigError，不碰当前对局。
        """
        return parse_map(Path(path) if path else MAP_FILE)

    def load_roster(self, path=None):
        """读武将配置 -> {玩家: [GeneralSpec]}（校验不过抛 RosterConfigError）。"""
        return parse_roster(Path(path) if path else ROSTER_FILE)

    def create_generals(self):
        """每方从本方 10 名里随机抽 DEPLOY_COUNT 名上阵，落到分好的出生点上。

        抽将和出生点都用 self.rng，所以按 R 重开会重新抽将、重新站位。
        """
        for player in (P1, P2):
            drafted = self.rng.sample(self.roster[player], DEPLOY_COUNT)
            for spec, (r, c) in zip(drafted, self.spawns[player]):
                self.generals.append(General(spec.name, spec.might, spec.intellect,
                                             player, r, c))
            self.push_log(f"{PLAYER_NAME[player]}上阵："
                          + "、".join(spec.name for spec in drafted) + "。")

    # ---------------- 基础查询 ----------------
    def generals_at(self, r, c):
        return [g for g in self.generals if g.alive and g.pos == (r, c)]

    def describe(self, r, c):
        """格子的称呼：地名（地形），如「襄阳（城池）」；障碍格没地名，只报地形。"""
        terrain = self.grid[r][c]
        if terrain == OBSTACLE:
            return TERRAIN_NAME[terrain]
        return f"{self.places[(r, c)]}（{TERRAIN_NAME[terrain]}）"

    def can_stop(self, gen, r, c):
        """gen 能不能停在 (r,c)：通路/城池、没有敌方、且己方在那格凑不满 CELL_CAPACITY。

        敌方格永远不能停——走进去等于交战，由 compute_attackable 单独给出。
        """
        if not self.in_bounds(r, c) or self.grid[r][c] == OBSTACLE:
            return False
        others = [g for g in self.generals_at(r, c) if g is not gen]
        if any(g.owner != gen.owner for g in others):
            return False
        return len(others) < CELL_CAPACITY

    def can_transit(self, gen, r, c):
        """gen 能不能路过 (r,c)：通路/城池且没有敌方。

        己方格子就算已经站满 CELL_CAPACITY 也能穿过去（只要终态不超员），
        自家的两个人不会把一条要道彻底堵死。
        """
        if not self.in_bounds(r, c) or self.grid[r][c] == OBSTACLE:
            return False
        return not any(g.owner != gen.owner for g in self.generals_at(r, c))

    def in_bounds(self, r, c):
        return 0 <= r < GRID and 0 <= c < GRID

    def garrisons(self):
        """{格子: [武将]}，只含活着的。同一格站两名时要分别画出来。"""
        out = {}
        for gen in self.generals:
            if gen.alive:
                out.setdefault(gen.pos, []).append(gen)
        return out

    def compute_reachable(self, gen):
        """BFS 算出该武将本回合能走到的落脚点 -> {pos: 需要花掉的移动力}

        移动力只决定能走多远，与体力无关；所以这里也不看体力。
        只收录能"停"的格子：敌方格子不在这里（走进去等于交战，由 compute_attackable
        单独给出），己方已经站满两名的那格只能路过、不能停。
        """
        if gen.exhausted:
            return {}
        budget = gen.move_points
        result = {}
        seen = {gen.pos}
        q = deque([(gen.row, gen.col, 0)])
        while q:
            r, c, d = q.popleft()
            if d >= budget:                   # 再走一格就超出移动力了
                continue
            for nr, nc in neighbors(r, c):
                if (nr, nc) in seen or not self.can_transit(gen, nr, nc):
                    continue
                seen.add((nr, nc))
                if self.can_stop(gen, nr, nc):     # 站不下就只当路过，不算落脚点
                    result[(nr, nc)] = d + 1
                q.append((nr, nc, d + 1))
        return result

    def compute_attackable(self, gen):
        """能踏进去交战的格子：相邻的敌方武将格，每个消耗 1 点移动力。"""
        if gen.exhausted:
            return set()
        return {(nr, nc)
                for nr, nc in neighbors(gen.row, gen.col)
                if any(other.owner != gen.owner for other in self.generals_at(nr, nc))}

    # ---------------- 玩家操作 ----------------
    def select(self, gen):
        self.selected = gen
        self.reachable = self.compute_reachable(gen) if gen else {}
        self.attackable = self.compute_attackable(gen) if gen else set()

    def clear_selection(self):
        self.selected = None
        self.reachable = {}
        self.attackable = set()

    def handle_board_click(self, row, col):
        # 先看"是不是走到这儿"：已经选中了武将、点的又是他能走到的落脚点。
        # 落脚点只可能是空格或己方格（can_stop 挡掉了敌方格和自己那一格），
        # 所以这条不会跟下面的"选中 / 攻击"抢——点了高亮格就是走过去。
        if self.selected and (row, col) in self.reachable:
            self.move(self.selected, row, col)
            return
        target = self.generals_at(row, col)
        if not target:
            self.clear_selection()
            return
        ours = [g for g in target if g.owner == self.current]
        if ours:
            self.click_own(ours)
            return
        # 点敌人：必须已选中、且相邻（相邻格才能踏进去交战）
        if self.selected and (row, col) in self.attackable:
            self.charge(self.selected, row, col)
        elif self.selected:
            self.push_log("要交战得先走到敌人旁边，从相邻格踏进去。")

    def click_own(self, ours):
        """点自己人：同格站着几名就依次轮换选中，轮完最后一个再点一下就取消选中。

        取消选中是必要的退路：点的格子若是当前武将的落脚点，会被判成"走过去"，
        想改选站在那格上的武将时，得先把选中清掉。
        """
        cycle = ours + [None]                 # 末尾的 None 表示"取消选中"
        pos = cycle.index(self.selected) if self.selected in ours else -1
        self.select(cycle[(pos + 1) % len(cycle)])

    def move(self, gen, row, col):
        """走一步（或一次走好几格）：按格数扣移动力，不扣体力。"""
        steps = self.reachable[(row, col)]
        gen.row, gen.col = row, col
        gen.move_points = max(0, gen.move_points - steps)
        self.push_log(f"{gen.name} 移动 {steps} 格至 {self.describe(row, col)}，"
                      f"剩余移动力 {gen.move_points}。")
        self.select(gen)                      # 重新计算剩余可走范围
        # 移动后若与敌人相邻，提示可以打
        if self.compute_attackable(gen):
            self.push_log(f"{gen.name} 与敌军相邻，可以踏进去交战！")

    # ---------------- 战斗 ----------------
    def charge(self, attacker, row, col):
        """向相邻的敌方武将格发动进攻：花 1 点移动力，然后切到交战界面。

        这一格里可能有 1-2 名守将，谁先迎战由守方在交战界面里定；攻方得把他们
        一个个打完才能进占这一格。真正的胜负判定与伤害结算都在 Battle 那一屏上完成
        （结算结果直接体现在双方体力上），打完由 end_battle 回到地图。
        交战不结束该武将的行动：只要还有移动力，就能接着走、接着撞下一个人。
        进攻方在交战期间不动窝——败了就是白花一点移动力。
        """
        defenders = self.generals_at(row, col)
        attacker.move_points = max(0, attacker.move_points - 1)
        self.clear_selection()                    # 交战期间棋盘不响应操作
        self.battle = Battle(self, attacker, defenders)
        self.push_log(f"⚔ {attacker.name} 进攻 {self.describe(row, col)}"
                      f"（守军：{'、'.join(g.name for g in defenders)}）。")

    def end_battle(self):
        """关掉交战界面，回到地图：让进攻方接着行动（前提是他还活着、还有移动力）。"""
        attacker = self.battle.atk
        self.battle = None
        self.check_victory()
        if self.over or not attacker.alive or attacker.exhausted:
            self.clear_selection()
        else:
            self.select(attacker)                 # 还有移动力就继续行动

    # ---------------- 回合流程 ----------------
    def end_turn(self):
        if self.over:                         # 已经分出胜负（含平局）就不再推进回合
            return
        self.clear_selection()
        self.current = 1 - self.current
        self.turn += 1
        if self.turn > TURN_LIMIT:
            self.finish_by_score()
            return
        self.start_turn()
        self.check_victory()

    def start_turn(self, regen=True):
        for gen in self.generals:
            if gen.alive and gen.owner == self.current:
                gen.reset_turn()
                if regen:
                    amount = REGEN[self.grid[gen.row][gen.col]]
                    gen.add_stamina(amount)
        if regen:
            self.push_log(f"--- 第 {self.turn} 回合，轮到 {PLAYER_NAME[self.current]} ---")

    def check_victory(self):
        alive1 = [g for g in self.generals if g.alive and g.owner == P1]
        alive2 = [g for g in self.generals if g.alive and g.owner == P2]
        if not alive1 and not alive2:
            self.set_winner(None, "两败俱伤，平局！")
        elif not alive1:
            self.set_winner(P2, f"{PLAYER_NAME[P2]} 全歼敌军，获胜！")
        elif not alive2:
            self.set_winner(P1, f"{PLAYER_NAME[P1]} 全歼敌军，获胜！")

    def finish_by_score(self):
        s1, s2 = self.score(P1), self.score(P2)
        if s1 > s2:
            self.set_winner(P1, f"回合用尽，{PLAYER_NAME[P1]} 以 {s1}:{s2} 获胜！")
        elif s2 > s1:
            self.set_winner(P2, f"回合用尽，{PLAYER_NAME[P2]} 以 {s2}:{s1} 获胜！")
        else:
            self.set_winner(None, f"回合用尽，{s1}:{s2} 平局！")

    def score(self, player):
        gens = [g for g in self.generals if g.alive and g.owner == player]
        cities = sum(1 for g in gens if self.grid[g.row][g.col] == CITY)
        return len(gens) * 100 + sum(g.stamina for g in gens) + cities * 50

    def set_winner(self, player, text):
        """定下胜负：player 为 None 就是平局。两种情况下对局都算结束。"""
        self.over = True
        self.winner = player
        self.push_log(text)
        self.banner = [text, None]            # 帧数 None = 常驻，胜负提示一直挂着

    # ---------------- 提示信息 ----------------
    def push_log(self, msg):
        self.log.append(msg)
        del self.log[:-9]

    def flash(self, msg, frames=90):
        self.banner = [msg, frames]

    def tick(self):
        if self.banner and self.banner[1] is not None:   # 剩余帧数 None = 常驻提示，不倒数
            self.banner[1] -= 1
            if self.banner[1] <= 0:
                self.banner = None

    # ---------------- 绘制 ----------------
    def cell_rect(self, row, col):
        return pygame.Rect(MARGIN + col * CELL, MARGIN + row * CELL, CELL, CELL)

    def draw(self, screen, mouse_pos, buttons):
        screen.fill(C_BG)
        self.draw_board(screen, mouse_pos)
        self.draw_sidebar(screen, mouse_pos, buttons)

    def hovered_cell(self, mouse_pos):
        """鼠标落在棋盘上就是 (行, 列)，否则 None。"""
        x, y = mouse_pos[0] - MARGIN, mouse_pos[1] - MARGIN
        if 0 <= x < BOARD and 0 <= y < BOARD:
            return y // CELL, x // CELL
        return None

    def draw_board(self, screen, mouse_pos):
        # --- 地形 ---
        for r in range(GRID):
            for c in range(GRID):
                t = self.grid[r][c]
                rect = self.cell_rect(r, c)
                checker = (r + c) % 2 == 0
                if t == OBSTACLE:
                    pygame.draw.rect(screen, C_OBSTACLE, rect)
                    self.draw_obstacle(screen, rect)
                elif t == CITY:
                    pygame.draw.rect(screen, C_CITY if checker else C_CITY_ALT, rect)
                    self.draw_city(screen, rect, r, c)
                else:
                    pygame.draw.rect(screen, C_PLAIN if checker else C_PLAIN_ALT, rect)
                    self.draw_place(screen, rect, r, c, C_PLACE)
                pygame.draw.rect(screen, C_GRID, rect, 1)

        # --- 可走范围 / 可攻击目标 ---
        overlay = pygame.Surface((BOARD, BOARD), pygame.SRCALPHA)
        for (r, c) in self.reachable:                 # 能走到的格子：选中色压淡
            x, y = c * CELL, r * CELL
            pygame.draw.rect(overlay, (*C_SELECT, 55), (x, y, CELL, CELL))
        for (r, c) in self.attackable:                # 能进攻的格子：进攻色压淡
            x, y = c * CELL, r * CELL
            pygame.draw.rect(overlay, (*C_ATTACK, 70), (x, y, CELL, CELL))
        screen.blit(overlay, (MARGIN, MARGIN))

        # --- 武将（同格站两名时左右分栏）---
        for (r, c), gens in self.garrisons().items():
            for gen, rect in zip(gens, self.general_rects(r, c, len(gens))):
                self.draw_general(screen, gen, rect)

        # --- 选中框 ---
        if self.selected:
            rect = self.cell_rect(*self.selected.pos).inflate(2, 2)
            pygame.draw.rect(screen, C_SELECT, rect, 3, border_radius=4)

        # --- 悬停格的地名（被武将压住的地名这样看）---
        cell = self.hovered_cell(mouse_pos)
        if cell:
            self.draw_tooltip(screen, cell, mouse_pos)

    def draw_obstacle(self, screen, rect):
        pygame.draw.line(screen, C_OBSTACLE_LINE, rect.topleft, rect.bottomright, 2)
        pygame.draw.line(screen, C_OBSTACLE_LINE, rect.topright, rect.bottomleft, 2)

    def draw_place(self, screen, rect, r, c, color):
        """在格子底部写地名（通路青灰、城池金色）。"""
        txt = get_font(11, bold=True).render(self.places[(r, c)], True, color)
        screen.blit(txt, txt.get_rect(center=(rect.centerx, rect.bottom - 11)))

    def draw_tooltip(self, screen, cell, mouse_pos):
        """鼠标旁边弹出这一格的「地名（地形）」。"""
        surf = get_font(13, bold=True).render(self.describe(*cell), True, (255, 246, 214))
        box = surf.get_rect().inflate(18, 10)
        box.topleft = (mouse_pos[0] + 14, mouse_pos[1] + 16)
        box.clamp_ip(pygame.Rect(0, 0, WIN_W, WIN_H))       # 贴边时自动收回来
        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((18, 18, 24, 226))
        screen.blit(bg, box.topleft)
        pygame.draw.rect(screen, (96, 104, 124), box, 1, border_radius=6)
        screen.blit(surf, surf.get_rect(center=box.center))

    def draw_city(self, screen, rect, r, c):
        # 城墙砖缝
        for i in range(1, 3):
            y = rect.top + CELL * i // 3
            pygame.draw.line(screen, (96, 78, 52), (rect.left + 3, y), (rect.right - 3, y), 1)
        # 垛口
        for i in range(3):
            x = rect.left + 6 + i * (CELL - 16) // 2
            pygame.draw.rect(screen, (150, 126, 88), (x, rect.top + 4, 8, 7))
        # 城名
        self.draw_place(screen, rect, r, c, C_PLACE_CITY)
        # 归属边框
        holder = self.generals_at(r, c)
        if holder:
            pygame.draw.rect(screen, PLAYER_COLOR[holder[0].owner], rect, 2, border_radius=3)

    def general_rects(self, r, c, count):
        """一格里的武将各占哪块地方：一个人占整格，两个人左右分栏。"""
        base = self.cell_rect(r, c)
        if count <= 1:
            return [base]
        half = base.width // 2
        return [pygame.Rect(base.left, base.top, half, base.height),
                pygame.Rect(base.left + half, base.top, base.width - half, base.height)]

    def draw_general(self, screen, gen, rect):
        """画一名武将；rect 是分给它的那一块（同格两名时只有半格宽）。"""
        slim = rect.width < CELL
        body = rect.inflate(-4 if slim else -8, -8)
        color = PLAYER_COLOR[gen.owner]
        dark = PLAYER_COLOR_DARK[gen.owner]
        # 圆角方块作为武将底盘
        pygame.draw.rect(screen, dark, body, border_radius=8)
        pygame.draw.rect(screen, color, body.inflate(-2 if slim else -4, -4), border_radius=6)

        # 姓名：字号按可用宽度收缩，三字名在半格宽里也塞得下
        name_font = fit_font(gen.name, body.width - 4, start=12 if slim else 14)
        name_txt = name_font.render(gen.name, True, (255, 255, 255))
        screen.blit(name_txt, name_txt.get_rect(
            center=(body.centerx, body.top + (12 if slim else 15))))

        # 属性行：半格宽实在放不下，索性省掉（悬停提示和侧边栏里还有）
        if not slim:
            stat_txt = get_font(11).render(f"武{gen.might} 智{gen.intellect}",
                                           True, (250, 250, 250))
            screen.blit(stat_txt, stat_txt.get_rect(center=(body.centerx, body.top + 32)))

        # 体力条
        bar = pygame.Rect(body.left + 3, body.bottom - 11, body.width - 6, 6)
        pygame.draw.rect(screen, (20, 20, 24), bar, border_radius=3)
        ratio = max(0.0, gen.stamina / gen.max_stamina)
        fill = bar.copy()
        fill.width = max(1, int(bar.width * ratio))
        hp_color = (96, 208, 112) if ratio > 0.5 else (232, 196, 72) if ratio > 0.25 else (226, 84, 72)
        pygame.draw.rect(screen, hp_color, fill, border_radius=3)
        hp_txt = get_font(10).render(str(gen.stamina), True, (245, 245, 245))
        screen.blit(hp_txt, hp_txt.get_rect(center=(body.centerx, body.bottom - 2)))

        if gen.exhausted:
            veil = pygame.Surface(body.size, pygame.SRCALPHA)
            veil.fill((10, 10, 14, 110))
            screen.blit(veil, body.topleft)
            pygame.draw.rect(screen, (120, 126, 140), body, 2, border_radius=8)

    def draw_sidebar(self, screen, mouse_pos, buttons):
        x0 = MARGIN * 2 + BOARD
        panel = pygame.Rect(x0, MARGIN, SIDEBAR, BOARD)
        pygame.draw.rect(screen, C_PANEL, panel, border_radius=10)
        btn_top = min(rect.top for _l, rect, _k in buttons)
        limit = btn_top - 10                      # 内容区不得压到按钮上

        y = panel.top + 14
        screen.blit(get_font(22, bold=True).render("三国战棋", True, C_TEXT), (panel.left + 16, y))
        y += 32

        if not self.over:
            screen.blit(get_font(13).render(f"第 {self.turn} / {TURN_LIMIT} 回合",
                                            True, C_TEXT_DIM), (panel.left + 16, y))
            y += 22
            dot = pygame.Rect(panel.left + 16, y + 4, 14, 14)
            pygame.draw.rect(screen, PLAYER_COLOR[self.current], dot, border_radius=4)
            gens = [g for g in self.generals if g.alive and g.owner == self.current]
            done = sum(1 for g in gens if g.exhausted)
            text = f"{PLAYER_NAME[self.current]}  ({done}/{len(gens)} 已走完)"
            screen.blit(get_font(14, bold=True).render(text, True, C_TEXT), (panel.left + 38, y))
            y += 30
        else:
            label = "平局，双方罢兵" if self.winner is None else f"{PLAYER_NAME[self.winner]} 获胜"
            screen.blit(get_font(15, bold=True).render(label, True, C_TEXT), (panel.left + 16, y))
            y += 30

        # 选中武将详情
        y = self.draw_selected_info(screen, panel, y)

        # 底部武将总览（固定在按钮区上方，战报用剩余空间）
        per_side = max(sum(1 for g in self.generals if g.owner == p) for p in (P1, P2))
        roster_h = 2 * (18 + per_side * 17) + 8
        roster_top = limit - roster_h
        screen.blit(get_font(13, bold=True).render("战报", True, C_TEXT_DIM), (panel.left + 16, y))
        y += 20
        log_font = get_font(12)
        max_lines = max(1, (roster_top - 8 - y) // 17)
        lines = []
        for entry in reversed(self.log):          # 从最新往回取，保证最新的一定显示
            lines.extend(wrap_text(entry, log_font, panel.width - 32))
            if len(lines) >= max_lines:
                break
        for chunk in lines[:max_lines][::-1]:     # 再翻回时间顺序
            screen.blit(log_font.render(chunk, True, (198, 203, 214)), (panel.left + 16, y))
            y += 17

        ry = roster_top
        for player in (P1, P2):
            ry = self.draw_roster(screen, panel, ry, player)

        # 按钮
        for label, rect, _key in buttons:
            hover = rect.collidepoint(mouse_pos)
            pygame.draw.rect(screen, C_BTN_HOVER if hover else C_BTN, rect, border_radius=8)
            pygame.draw.rect(screen, (86, 94, 112), rect, 1, border_radius=8)
            txt = get_font(14, bold=True).render(label, True, C_TEXT)
            screen.blit(txt, txt.get_rect(center=rect.center))

        # 顶部飘字提示
        if self.banner:
            text = self.banner[0]
            font = get_font(20, bold=True)
            surf = font.render(text, True, (255, 246, 214))
            box = surf.get_rect(center=(MARGIN + BOARD // 2, MARGIN + 30)).inflate(28, 16)
            bg = pygame.Surface(box.size, pygame.SRCALPHA)
            bg.fill((18, 18, 24, 214))
            screen.blit(bg, box.topleft)
            pygame.draw.rect(screen, (214, 180, 96), box, 2, border_radius=8)
            screen.blit(surf, surf.get_rect(center=box.center))

    def draw_selected_info(self, screen, panel, y):
        gen = self.selected
        box = pygame.Rect(panel.left + 16, y, panel.width - 32, 92)
        pygame.draw.rect(screen, (42, 46, 58), box, border_radius=8)
        if not gen or not gen.alive:
            tip = get_font(12).render("点己方武将选中，再点高亮格移动", True, C_TEXT_DIM)
            screen.blit(tip, tip.get_rect(center=box.center))
            return box.bottom + 12
        pygame.draw.rect(screen, PLAYER_COLOR[gen.owner], box, 2, border_radius=8)
        f_big = get_font(17, bold=True)
        f_sm = get_font(12)
        screen.blit(f_big.render(gen.name, True, C_TEXT), (box.left + 12, box.top + 8))
        screen.blit(f_sm.render(f"武力 {gen.might}   智力 {gen.intellect}",
                                True, C_TEXT), (box.left + 12, box.top + 34))
        screen.blit(f_sm.render(
            f"体力 {gen.stamina}/{gen.max_stamina}   移动力 {gen.move_points}/{MOVE_POINTS}",
            True, C_TEXT), (box.left + 12, box.top + 54))
        note = f"位于 {self.describe(gen.row, gen.col)}"
        if gen.exhausted:
            note += "  · 本回合已走完"
        elif self.compute_attackable(gen):
            note += "  · 旁边有敌军，可踏进去交战"
        screen.blit(f_sm.render(note, True, C_TEXT_DIM), (box.left + 12, box.top + 72))
        return box.bottom + 12

    def draw_roster(self, screen, panel, y, player):
        font = get_font(12)
        screen.blit(font.render(PLAYER_NAME[player], True, PLAYER_COLOR[player]),
                    (panel.left + 16, y))
        y += 18
        for gen in self.generals:
            if gen.owner != player:
                continue
            if not gen.alive:
                txt, color = f"{gen.name}  阵亡", (128, 128, 138)
            else:
                txt = f"{gen.name}  武{gen.might} 智{gen.intellect} 体{gen.stamina}"
                color = (206, 211, 222)
            screen.blit(font.render(txt, True, color), (panel.left + 24, y))
            y += 17
        return y + 8


# --------------------------------------------------------------------------
# 交战界面（单独的一屏）
# --------------------------------------------------------------------------
class Battle:
    """一次交战的独立界面：一格守军最多两名，攻方要把他们一个个打完。

    出战顺序
    --------
    * 攻方踏进敌方格子时，若那格有两名守将，**由守方决定谁先迎战**（PICK_DEFENDER）。
    * 攻方与第一名守将打完（守将撤退或阵亡）后，只要这一格还有守将，就自动接着打
      下一名。**第二场开打前双方都可以选择撤退**（仍是攻方先选）——因为这时攻方
      已经打了一场、守方却是生力军，给双方一个收手的机会。
    * 把守将全部打完、且攻方自己没退没死，攻方才进占这一格。

    单挑规则（胜负判定 + 伤害结算都在这屏上完成）
    ------------------------------------------
    * 每回合双方**同时**掉体力，掉多少只看**对方**武力：取闭区间
      [1, LOSS_MAX_PER_MIGHT * 对方武力] 里的一个随机整数（默认就是 2 倍对方武力）。
      武力高的武将打得疼，也扛得住——因为对方的武力决定了"打他多重"。
    * 每回合结束时双方都可以选择撤退，由**攻方先选**；撤退的一方算败方。
      两边都选继续就进下一回合，所以第一场撤退至少要等第 1 回合打完才能选。
    * 体力掉到 0 或以下即阵亡，同样算败方；双方同一回合都掉到 0 就是同归于尽。
    * 打完时双方剩多少体力，就是这场交战的伤害结算结果——不再有额外的伤害公式。

    撤退
    ----
    * **攻方撤退**：只是回到出发格（攻方在交战期间本来就没动窝），不额外扣移动力。
    * **守方撤退**：从争夺格做 BFS，挑一个落脚点撤过去，撤几格就**透支下回合几点行动力**。
      路径是 BFS 算出来的，**可以拐弯、不要求走直线**；约束是第一步不能迎着攻方来的方向，
      中途每格要过得去（通路/城池、无敌方），落脚那格还要停得下（己方不满 CELL_CAPACITY）。
      步数取 BFS 最短距离，所以每个落脚点对应一个确定的透支数。
    * **同一回合累计撤退格数封顶 MOVE_POINTS**：已经撤过的格数一扣，剩下的才是这轮的额度
      （退满满额，下回合就走不动了）。额度不够的落脚点根本不算合法撤退，不会列出来；
      额度为 0 时守方就没有撤退的权利。
    * 一个落脚点都没有时，守方**没有撤退的权利**，界面上不给"撤退"按钮，只能继续缠斗。
      可选项不止一个时由守方自己挑（RETREAT_PICK）。

    状态流转
    --------
        PICK_DEFENDER --点将--> 第一场 READY
        第一场: READY --交手--> IMPACT --掉血动画放完--> 有人下场？ --> 换人 / 收场
                                              \\--> 都还活着 --> CHOOSE_ATK
        第二场: 直接从 CHOOSE_ATK 起手（第一回合前双方都能撤）
        CHOOSE_ATK --继续--> CHOOSE_DFD --继续--> 下一回合的 READY
        CHOOSE_ATK --撤退--> OVER（攻方原地不动）
        CHOOSE_DFD --撤退--> RETREAT_PICK --选好方向步数--> 换人 / 攻方进占
        OVER --返回战场--> 回到地图
    """

    (PICK_DEFENDER, READY, IMPACT,
     CHOOSE_ATK, CHOOSE_DFD, RETREAT_PICK, OVER) = range(7)
    IMPACT_FRAMES = 42                     # 掉血动画时长（帧，60fps 约 0.7 秒）
    SHAKE = (0, -4, 3, -3, 2, -2, 1, 0)    # 掉血瞬间卡片的抖动偏移
    HIST_ROWS = 5                          # 战斗过程一屏显示几回合（多出来的可以翻）

    # 一整屏的版面（屏幕尺寸由主循环的 WIN_W x WIN_H 决定）
    CARD_W, CARD_H, CARD_Y = 420, 246, 86
    CARD_X = (40, WIN_W - 40 - CARD_W)
    BTN_W, BTN_H, BTN_Y = 220, 52, 412
    HIST_RECT = pygame.Rect(40, 476, WIN_W - 80, 166)
    PICK_COLS = 4                          # 撤退选项：4 列铺在战报那块地方
    HINT_Y, FOOT_Y = 348, 654

    def __init__(self, game, attacker, defenders):
        self.game = game
        self.rng = game.rng
        self.atk = attacker
        self.defenders = list(defenders)      # 这一格的守军，出场顺序由守方定
        self.cell = self.defenders[0].pos     # 争夺中的格子（守方原本站的地方）
        self.origin = attacker.pos            # 攻方的出发格（攻方败了原地不动）
        self.place = game.describe(*self.cell)           # 争夺中的这一格：地名（地形）
        self.origin_place = game.describe(*self.origin)   # 攻方是从哪一格打过来的
        self.fight_no = 1                     # 第几场（守军最多两名，所以最多两场）
        self.dfd = None                       # 当前迎战的守将
        self.round = 0
        self.rounds = []                      # 每回合一条战报，见 roll()
        self.scroll = 0                       # 战斗过程往上翻了几回合（0 = 贴着最新一条）
        self.timer = 0
        self.atk_retreated = False            # 攻方退过，就不再进占这一格
        self.retreat_choices = []             # RETREAT_PICK 阶段可点的 (落脚点, 步数)
        self.retreat_from = None              # 从哪个状态点进撤退选择的（"再想想"用）
        self.ending = ""
        if len(self.defenders) > 1:
            self.state = self.PICK_DEFENDER
            self.hint = f"{self.place} 有两名守将，请守方决定谁先出阵迎战。"
        else:
            self.begin_fight(self.defenders[0])
            self.hint = f"两军在 {self.place} 列阵，准备交手。"

    def begin_fight(self, defender):
        """让 defender 上场迎战：第一场从 READY 起手，第二场从"开打前可撤退"起手。"""
        self.dfd = defender
        self.round = 0
        self.scroll = 0
        self.timer = 0
        self.state = self.CHOOSE_ATK if self.fight_no > 1 else self.READY
        if self.state == self.CHOOSE_ATK:
            self.hint = (f"第 {self.fight_no} 场：{defender.name} 接着迎战。"
                         f"开打前双方都还能收手——{self.atk.name}（攻方）先决定。")

    # ---------------- 规则 ----------------
    def foe_of(self, gen):
        """gen 的对手；守方的对手就是攻方，攻方的对手是当前迎战的那名守将。"""
        return self.dfd if gen is self.atk else self.atk

    def loss_range(self, victim):
        """victim 这一回合最多掉多少体力 = LOSS_MAX_PER_MIGHT * 对方武力。"""
        return LOSS_MAX_PER_MIGHT * self.foe_of(victim).might

    @property
    def chooser(self):
        """现在该谁做决定（继续 / 撤退）；没人要做决定时是 None。"""
        if self.state == self.CHOOSE_ATK:
            return self.atk
        if self.state == self.CHOOSE_DFD:
            return self.dfd
        return None

    @property
    def pre_round(self):
        """现在是不是"第一回合开打之前"的那个选择（只有第二场才有）。"""
        return self.round == 0 and self.state in (self.CHOOSE_ATK, self.CHOOSE_DFD)

    @property
    def shown_round(self):
        """界面上该显示的回合数：准备阶段显示的是即将开打的这一回合。"""
        if self.state == self.READY or self.pre_round:
            return self.round + 1
        return max(1, self.round)

    def roll(self):
        """交手一回合：双方同时按对方武力掉体力（各取一个 [1, 2*对方武力] 的随机数）。"""
        if self.state != self.READY:
            return
        self.round += 1
        atk_loss = self.rng.randint(1, self.loss_range(self.atk))
        dfd_loss = self.rng.randint(1, self.loss_range(self.dfd))
        self.atk.add_stamina(-atk_loss)
        self.dfd.add_stamina(-dfd_loss)
        for gen in (self.atk, self.dfd):
            if gen.stamina <= 0:
                gen.alive = False             # 掉到 0 或以下当场阵亡
        # 战报里连守将一起记下来：换人之后还要能把这一场画回历史里
        self.rounds.append({"fight": self.fight_no, "no": self.round, "dfd": self.dfd,
                            "atk_loss": atk_loss, "dfd_loss": dfd_loss,
                            "atk_hp": self.atk.stamina, "dfd_hp": self.dfd.stamina})
        self.hint = (f"第 {self.round} 回合：{self.atk.name} 掉 {atk_loss} 点体力，"
                     f"{self.dfd.name} 掉 {dfd_loss} 点体力。")
        self.state, self.timer = self.IMPACT, self.IMPACT_FRAMES

    def update(self):
        """掉血动画放完后决定下一步：有人下场就换人/收场，否则交给双方做选择。"""
        if self.state != self.IMPACT:
            return
        self.timer -= 1
        if self.timer > 0:
            return
        if not self.atk.alive or not self.dfd.alive:
            self.settle_fight()
            return
        self.state = self.CHOOSE_ATK
        self.hint = (f"第 {self.round} 回合结束，{self.atk.name}（攻方）先决定："
                     f"继续缠斗，还是就此撤退？")

    def continue_fight(self):
        """选择继续：攻方选完轮到守方，两边都选继续就打下一回合（或第二场的第一回合）。"""
        if self.state == self.CHOOSE_ATK:
            self.state = self.CHOOSE_DFD
            self.hint = (f"{self.atk.name} 继续缠斗，现在轮到 {self.dfd.name}（守方）"
                         f"决定：接着打，还是撤退？")
        elif self.state == self.CHOOSE_DFD:
            self.state = self.READY
            self.hint = f"双方各自重整旗鼓，第 {self.round + 1} 回合准备交手。"

    def settle_fight(self):
        """一场打完（有人阵亡）：报战报，然后决定是换人接着打还是收场。"""
        game, atk, dfd = self.game, self.atk, self.dfd
        for gen in (atk, dfd):
            if not gen.alive:
                game.push_log(f"☠ {gen.name} 体力耗尽，阵亡！")
        if not atk.alive and not dfd.alive:
            text = f"{atk.name} 与 {dfd.name} 同归于尽，双双阵亡。"
        elif not atk.alive:
            text = f"{atk.name} 力竭阵亡，{dfd.name} 守住了阵脚。"
        else:
            text = f"{dfd.name} 力竭阵亡，{atk.name} 获胜。"
        game.push_log(f"⚔ {atk.name} vs {dfd.name} 共 {self.round} 回合：{text}")
        self.ending = text
        self.advance(text)

    def advance(self, text):
        """一名守将下场了：攻方还在就换下一名接着打，守军打光了就收场。"""
        if self.atk_retreated or not self.atk.alive:
            self.finish(text)
            return
        rest = [g for g in self.defenders if g.alive and g.pos == self.cell]
        if rest:
            self.fight_no += 1
            self.begin_fight(rest[0])
            return
        self.finish(text)

    def finish(self, text):
        """整场交战结束：定下结算文字，把战果落回地图。"""
        self.state, self.hint = self.OVER, text
        self.apply()

    def apply(self):
        """战果落回地图：守军清空且攻方没退没死，攻方才进占这一格。"""
        game, atk = self.game, self.atk
        if self.atk_retreated or not atk.alive:
            return
        if any(g.alive and g.pos == self.cell for g in self.defenders):
            return                            # 还有守将在，格子不归攻方
        atk.row, atk.col = self.cell
        game.push_log(f"{atk.name} 进占 {game.describe(*self.cell)}。")

    # ---------------- 撤退 ----------------
    def came_direction(self):
        """攻方是从哪个方向来的（从争夺格指向攻方出发格的单位向量）。"""
        dr = self.origin[0] - self.cell[0]
        dc = self.origin[1] - self.cell[1]
        return ((dr > 0) - (dr < 0), (dc > 0) - (dc < 0))

    def retreat_paths(self):
        """守方能撤到哪几格、各要几步 -> {终点: 步数}；一处都去不了就是空。

        从争夺格做 BFS：一格一格挪，**可以拐弯，不要求走直线**。约束有这么几条——
        * 第一步不能迎着攻方来的方向（那是朝刀口上撞）；
        * 中途每一格都要"过得去"（通路/城池、没有敌方）；
        * 落脚的那一格还要"停得下"（己方不满 CELL_CAPACITY）；
        * 加上本回合已经撤过的格数，累计不能超过 MOVE_POINTS——超了就不是合法的撤退，
          那些落脚点压根不会列出来。
        步数取的是 BFS 最短距离，也就等于这次撤退要透支的行动力。
        """
        cell = self.cell
        came = self.came_direction()
        limit = min(RETREAT_MAX, self.dfd.retreat_room)   # 本回合还剩多少撤退额度
        dests = {}
        if limit <= 0:
            return dests                                # 退满了，没得退
        seen = {cell}
        q = deque([(cell[0], cell[1], 0)])
        while q:
            r, c, d = q.popleft()
            if d >= limit:
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                if d == 0 and (dr, dc) == came:
                    continue
                nr, nc = r + dr, c + dc
                if (nr, nc) in seen or not self.game.can_transit(self.dfd, nr, nc):
                    continue
                seen.add((nr, nc))
                if self.game.can_stop(self.dfd, nr, nc):   # 停不下就只当路过
                    dests[(nr, nc)] = d + 1
                q.append((nr, nc, d + 1))
        return dests

    def retreat_options(self):
        """候选落脚点，按"先近后远"排好 -> [(终点, 步数)]：退得越少，透支越少。"""
        return sorted(self.retreat_paths().items(), key=lambda kv: (kv[1], kv[0]))

    def can_retreat(self):
        """当前该做决定的一方有没有撤退的权利：攻方永远有（原地退回），守方要有退路。"""
        if self.chooser is self.atk:
            return True
        return bool(self.retreat_paths())

    def request_retreat(self, gen):
        """点了"撤退"：攻方直接原地退回，守方先挑撤到哪一格。"""
        if gen is self.atk:
            self.atk_retreated = True
            text = f"{self.atk.name} 撤退，判为败方；{self.dfd.name} 守住 {self.place}。"
            self.game.push_log(f"⚔ {self.atk.name} 从 {self.place} 撤退，退回原地。")
            self.finish(text)
            return
        options = self.retreat_options()
        if not options:
            return                            # 没退路时本来就不给按钮，这里只是兜底
        if len(options) == 1:                 # 只有一条路，不用再让玩家点一次
            self.apply_retreat(*options[0])
            return
        self.retreat_choices = options
        self.retreat_from = self.state
        self.state = self.RETREAT_PICK
        self.hint = (f"{gen.name} 往哪撤？（{len(options)} 个落脚点可选，"
                     f"第一步不能迎着攻方来；本回合还剩 {gen.retreat_room} 格额度）")

    def apply_retreat(self, dest, steps):
        """守方撤退落地：挪过去，并把步数记成下回合要还的行动力。"""
        gen = self.dfd
        if steps > gen.retreat_room:            # 选项都是按额度生成的，这里只是兜底
            return
        self.retreat_choices = []               # 选完了，选项作废
        gen.row, gen.col = dest
        gen.add_move_debt(steps)
        to = self.game.describe(*dest)
        self.game.push_log(
            f"⚔ {gen.name} 从 {self.place} 撤退 {steps} 格到 {to}"
            f"（判为败方，本回合累计撤退 {gen.move_debt} 格，"
            f"下回合透支 {gen.move_debt} 点行动力）。")
        self.ending = f"{gen.name} 撤到 {to}，判为败方；{self.atk.name} 占上风。"
        self.advance(self.ending)

    # ---------------- 操作 ----------------
    def button_rect(self, index, count):
        """第 index 个按钮（一行 count 个，整体居中）。"""
        gap = 24
        total = count * self.BTN_W + (count - 1) * gap
        left = (WIN_W - total) // 2 + index * (self.BTN_W + gap)
        return pygame.Rect(left, self.BTN_Y, self.BTN_W, self.BTN_H)

    def pick_rect(self, index, count):
        """撤退选项按钮：PICK_COLS 列，铺在战报那块地方（这一屏不显示战报）。"""
        rect, gap = self.HIST_RECT, 12
        cols = self.PICK_COLS
        rows = max(1, -(-count // cols))       # 向上取整
        w = (rect.width - (cols - 1) * gap) // cols
        h = (rect.height - (rows - 1) * gap) // rows
        return pygame.Rect(rect.left + (index % cols) * (w + gap),
                           rect.top + (index // cols) * (h + gap), w, h)

    def buttons(self):
        """当前状态下可点的按钮 -> [(文字, Rect, 动作)]。"""
        if self.state == self.PICK_DEFENDER:
            count = len(self.defenders)
            return [(f"{g.name} 先出阵", self.button_rect(i, count), f"pick:{i}")
                    for i, g in enumerate(self.defenders)]
        if self.state == self.READY:
            return [("交手", self.button_rect(0, 1), "roll")]
        if self.state in (self.CHOOSE_ATK, self.CHOOSE_DFD):
            action = "atk_retreat" if self.state == self.CHOOSE_ATK else "dfd_retreat"
            options = [("继续缠斗", "hold")]
            if self.can_retreat():            # 守方没退路时，连按钮都不给
                options.append(("撤退（判负）", action))
            return [(label, self.button_rect(i, len(options)), act)
                    for i, (label, act) in enumerate(options)]
        if self.state == self.RETREAT_PICK:
            count = len(self.retreat_choices)
            picks = [(f"撤至 {self.game.places[dest]}（{n} 点）",
                      self.pick_rect(i, count), f"retreat:{i}")
                     for i, (dest, n) in enumerate(self.retreat_choices)]
            picks.append(("再想想（回去缠斗）", self.button_rect(0, 1), "back"))
            return picks
        if self.state == self.OVER:
            return [("返回战场", self.button_rect(0, 1), "close")]
        return []                             # IMPACT：掉血动画中，不接受操作

    def act(self, action):
        if action == "roll":
            self.roll()
        elif action == "hold":
            self.continue_fight()
        elif action == "atk_retreat":
            self.request_retreat(self.atk)
        elif action == "dfd_retreat":
            self.request_retreat(self.dfd)
        elif action == "back":
            self.retreat_choices = []                 # 别把这一轮的选项留到下一轮
            self.state = self.retreat_from
            self.hint = "重新决定：继续缠斗，还是撤退？"
        elif action.startswith("pick:"):
            self.pick_defender(int(action.split(":")[1]))
        elif action.startswith("retreat:"):
            self.apply_retreat(*self.retreat_choices[int(action.split(":")[1])])
        elif action == "close":
            self.game.end_battle()

    def pick_defender(self, index):
        """守方定下谁先出阵：选中的先上，另一名排在后面等着。"""
        first = self.defenders[index]
        self.defenders = [first] + [g for g in self.defenders if g is not first]
        self.game.push_log(f"{first.name} 出阵迎战 {self.atk.name}。")
        self.begin_fight(first)

    def handle_click(self, pos):
        for _label, rect, action in self.buttons():
            if rect.collidepoint(pos):
                self.act(action)
                return

    def scroll_history(self, steps):
        """往上翻 / 往下翻战斗过程（滚轮一次几行、方向键一行）。"""
        self.scroll = max(0, min(self.max_scroll, self.scroll + steps))

    @property
    def max_scroll(self):
        return max(0, len(self.rounds) - self.HIST_ROWS)

    def primary(self):
        """空格 / 回车：走第一个按钮（交手 / 继续缠斗 / 返回战场），不会误触撤退。

        点将和挑撤退方向那两屏例外：那里的按钮都是"替自己做决定"，按空格什么都不做，
        必须用鼠标点，免得手一快就替守方定了出战顺序或撤退方向。
        """
        if self.state in (self.PICK_DEFENDER, self.RETREAT_PICK):
            return
        buttons = self.buttons()
        if buttons:
            self.act(buttons[0][2])

    # ---------------- 绘制 ----------------
    def card_rect(self, gen):
        if self.state == self.PICK_DEFENDER:   # 点将那一屏：两名守将各占一张牌
            return pygame.Rect(self.CARD_X[self.defenders.index(gen) % 2],
                               self.CARD_Y, self.CARD_W, self.CARD_H)
        return pygame.Rect(self.CARD_X[0 if gen is self.atk else 1],
                           self.CARD_Y, self.CARD_W, self.CARD_H)

    def draw(self, screen, mouse_pos):
        screen.fill(C_BG)
        self.draw_header(screen)
        if self.state == self.PICK_DEFENDER:
            for i, gen in enumerate(self.defenders):
                self.draw_card(screen, gen, f"守将 {i + 1}")
        else:
            self.draw_card(screen, self.atk, "攻方")
            self.draw_card(screen, self.dfd, "守方")
            self.draw_vs(screen)
        if self.state != self.RETREAT_PICK:    # 挑撤退方向时，那块地方让给选项按钮
            self.draw_history(screen)
        self.draw_controls(screen, mouse_pos)

    def draw_header(self, screen):
        title = get_font(26, bold=True).render("交战", True, C_TEXT)
        screen.blit(title, title.get_rect(midtop=(WIN_W // 2, 16)))
        if self.dfd is None:                   # 点将阶段还没有"当前守将"
            sub = (f"{self.atk.name}（{PLAYER_NAME[self.atk.owner]}）进攻 {self.place}，"
                   f"守军 {len(self.defenders)} 人")
        else:
            sub = (f"{self.atk.name}（{PLAYER_NAME[self.atk.owner]}）进攻 "
                   f"{self.dfd.name}（{PLAYER_NAME[self.dfd.owner]}）驻守的 {self.place}")
            if len(self.defenders) > 1:
                sub += f"　·　第 {self.fight_no} 场 / 共 {len(self.defenders)} 场"
        surf = get_font(14).render(sub, True, C_TEXT_DIM)
        screen.blit(surf, surf.get_rect(midtop=(WIN_W // 2, 52)))

    def draw_vs(self, screen):
        cx = (self.CARD_X[0] + self.CARD_W + self.CARD_X[1]) // 2
        vs = get_font(30, bold=True).render("VS", True, (108, 116, 136))
        screen.blit(vs, vs.get_rect(center=(cx, self.CARD_Y + 56)))
        rnd = get_font(18, bold=True).render(f"第 {self.shown_round} 回合", True, C_TEXT)
        screen.blit(rnd, rnd.get_rect(center=(cx, self.CARD_Y + 100)))

    def card_frames(self, gen):
        """(没被抖动的卡片矩形, 掉血进度 0->1)——不在掉血动画中时进度是 None。"""
        rect = self.card_rect(gen)
        if self.state != self.IMPACT or not self.rounds:
            return rect, None
        progress = 1 - self.timer / self.IMPACT_FRAMES
        if self.timer > self.IMPACT_FRAMES - len(self.SHAKE):
            rect = rect.move(self.SHAKE[self.IMPACT_FRAMES - self.timer], 0)
        return rect, progress

    def draw_card(self, screen, gen, side_label):
        rect, progress = self.card_frames(gen)
        other = self.foe_of(gen)
        color = PLAYER_COLOR[gen.owner]
        pygame.draw.rect(screen, C_PANEL, rect, border_radius=12)

        # 顶栏：攻方/守方 + 站位
        tag = get_font(14, bold=True).render(side_label, True, color)
        screen.blit(tag, (rect.left + 16, rect.top + 12))
        where = (f"从 {self.origin_place} 进攻" if gen is self.atk else
                 f"驻守 {self.place}")
        info = get_font(12).render(where, True, C_TEXT_DIM)
        screen.blit(info, info.get_rect(midright=(rect.right - 16, rect.top + 20)))

        # 姓名 + 属性
        screen.blit(get_font(26, bold=True).render(gen.name, True, C_TEXT),
                    (rect.left + 16, rect.top + 42))
        screen.blit(get_font(14).render(
            f"武力 {gen.might}    智力 {gen.intellect}    {PLAYER_NAME[gen.owner]}",
            True, C_TEXT_DIM), (rect.left + 16, rect.top + 80))

        # 体力条 + 本回合的掉血范围
        self.draw_stamina_bar(screen, gen, pygame.Rect(rect.left + 16, rect.top + 116,
                                                       rect.width - 32, 30))
        screen.blit(get_font(13).render(
            f"每回合掉 1 ~ {self.loss_range(gen)} 点体力"
            f"（对方武力 {other.might} × {LOSS_MAX_PER_MIGHT}）", True, C_TEXT_DIM),
            (rect.left + 16, rect.top + 158))

        # 状态提示
        if not gen.alive:
            note, note_color = "阵亡", C_WARN
        elif self.chooser is gen:
            note, note_color = "该你决定（继续 / 撤退）", C_SELECT
        else:
            note, note_color = "", C_TEXT_DIM
        if self.state == self.PICK_DEFENDER:
            note, note_color = "点下方按钮决定谁先出阵", C_SELECT
        if note:
            screen.blit(get_font(16, bold=True).render(note, True, note_color),
                        (rect.left + 16, rect.top + 186))

        # 守方卡片：这一格还有谁在后面等着上场
        if gen is self.dfd and len(self.defenders) > 1:
            waiting = [g.name for g in self.defenders if g is not gen and g.alive]
            if waiting:
                screen.blit(get_font(12).render(f"阵中还有：{'、'.join(waiting)}",
                                                True, C_TEXT_DIM),
                            (rect.left + 16, rect.top + 214))

        # 掉血动画：卡片泛红 + 上浮的掉血数字
        if progress is not None:
            flash = pygame.Surface(rect.size, pygame.SRCALPHA)
            flash.fill((226, 84, 72, int(90 * max(0.0, 1 - progress * 2))))
            screen.blit(flash, rect.topleft)
            self.draw_loss_popup(screen, gen, rect, progress)

        if not gen.alive:
            veil = pygame.Surface(rect.size, pygame.SRCALPHA)
            veil.fill((10, 10, 14, 170))
            screen.blit(veil, rect.topleft)
            big = get_font(34, bold=True).render("阵亡", True, C_WARN)
            screen.blit(big, big.get_rect(center=rect.center))

        pygame.draw.rect(screen, color if gen.alive else (110, 110, 120),
                         rect, 3, border_radius=12)

    def draw_loss_popup(self, screen, gen, rect, progress):
        record = self.rounds[-1]
        loss = record["atk_loss"] if gen is self.atk else record["dfd_loss"]
        alpha = 255 if progress < 0.55 else max(0, int(255 * (1 - progress) / 0.45))
        pos = pygame.Rect(0, 0, 0, 0)
        pos.center = (rect.centerx, rect.centery - 24 - int(26 * progress))
        for dx, dy, col in ((2, 2, (40, 20, 16)), (0, 0, (255, 226, 150))):
            surf = get_font(46, bold=True).render(f"-{loss}", True, col)
            surf.set_alpha(alpha)
            screen.blit(surf, surf.get_rect(center=(pos.centerx + dx, pos.centery + dy)))

    def draw_stamina_bar(self, screen, gen, bar):
        pygame.draw.rect(screen, (20, 20, 26), bar, border_radius=6)
        ratio = max(0.0, min(1.0, gen.stamina / gen.max_stamina))
        fill = bar.copy()
        fill.width = max(1, int(bar.width * ratio))
        color = ((96, 208, 112) if ratio > 0.5 else
                 (232, 196, 72) if ratio > 0.25 else (226, 84, 72))
        pygame.draw.rect(screen, color, fill, border_radius=6)
        pygame.draw.rect(screen, (86, 94, 112), bar, 1, border_radius=6)
        txt = get_font(15, bold=True).render(
            f"体力 {gen.stamina} / {gen.max_stamina}", True, (245, 245, 245))
        screen.blit(txt, txt.get_rect(center=bar.center))

    def draw_history(self, screen):
        rect = self.HIST_RECT
        pygame.draw.rect(screen, C_PANEL, rect, border_radius=10)
        pygame.draw.rect(screen, C_BTN, rect, 1, border_radius=10)
        total = len(self.rounds)
        title = f"战斗过程（共 {total} 回合）" if total else "战斗过程"
        screen.blit(get_font(14, bold=True).render(title, True, C_TEXT_DIM),
                    (rect.left + 16, rect.top + 10))
        if not total:
            screen.blit(get_font(13).render("尚未交手。", True, C_TEXT_DIM),
                        (rect.left + 16, rect.top + 40))
            return

        end = total - self.scroll                        # 显示第 ... 到第 end 回合
        shown = self.rounds[max(0, end - self.HIST_ROWS):end]
        multi = len(self.defenders) > 1                  # 两场时回合号要带上场次
        if total > self.HIST_ROWS:
            first, last = shown[0], shown[-1]
            span = (f"{first['fight']}-{first['no']} ~ {last['fight']}-{last['no']}"
                    if multi else f"{first['no']}-{last['no']}")
            tip = f"显示第 {span} 回合 · 滚轮 / ↑↓ 翻看"
            tip_surf = get_font(12).render(tip, True, C_TEXT_DIM)
            screen.blit(tip_surf, tip_surf.get_rect(midright=(rect.right - 16, rect.top + 18)))

        font = get_font(14)
        x_round = rect.left + 16
        x_atk = x_round + (136 if multi else 104)
        x_dfd = x_atk + (rect.right - 16 - x_atk) // 2
        y = rect.top + 38
        for record in shown:
            label = (f"第 {record['fight']} 场·{record['no']} 回合" if multi
                     else f"第 {record['no']} 回合")
            screen.blit(font.render(label, True, C_TEXT_DIM), (x_round, y))
            for gen, x in ((self.atk, x_atk), (record["dfd"], x_dfd)):
                loss, hp = ((record["atk_loss"], record["atk_hp"]) if gen is self.atk else
                            (record["dfd_loss"], record["dfd_hp"]))
                text = f"{gen.name}  -{loss}  体力剩 {hp}"
                if hp <= 0:
                    text += "  阵亡"
                screen.blit(font.render(text, True, PLAYER_COLOR[gen.owner]), (x, y))
            y += 22

    def draw_controls(self, screen, mouse_pos):
        font = get_font(17, bold=True)
        if self.state == self.OVER:
            color = (255, 236, 160)
        elif self.state in (self.PICK_DEFENDER, self.RETREAT_PICK):
            color = C_SELECT                   # 这两步要人做选择，字提亮一点
        else:
            color = C_TEXT
        y = self.HINT_Y
        for line in wrap_text(self.hint, font, WIN_W - 120)[:2]:
            surf = font.render(line, True, color)
            screen.blit(surf, surf.get_rect(center=(WIN_W // 2, y)))
            y += 26
        for label, rect, action in self.buttons():
            hover = rect.collidepoint(mouse_pos)
            pygame.draw.rect(screen, C_BTN_HOVER if hover else C_BTN, rect, border_radius=10)
            pygame.draw.rect(screen, self.button_accent(action), rect, 2, border_radius=10)
            if action.startswith("retreat:"):     # 撤退选项格子小，字号跟着位置缩
                font = fit_font(label, rect.width - 14, start=min(15, rect.height - 8),
                                min_size=9)
            else:
                font = get_font(16, bold=True)
            txt = font.render(label, True, C_TEXT)
            screen.blit(txt, txt.get_rect(center=rect.center))
        if self.state == self.RETREAT_PICK:
            foot_text = ("点一个落脚点撤退 · 括号里是这次撤退要透支的行动力，"
                         "本回合累计不能超过 MOVE_POINTS"
                         " · 这里按空格 / 回车不生效，免得误撤")
        elif self.state == self.PICK_DEFENDER:
            foot_text = ("点下方按钮决定谁先出阵 · 排在后面的那位会在前一位下场后接着打"
                         " · 这里按空格 / 回车不生效，免得替你定顺序")
        else:
            foot_text = ("空格 / 回车 = 第一个按钮（交手、继续缠斗、返回战场）  ·  撤退请点按钮"
                         "  ·  滚轮 / ↑↓ 翻看战斗过程  ·  战斗中 ESC / R 不生效")
        foot = get_font(12).render(foot_text, True, C_TEXT_DIM)
        screen.blit(foot, foot.get_rect(center=(WIN_W // 2, self.FOOT_Y)))

    def button_accent(self, action):
        if action in ("atk_retreat", "dfd_retreat") or action.startswith("retreat:"):
            return C_WARN
        if action == "roll" or action == "back" or action.startswith("pick:"):
            return C_GOLD
        return (86, 94, 112)


def wrap_text(text, font, max_width):
    """按像素宽度粗略折行（中文逐字）。"""
    lines, cur = [], ""
    for ch in text:
        if font.size(cur + ch)[0] > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------
# 主循环
# --------------------------------------------------------------------------
def make_buttons():
    x0 = MARGIN * 2 + BOARD
    w = SIDEBAR - 32
    labels = [("结束回合 (空格)", "end"), ("重新开局 (R)", "restart"), ("退出 (ESC)", "quit")]
    rects = []
    # 从面板底部往上排，与 draw_sidebar 保持一致
    panel_bottom = MARGIN + BOARD
    for i, (label, key) in enumerate(reversed(labels)):
        top = panel_bottom - 14 - (i + 1) * 44
        rects.append((label, pygame.Rect(x0 + 16, top, w, 36), key))
    return list(reversed(rects))


def restart(game):
    """重新开局；配置文件被改坏时保留当前对局，只在界面上提示。"""
    try:
        game.new_game()
    except ConfigError as exc:
        game.push_log(f"重开失败：{exc}")
        game.flash("配置有误，重开失败（详见战报）")


def show_config_error(exc):
    """开局就读不到合法配置：开个小窗把原因显示出来，等玩家关掉。"""
    pygame.init()
    screen = pygame.display.set_mode((780, 420))
    pygame.display.set_caption("三国战棋 - 配置有误")
    clock = pygame.time.Clock()
    font = get_font(15)

    lines = wrap_text(f"配置有误：{exc}", font, 730)
    lines += [""]
    for path in (MAP_FILE, ROSTER_FILE):
        lines += wrap_text(f"配置文件：{path}", font, 730)
    lines += wrap_text("修好后重新运行程序即可。", font, 730)

    waiting = True
    while waiting:
        for event in pygame.event.get():
            if event.type in (pygame.QUIT, pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                waiting = False
        screen.fill(C_BG)
        y = 28
        for line in lines:
            screen.blit(font.render(line, True, C_TEXT), (26, y))
            y += 26
        pygame.display.flip()
        clock.tick(FPS)


def main():
    try:
        game = Game()                         # 先确认配置没问题，再开窗口
    except ConfigError as exc:
        print(f"配置有误：{exc}", file=sys.stderr)
        for path in (MAP_FILE, ROSTER_FILE):
            print(f"配置文件：{path}", file=sys.stderr)
        show_config_error(exc)
        pygame.quit()
        sys.exit(1)

    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("三国战棋 - 10x10 回合制对战")
    clock = pygame.time.Clock()

    buttons = make_buttons()

    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif game.battle is not None:
                # 交战界面是单独的一屏：键盘鼠标都归它管。ESC / R 在这里故意不生效，
                # 免得打到一半误触把这一局丢了（关窗口仍然可以退出）。
                key = event.key if event.type == pygame.KEYDOWN else None
                if key in (pygame.K_SPACE, pygame.K_RETURN):
                    game.battle.primary()
                elif key == pygame.K_UP:
                    game.battle.scroll_history(1)
                elif key == pygame.K_DOWN:
                    game.battle.scroll_history(-1)
                elif key == pygame.K_PAGEUP:
                    game.battle.scroll_history(game.battle.HIST_ROWS)
                elif key == pygame.K_PAGEDOWN:
                    game.battle.scroll_history(-game.battle.HIST_ROWS)
                elif event.type == pygame.MOUSEWHEEL:
                    game.battle.scroll_history(event.y)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    game.battle.handle_click(event.pos)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    game.end_turn()
                elif event.key == pygame.K_r:
                    restart(game)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                hit_button = None
                for _label, rect, key in buttons:
                    if rect.collidepoint(mx, my):
                        hit_button = key
                        break
                if hit_button == "end":
                    game.end_turn()
                elif hit_button == "restart":
                    restart(game)
                elif hit_button == "quit":
                    running = False
                else:
                    # 按钮都在右侧面板里（x 远大于棋盘右边界），所以落不到按钮上的点击
                    # 只要在棋盘矩形内就交给棋盘；别再按 y 去卡，否则最下面几行点不到。
                    board_x, board_y = mx - MARGIN, my - MARGIN
                    if 0 <= board_x < BOARD and 0 <= board_y < BOARD:
                        game.handle_board_click(board_y // CELL, board_x // CELL)

        battle = game.battle
        if battle is not None:
            battle.update()                       # 掉血动画放完后自动进入下一步
            battle.draw(screen, mouse_pos)
        else:
            game.tick()
            game.draw(screen, mouse_pos, buttons)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
