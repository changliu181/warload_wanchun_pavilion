# -*- coding: utf-8 -*-
"""map.txt / generals.txt 的解析与校验。

从 warlords.py 拆出：读配置 -> 校验 -> 产出 grid / places / roster。
任何格式问题都抛 ConfigError 的子类，由调用方（Game / 界面）呈现给玩家。
只依赖 constants，不 import pygame。
"""
from collections import deque

from constants import (
    CITY_CHAR, CITY_COUNT, DEPLOY_COUNT, FACTION_PLAYER, GRID, GeneralSpec, MAP_LEGEND,
    MAX_STAT, NAME_SEP, OBSTACLE, OBSTACLE_CHAR, P1, P2, PLAIN, PLAYER_NAME, ROSTER_SIZE,
    SPAWN_ROWS,
)

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
        need = DEPLOY_COUNT[player]
        if len(cells) < need:
            half = "上" if player == P1 else "下"
            raise MapConfigError(
                f"{half}半场只有 {len(cells)} 格可通行，"
                f"放不下 {PLAYER_NAME[player]} 的 {need} 名武将。")


def pick_spawns(grid, rng):
    """开局时按地形随机分出生点（map.txt 里没有出生点）。

    玩家一从上半场抽 DEPLOY_COUNT[P1] 格、玩家二从下半场抽 DEPLOY_COUNT[P2] 格
    （两边人数可以不一样），同一方互不重复；
    每次开局（含按 R 重开）都重新抽，所以同一张地图每局站位都不一样。
    """
    return {player: rng.sample(walkable_in(grid, SPAWN_ROWS[player]), DEPLOY_COUNT[player])
            for player in (P1, P2)}


def parse_roster(path):
    """读取武将配置 -> {玩家: [GeneralSpec, ...]}；格式不对抛 RosterConfigError。

    每行 4 项：阵营 姓名 武力 智力（例：蜀 关羽 21 14）。只解析，不抽将——
    哪几名上阵（两边可以不一样多）由 Game.create_generals 在开局时随机抽。
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
        need = DEPLOY_COUNT[player]
        if not 1 <= need <= got:
            raise RosterConfigError(
                f"{PLAYER_NAME[player]}要上阵 {need} 名，应在 1-{got} 之间"
                f"（DEPLOY_COUNT[{PLAYER_NAME[player]}]）。")
    return roster
