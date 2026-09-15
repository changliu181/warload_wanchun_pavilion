# -*- coding: utf-8 -*-
"""
三国战棋 —— 10x10 格子地图上的双人回合制对战小游戏（Pygame）

规则概要
--------
* 地图 10x10，每格一种地形：障碍(不可通行) / 通路 / 城池(可通行，防御 +30%，驻守回血更多)
  地形用整数枚举定义，以后想加第 4 种（如"树林"）只需在 TERRAIN_* 后面追加并把
  TERRAIN_NAME / TERRAIN_COLOR / REGEN 里补一条即可。
* 地图不做随机生成，固定写在与本文件同目录的 map.txt 里：10 行 x 10 列、正好 10 座城池、
  双方各 3 个出生点，左右可以不对称。改完地图保存后，在游戏里按 R 即可按新地图重开。
* 双方各有 3 名武将，属性：
    - 武力 might     ：固定值，决定战斗判定权重
    - 智力 intellect ：固定值，目前只作展示，不参与计算
    - 体力 stamina   ：可变值，上限 100。只有战斗会消耗体力；
                       每回合开始时按所在地形恢复（通路 +8 / 城池 +16）
* 移动：每名武将有 MOVE_POINTS 点移动力，回合开始时重置为 3，每挪到相邻一格花 1 点，
        所以一回合最多走 3 格。移动力与体力完全脱钩：移动不消耗体力，
        体力见底也能照走 3 格。
* 回合制：双方轮流行动；只要移动力还没花完，这名武将就能继续行动（继续走或继续交战），
        移动力花完了本回合才动不了。
* 交战：把己方武将的移动目标点成"相邻的敌方武将格子"（踏进去）即触发交战，消耗 1 点移动力。
        必须从相邻格踏入，不能隔着格子冲锋。
        先按双方战力加权随机判定胜负，再结算伤害——这一版就是"随机判定胜负"的简化模型。
        战力 = 武力 + 体力 * 0.5，防守方（原本驻守这一格的一方）站在城池上额外 * 1.3
        败者掉血并让出这一格：进攻方败则退回冲锋前所在的格子，
        防守方败则被挤到旁边的空格（优先沿冲锋方向继续往外）。
        体力归零则该武将阵亡，格子由胜者占据。
* 胜负：一方武将全灭即败；回合数达到上限时按 存活武将*100 + 总体力 + 占据城池*50 比总分。

操作
----
* 鼠标左键：点自己的武将选中 / 点高亮格移动 / 点相邻的敌人格子冲进去交战 / 点侧边栏按钮
* 空格 或 回车：结束回合
* R：重新开局（重新读取 map.txt 的固定地图）      ESC：退出
"""

import random
import sys
from collections import deque
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
REGEN = {OBSTACLE: 0, PLAIN: 8, CITY: 16}
ASSAULT_COST = 8        # 冲进敌方格子交战的额外体力消耗

P1, P2 = 0, 1
PLAYER_NAME = {P1: "玩家一（红·蜀）", P2: "玩家二（蓝·魏）"}
PLAYER_COLOR = {P1: (206, 74, 62), P2: (72, 124, 214)}
PLAYER_COLOR_DARK = {P1: (128, 42, 36), P2: (40, 74, 136)}

# 固定地图配置（不做随机生成）
MAP_FILE = Path(__file__).with_name("map.txt")
CITY_COUNT = 10                   # map.txt 里应正好有 10 座城池
MAP_LEGEND = {                    # 配置字符 -> 地形（1/2 是出生点，脚下按通路算）
    ".": PLAIN,
    "#": OBSTACLE,
    "C": CITY,
    "1": PLAIN,
    "2": PLAIN,
}
MAP_SPAWN = {"1": P1, "2": P2}    # 配置字符 -> 该出生点属于谁

NAMES = {
    P1: ["关羽", "张飞", "赵云"],
    P2: ["张辽", "许褚", "徐晃"],
}

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
C_TEXT = (228, 231, 238)
C_TEXT_DIM = (150, 156, 170)
C_SELECT = (255, 236, 150)
C_ATTACK = (255, 96, 82)
C_BTN = (52, 57, 70)
C_BTN_HOVER = (74, 82, 100)

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


# --------------------------------------------------------------------------
# 地图配置
# --------------------------------------------------------------------------
class MapConfigError(Exception):
    """map.txt 有问题（行数 / 字符 / 城池数 / 出生点 / 连通性）。"""


def neighbors(r, c):
    """四邻格（不越界）。"""
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < GRID and 0 <= nc < GRID:
            yield nr, nc


def parse_map(path):
    """读取固定地图配置 -> (grid, spawns)；格式不对抛 MapConfigError。"""
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MapConfigError(f"读不到地图文件 {path}：{exc}") from exc

    # 跳过空行和 // 注释行；行内的空格制表符只是排版用的，全部忽略
    lines = [(no, "".join(text.split())) for no, text in enumerate(raw, 1)
             if text.strip() and not text.lstrip().startswith("//")]
    if len(lines) != GRID:
        raise MapConfigError(f"地图应有 {GRID} 行，实际 {len(lines)} 行。")

    grid = [[PLAIN] * GRID for _ in range(GRID)]
    spawns = {P1: [], P2: []}
    cities = 0
    for r, (no, text) in enumerate(lines):
        if len(text) != GRID:
            raise MapConfigError(
                f"第 {no} 行应有 {GRID} 个地形字符，实际 {len(text)} 个：{text}")
        for c, ch in enumerate(text):
            if ch not in MAP_LEGEND:
                raise MapConfigError(
                    f"第 {no} 行第 {c + 1} 个地形字符是 {ch!r}（可用：{' '.join(MAP_LEGEND)}）")
            grid[r][c] = MAP_LEGEND[ch]
            if ch == "C":
                cities += 1
            elif ch in MAP_SPAWN:
                spawns[MAP_SPAWN[ch]].append((r, c))

    if cities != CITY_COUNT:
        raise MapConfigError(f"地图应有 {CITY_COUNT} 座城池，实际 {cities} 座。")
    for player in (P1, P2):
        need = len(NAMES[player])
        got = len(spawns[player])
        if got != need:
            raise MapConfigError(
                f"{PLAYER_NAME[player]}需要 {need} 个出生点（{'/'.join(MAP_SPAWN)}），实际 {got} 个。")
    validate_map(grid, spawns)
    return grid, spawns


def validate_map(grid, spawns):
    """所有可通行格必须连成一片，否则双方可能碰不上面。"""
    walkable = {(r, c) for r in range(GRID) for c in range(GRID)
                if grid[r][c] != OBSTACLE}
    origins = spawns[P1] + spawns[P2]
    seen = {origins[0]}
    q = deque([origins[0]])
    while q:
        r, c = q.popleft()
        for cell in neighbors(r, c):
            if cell in walkable and cell not in seen:
                seen.add(cell)
                q.append(cell)
    unreachable = [p for p in origins if p not in seen]
    if unreachable:
        raise MapConfigError(f"地图不连通，这些出生点走不到：{unreachable}。")
    islands = sorted(walkable - seen)
    if islands:
        raise MapConfigError(f"地图有被墙隔开的孤岛格：{islands}。")


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

    @property
    def pos(self):
        return (self.row, self.col)

    @property
    def exhausted(self):
        """本回合移动力已用尽，不能再走也不能交战。"""
        return self.move_points <= 0

    @property
    def power(self):
        return self.might + self.stamina * 0.5

    def reset_turn(self):
        self.move_points = MOVE_POINTS

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
        self.load_map()                       # 先读地图：配置有问题就不会动到当前对局
        self.generals = []
        self.create_generals()
        self.current = P1
        self.turn = 1
        self.selected = None
        self.reachable = {}
        self.attackable = set()
        self.log = []
        self.banner = None                # (文本, 剩余帧数)
        self.winner = None
        self.push_log("新的一局开始，玩家一先行。")
        self.start_turn(regen=False)

    def load_map(self, path=None):
        """从固定地图配置读取地形和出生点（校验不过抛 MapConfigError）。"""
        grid, spawns = parse_map(Path(path) if path else MAP_FILE)
        self.grid = grid
        self.spawns = spawns

    def create_generals(self):
        for player in (P1, P2):
            for name, (r, c) in zip(NAMES[player], self.spawns[player]):
                self.generals.append(General(name, self.rng.randint(62, 95),
                                             self.rng.randint(40, 95), player, r, c))

    # ---------------- 基础查询 ----------------
    def generals_at(self, r, c):
        return [g for g in self.generals if g.alive and g.pos == (r, c)]

    def is_blocked(self, r, c):
        """障碍或已有武将的格子：既不能走上去，也不能穿过去。"""
        return self.grid[r][c] == OBSTACLE or bool(self.generals_at(r, c))

    def free_for(self, gen, r, c):
        """gen 能否站到 (r,c)：不是障碍，且除了 gen 自己之外没有别的武将。"""
        if not (0 <= r < GRID and 0 <= c < GRID) or self.grid[r][c] == OBSTACLE:
            return False
        return all(other is gen for other in self.generals_at(r, c))

    def compute_reachable(self, gen):
        """BFS 算出该武将本回合能走到的空格 -> {pos: 需要花掉的移动力}

        移动力只决定能走多远，与体力无关；所以这里也不看体力。
        这里只算空出来的落脚点：敌方武将的格子不在这里，走进去等于交战，
        由 compute_attackable 单独给出。
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
                if (nr, nc) in seen or self.is_blocked(nr, nc):
                    continue
                seen.add((nr, nc))
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
        target = self.generals_at(row, col)
        if target:
            gen = target[0]
            if gen.owner == self.current:
                self.select(gen)              # 选自己人（含已走完的，用于看属性）
                return
            # 点敌人：必须已选中、且相邻（相邻格才能踏进去交战）
            if self.selected and (row, col) in self.attackable:
                self.charge(self.selected, gen)
            elif self.selected:
                self.push_log("要交战得先走到敌人旁边，从相邻格踏进去。")
            return
        if self.selected and (row, col) in self.reachable:
            self.move(self.selected, row, col)
        else:
            self.clear_selection()

    def move(self, gen, row, col):
        """走一步（或一次走好几格）：按格数扣移动力，不扣体力。"""
        steps = self.reachable[(row, col)]
        terrain = self.grid[row][col]
        gen.row, gen.col = row, col
        gen.move_points = max(0, gen.move_points - steps)
        self.push_log(f"{gen.name} 移动 {steps} 格至 ({row},{col})，"
                      f"{TERRAIN_NAME[terrain]}，剩余移动力 {gen.move_points}。")
        self.select(gen)                      # 重新计算剩余可走范围
        # 移动后若与敌人相邻，提示可以打
        if self.compute_attackable(gen):
            self.push_log(f"{gen.name} 与敌军相邻，可以踏进去交战！")

    # ---------------- 战斗 ----------------
    def charge(self, attacker, defender):
        """从相邻格踏进敌方武将所在的格子，触发交战。

        消耗 1 点移动力 + 一次突击体力；交战不结束该武将的行动，
        只要还有移动力就能接着走或者接着撞下一个人。
        """
        origin = attacker.pos
        terrain = self.grid[defender.row][defender.col]
        attacker.row, attacker.col = defender.pos       # 先踏进对方格子
        attacker.move_points = max(0, attacker.move_points - 1)
        attacker.add_stamina(-ASSAULT_COST)

        self.resolve_battle(attacker, defender, origin, terrain)

        if attacker.alive:
            if attacker.exhausted:
                self.clear_selection()
            else:
                self.select(attacker)                   # 还有移动力就继续行动
        else:
            self.clear_selection()
        self.check_victory()

    def resolve_battle(self, atk, dfd, origin, terrain):
        """atk 已踏进 dfd 的格子；origin 是冲锋前所在的格子，terrain 是交战格地形。"""
        atk_power = atk.power
        dfd_power = dfd.power
        if terrain == CITY:
            dfd_power *= 1.3                  # 城池防御加成（守方是原本驻守这一格的人）
        total = atk_power + dfd_power
        p_atk = atk_power / total if total > 0 else 0.5
        roll = self.rng.random()
        winner, loser = (atk, dfd) if roll < p_atk else (dfd, atk)

        base = 26 + winner.might * 0.35 + self.rng.uniform(0, 14)
        if terrain == CITY and loser is dfd:
            base *= 0.85                      # 守城减伤
        damage = int(round(base))
        loser.add_stamina(-damage)
        winner.add_stamina(-int(damage * 0.25))   # 胜者也有损耗

        self.push_log(f"⚔ {atk.name} 踏进 {dfd.name} 的格子（胜率 {p_atk:.0%}）："
                      f"{winner.name} 胜，{loser.name} 损失 {damage} 体力。")
        self.flash(f"{winner.name} 击败 {loser.name}！(-{damage} 体力)")

        for gen in (loser, winner):
            if gen.alive and gen.stamina <= 0:
                gen.alive = False
                self.push_log(f"☠ {gen.name} 体力耗尽，阵亡！")

        if not winner.alive or not loser.alive:
            return                            # 格子归还活着的那一方，无需再挪
        if loser is atk:
            self.retreat(atk, origin)         # 进攻方败：退回冲锋前所在的格子
        elif not self.dislodge(dfd, origin):
            self.retreat(atk, origin)         # 防守方败却无处可挪：胜者也不进占

    def retreat(self, gen, cell):
        """把 gen 挪回 cell（冲锋前的出发格，此时必定空着）；万一被占就就近找个空位。"""
        if self.free_for(gen, *cell):
            gen.row, gen.col = cell
            return True
        return self.dislodge(gen, cell)

    def dislodge(self, gen, origin):
        """把 gen 挤到旁边的空格：优先沿冲锋方向继续往外，再退回其它方向。"""
        dirs = []
        if origin is not None:
            dr = (gen.row - origin[0])
            dc = (gen.col - origin[1])
            dr, dc = (dr > 0) - (dr < 0), (dc > 0) - (dc < 0)
            if dr or dc:
                dirs.append((dr, dc))
        dirs += [d for d in ((-1, 0), (1, 0), (0, -1), (0, 1)) if d not in dirs]
        for dr, dc in dirs:
            if self.free_for(gen, gen.row + dr, gen.col + dc):
                gen.row, gen.col = gen.row + dr, gen.col + dc
                return True
        return False

    # ---------------- 回合流程 ----------------
    def end_turn(self):
        if self.winner is not None:
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
        self.winner = player
        self.push_log(text)
        self.banner = [text, 60 * 30]         # 长提示常驻

    # ---------------- 提示信息 ----------------
    def push_log(self, msg):
        self.log.append(msg)
        del self.log[:-9]

    def flash(self, msg, frames=90):
        self.banner = [msg, frames]

    def tick(self):
        if self.banner:
            self.banner[1] -= 1
            if self.banner[1] <= 0 and self.winner is None:
                self.banner = None

    # ---------------- 绘制 ----------------
    def cell_rect(self, row, col):
        return pygame.Rect(MARGIN + col * CELL, MARGIN + row * CELL, CELL, CELL)

    def draw(self, screen, mouse_pos, buttons):
        screen.fill(C_BG)
        self.draw_board(screen)
        self.draw_sidebar(screen, mouse_pos, buttons)

    def draw_board(self, screen):
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
                pygame.draw.rect(screen, C_GRID, rect, 1)

        # --- 可走范围 / 可攻击目标 ---
        overlay = pygame.Surface((BOARD, BOARD), pygame.SRCALPHA)
        for (r, c) in self.reachable:
            x, y = c * CELL, r * CELL
            pygame.draw.rect(overlay, (255, 236, 150, 55), (x, y, CELL, CELL))
        for (r, c) in self.attackable:
            x, y = c * CELL, r * CELL
            pygame.draw.rect(overlay, (255, 96, 82, 70), (x, y, CELL, CELL))
        screen.blit(overlay, (MARGIN, MARGIN))

        # --- 武将 ---
        for gen in self.generals:
            if gen.alive:
                self.draw_general(screen, gen)

        # --- 选中框 ---
        if self.selected:
            rect = self.cell_rect(*self.selected.pos).inflate(2, 2)
            pygame.draw.rect(screen, C_SELECT, rect, 3, border_radius=4)

    def draw_obstacle(self, screen, rect):
        pygame.draw.line(screen, C_OBSTACLE_LINE, rect.topleft, rect.bottomright, 2)
        pygame.draw.line(screen, C_OBSTACLE_LINE, rect.topright, rect.bottomleft, 2)

    def draw_city(self, screen, rect, r, c):
        # 城墙砖缝
        for i in range(1, 3):
            y = rect.top + CELL * i // 3
            pygame.draw.line(screen, (96, 78, 52), (rect.left + 3, y), (rect.right - 3, y), 1)
        # 垛口
        for i in range(3):
            x = rect.left + 6 + i * (CELL - 16) // 2
            pygame.draw.rect(screen, (150, 126, 88), (x, rect.top + 4, 8, 7))
        # 归属边框
        holder = self.generals_at(r, c)
        if holder:
            pygame.draw.rect(screen, PLAYER_COLOR[holder[0].owner], rect, 2, border_radius=3)
        else:
            f = get_font(11)
            txt = f.render("城池", True, (206, 184, 140))
            screen.blit(txt, txt.get_rect(center=(rect.centerx, rect.bottom - 12)))

    def draw_general(self, screen, gen):
        rect = self.cell_rect(gen.row, gen.col)
        body = rect.inflate(-8, -8)
        color = PLAYER_COLOR[gen.owner]
        dark = PLAYER_COLOR_DARK[gen.owner]
        # 圆角方块作为武将底盘
        pygame.draw.rect(screen, dark, body, border_radius=8)
        pygame.draw.rect(screen, color, body.inflate(-4, -4), border_radius=6)

        name_font = get_font(14, bold=True)
        stat_font = get_font(11)
        name_txt = name_font.render(gen.name, True, (255, 255, 255))
        screen.blit(name_txt, name_txt.get_rect(center=(rect.centerx, rect.top + 15)))
        stat_txt = stat_font.render(f"武{gen.might} 智{gen.intellect}", True, (250, 250, 250))
        screen.blit(stat_txt, stat_txt.get_rect(center=(rect.centerx, rect.top + 32)))

        # 体力条
        bar = pygame.Rect(rect.left + 9, rect.bottom - 15, CELL - 18, 6)
        pygame.draw.rect(screen, (20, 20, 24), bar, border_radius=3)
        ratio = max(0.0, gen.stamina / gen.max_stamina)
        fill = bar.copy()
        fill.width = max(1, int(bar.width * ratio))
        hp_color = (96, 208, 112) if ratio > 0.5 else (232, 196, 72) if ratio > 0.25 else (226, 84, 72)
        pygame.draw.rect(screen, hp_color, fill, border_radius=3)
        hp_txt = get_font(10).render(str(gen.stamina), True, (245, 245, 245))
        screen.blit(hp_txt, hp_txt.get_rect(center=(rect.centerx, rect.bottom - 6)))

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

        if self.winner is None:
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
        roster_h = 2 * (18 + 3 * 17) + 8
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
            tip = get_font(12).render("点击己方武将查看详情 / 移动", True, C_TEXT_DIM)
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
        note = f"位于 {TERRAIN_NAME[self.grid[gen.row][gen.col]]} ({gen.row},{gen.col})"
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
    """重新开局；map.txt 被改坏时保留当前对局，只在界面上提示。"""
    try:
        game.new_game()
    except MapConfigError as exc:
        game.push_log(f"重开失败：{exc}")
        game.flash("地图配置有误，重开失败（详见战报）")


def show_map_error(exc):
    """开局就读不到合法地图：开个小窗把原因显示出来，等玩家关掉。"""
    pygame.init()
    screen = pygame.display.set_mode((780, 420))
    pygame.display.set_caption("三国战棋 - 地图配置有误")
    clock = pygame.time.Clock()
    font = get_font(15)

    lines = wrap_text(f"地图配置有误：{exc}", font, 730)
    lines += [""]
    lines += wrap_text(f"配置文件：{MAP_FILE}", font, 730)
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
        game = Game()                         # 先确认地图配置没问题，再开窗口
    except MapConfigError as exc:
        print(f"地图配置有误：{exc}", file=sys.stderr)
        print(f"配置文件：{MAP_FILE}", file=sys.stderr)
        show_map_error(exc)
        pygame.quit()
        sys.exit(1)

    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("三国战棋 - 10x10 回合制对战")
    clock = pygame.time.Clock()

    buttons = make_buttons()
    btn_lookup = {key: rect for _label, rect, key in buttons}
    bottom_top = min(rect.top for _l, rect, _k in buttons)

    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
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
                elif my < bottom_top:
                    board_x, board_y = mx - MARGIN, my - MARGIN
                    if 0 <= board_x < BOARD and 0 <= board_y < BOARD:
                        game.handle_board_click(board_y // CELL, board_x // CELL)

        game.tick()
        game.draw(screen, mouse_pos, buttons)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
