# -*- coding: utf-8 -*-
"""计谋 —— 让智力真正参与计算的那一层。

四条计谋（暗度陈仓 / 调虎离山 / 内讧 / 劫粮），成功率和合法目标都由这里定；
界面（用计弹窗、瞄准高亮）在 warlords.py 的 CunningPick / CunningAim 里，
派电脑用计的决策暂时没做（这一版只有人类能用）。

照 ai.py 的老规矩：这里不 import pygame、也不 import warlords——所有函数都从外面
接一个 game 对象来读改写（用到的都是 Game 上那几个公开方法），所以能脱开图形环境
单独测。数值系数全在 constants.py 的 STRATAGEM_* 里，这里只管算式。

三条名词先厘清，后面到处都用
--------------------------
* **用计方 / 施计者**：花 1 点行动力 + 10 点体力放出计谋的那名武将。
* **敌方智力**：规则里的成功率都要减一个"敌方智力"，但目标不同，这个数怎么取不一样，
  而且说法很绕，所以单独封成两个函数（foe_intellect_of / foe_intellect_at）：
    - 对**敌将**用计（调虎离山 / 内讧）：单独站一格就是他自己的智力；
      同格另有**智力比他高**的同伴时，取这两人智力的平均值（同伴智力比他低就不算，
      这条是照规则原样实现的，不是笔误）。
    - 对**格子**用计（劫粮）：格上没武将、或只有己方武将，按空场值 10 算；
      有对方武将就取格上敌方武将里最高的那个智力。
* **成功率**：一律夹在 0~1 之间（智力差得离谱时按 0% 或 100% 算）。
"""

import math
from collections import namedtuple

from config import neighbors
from constants import (
    LOSS_MAX_PER_MIGHT, OBSTACLE,
    STRATAGEM_INFIGHT_DIVISOR, STRATAGEM_INFIGHT_OFFSET,
    STRATAGEM_LURE_DIVISOR, STRATAGEM_LURE_MOVE_CAP, STRATAGEM_LURE_MOVE_DIVISOR,
    STRATAGEM_LURE_MOVE_OFFSET, STRATAGEM_LURE_OFFSET,
    STRATAGEM_MOVE_COST, STRATAGEM_RAID_BASE_INT, STRATAGEM_RAID_DIVISOR,
    STRATAGEM_RANGE, STRATAGEM_SNEAK_DIVISOR, STRATAGEM_STAMINA_COST,
)

# 点目标的方式：点一个落点 / 点一名敌将 / 点一个有粮的格子
AIM_CELL, AIM_FOE, AIM_GRAIN = "cell", "foe", "grain"

Stratagem = namedtuple("Stratagem", "key name aim blurb")

STRATAGEMS = (
    Stratagem("sneak", "暗度陈仓", AIM_CELL,
              "跃过紧邻的障碍，落到正对面那一格"),
    Stratagem("lure", "调虎离山", AIM_FOE,
              f"{STRATAGEM_RANGE} 格内的敌将被牵着走一段"),
    Stratagem("infight", "内讧", AIM_FOE,
              f"{STRATAGEM_RANGE} 格内的两名敌将自相残杀一回合"),
    Stratagem("raid", "劫粮", AIM_GRAIN,
              "把某一格上的粮草全搬到自己脚下"),
)
BY_KEY = {s.key: s for s in STRATAGEMS}

# 一次用计的目标：cell 是要点的格子，foe_int 是这一目标对应的"敌方智力"，
# foe 是中计的那名敌将（暗度陈仓 / 劫粮没有，是 None）。
Target = namedtuple("Target", "cell foe_int foe")


def stratagem(key):
    return BY_KEY[key]


def name_of(key):
    return BY_KEY[key].name


# --------------------------------------------------------------------------
# 代价
# --------------------------------------------------------------------------
def cost_ok(gen):
    """这名武将现在付得起用计的代价吗（1 点行动力 + 10 点体力）。

    体力卡的是**多于** 10 而不是"至少 10"：正好 10 点的话付完就归零，
    按规则那是阵亡，等于用计自尽——那不是"够用"该有的样子，所以留 1 点底。
    """
    return (gen.alive
            and gen.move_points >= STRATAGEM_MOVE_COST
            and gen.stamina > STRATAGEM_STAMINA_COST)


def pay(gen):
    """把代价结掉。调用方必须先用 cost_ok 确认过。"""
    gen.move_points -= STRATAGEM_MOVE_COST
    gen.add_stamina(-STRATAGEM_STAMINA_COST)


# --------------------------------------------------------------------------
# 敌方智力
# --------------------------------------------------------------------------
def foe_intellect_of(game, foe):
    """对**敌将** foe 用计时，"敌方智力"取多少。

    单独站一格就是他自己；同格另有智力比他高的同伴时，取目标与那名同伴的平均值。
    同格同伴智力比他低就不算数（照规则原样）。
    """
    mates = [g for g in game.generals_at(*foe.pos) if g is not foe]
    higher = [g.intellect for g in mates if g.intellect > foe.intellect]
    if higher:
        return (foe.intellect + max(higher)) / 2
    return float(foe.intellect)


def foe_intellect_at(game, cell, owner):
    """对**格子** cell 用计时（劫粮），"敌方智力"取多少。

    格上没武将、或只有用计方自己人 -> 空场值 10；有对方武将 -> 取他们里最高的智力。
    """
    foes = [g for g in game.generals_at(*cell) if g.owner != owner]
    if not foes:
        return float(STRATAGEM_RAID_BASE_INT)
    return float(max(g.intellect for g in foes))


# --------------------------------------------------------------------------
# 成功率与调动格数
# --------------------------------------------------------------------------
def chance(key, my_intellect, foe_int):
    """这一计的成功率，夹在 0~1 之间。"""
    if key == "sneak":
        raw = my_intellect / STRATAGEM_SNEAK_DIVISOR
    elif key == "lure":
        raw = (my_intellect - foe_int - STRATAGEM_LURE_OFFSET) / STRATAGEM_LURE_DIVISOR
    elif key == "infight":
        raw = (my_intellect - foe_int - STRATAGEM_INFIGHT_OFFSET) / STRATAGEM_INFIGHT_DIVISOR
    elif key == "raid":
        raw = (my_intellect - foe_int) / STRATAGEM_RAID_DIVISOR
    else:
        raise ValueError(f"没有这一计：{key!r}")
    return max(0.0, min(1.0, raw))


def chance_of(game, gen, key, target):
    """某一目标上这一计的成功率（界面直接拿去显示）。"""
    return chance(key, gen.intellect, target.foe_int)


def lure_move_cap(my_intellect, foe_int):
    """调虎离山最多能把敌将调走几格：min(floor((智力差 - 2) / 2), 6)。

    差值不够就是 0——这一计对这个目标根本使不出来（不会拿"0 格"去糊弄）。
    """
    steps = math.floor((my_intellect - foe_int - STRATAGEM_LURE_MOVE_OFFSET)
                       / STRATAGEM_LURE_MOVE_DIVISOR)
    return max(0, min(steps, STRATAGEM_LURE_MOVE_CAP))


def distance(a, b):
    """两格的欧氏距离（格子中心到格子中心）。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --------------------------------------------------------------------------
# 合法目标
# --------------------------------------------------------------------------
def targets(game, gen, key):
    """这一计现在能点哪些目标 -> {(行,列): Target}；一个都没有就是空表。

    三条计谋都会把"使了也白使"的目标滤掉，免得界面上摆出一堆死路：
    成功率为 0 的、调不动格数的、边上凑不出第二个人的、搬不动粮的。
    """
    if not cost_ok(gen):
        return {}
    if key == "sneak":
        return _sneak_targets(game, gen)
    if key == "lure":
        return _lure_targets(game, gen)
    if key == "infight":
        return _infight_targets(game, gen)
    if key == "raid":
        return _raid_targets(game, gen)
    raise ValueError(f"没有这一计：{key!r}")


def _sneak_targets(game, gen):
    """暗度陈仓：四个正方向看过去，紧邻那格是障碍、正对面那格能落脚，就能跳。"""
    out = {}
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        mid = (gen.row + dr, gen.col + dc)
        dest = (gen.row + dr * 2, gen.col + dc * 2)
        if not game.in_bounds(*dest):
            continue
        if game.grid[mid[0]][mid[1]] != OBSTACLE:      # 中间那格必须真是障碍，才叫"跃过"
            continue
        if not game.can_stop(gen, *dest):             # 落点得能停下（无敌方、己方不满员）
            continue
        out[dest] = Target(dest, 0.0, None)
    return out


def _foes(game, gen):
    """场上的敌将（用计方的对面那一方），只看活着的。"""
    return [g for g in game.generals if g.alive and g.owner != gen.owner]


def _lure_targets(game, gen):
    """调虎离山：射程内的敌将，且智力差够；还得真有地方可调，不然调了也白调。"""
    out = {}
    for foe in _foes(game, gen):
        if distance(gen.pos, foe.pos) > STRATAGEM_RANGE:
            continue
        foe_int = foe_intellect_of(game, foe)
        cap = lure_move_cap(gen.intellect, foe_int)
        if cap < 1 or chance("lure", gen.intellect, foe_int) <= 0:
            continue
        if not lure_dests(game, foe, cap):             # 四面走不动，调不动
            continue
        out[foe.pos] = Target(foe.pos, foe_int, foe)
    return out


def _infight_targets(game, gen):
    """内讧：射程内的敌将，且他同格或相邻还有别的敌将——凑得出两个人才能内讧。"""
    out = {}
    for foe in _foes(game, gen):
        if distance(gen.pos, foe.pos) > STRATAGEM_RANGE:
            continue
        foe_int = foe_intellect_of(game, foe)
        if chance("infight", gen.intellect, foe_int) <= 0:
            continue
        if not infight_partners(game, foe):            # 身边没人，内讧不起来
            continue
        out[foe.pos] = Target(foe.pos, foe_int, foe)
    return out


def _raid_targets(game, gen):
    """劫粮：场上有粮的格子，除了自己脚下那一格（搬到自己脚下等于没搬）。"""
    out = {}
    for cell, amount in game.grain.items():
        if amount <= 0 or cell == gen.pos:
            continue
        foe_int = foe_intellect_at(game, cell, gen.owner)
        if chance("raid", gen.intellect, foe_int) <= 0:
            continue
        out[cell] = Target(cell, foe_int, None)
    return out


def infight_partners(game, foe):
    """内讧可以拉谁下水 -> {格: [敌将, ...]}（同格或相邻、且是 foe 的同僚）。

    同格能站两名，所以一个格子里可能不止一名候选；界面按格高亮，
    点下去时取武力最高的那个（打得更疼，见 pick_partner）。
    """
    cells = {foe.pos} | set(neighbors(*foe.pos))
    out = {}
    for cell in cells:
        mates = [g for g in game.generals_at(*cell)
                 if g is not foe and g.owner == foe.owner]
        if mates:
            out[cell] = mates
    return out


def pick_partner(mates):
    """同格有好几名候选时挑谁上场：取武力最高的（下刀最狠）。"""
    return max(mates, key=lambda g: (g.might, g.name))


# --------------------------------------------------------------------------
# 调虎离山的落脚点
# --------------------------------------------------------------------------
def lure_dests(game, foe, steps_limit):
    """中计的敌将被牵着走时能站到哪些格 -> {格: 步数}。

    走的是**普通移动规则**：一格一格挪，中途过得去（通路/城池、无敌方）、
    落脚停得下（己方不满 CELL_CAPACITY）。只有一点不照搬——**不看这名敌将自己的
    移动力**：他是被牵着走的，不是自己行动，所以跟他这回合还剩几点无关。

    上限 steps_limit 是掷出来的调动格数，实际走几格由用计方在这张表里挑。
    """
    if steps_limit < 1:
        return {}
    seen = {foe.pos}
    q = [(foe.row, foe.col, 0)]
    out = {}
    while q:
        r, c, d = q.pop(0)
        if d >= steps_limit:
            continue
        for nb in neighbors(r, c):
            if nb in seen or not game.can_transit(foe, *nb):
                continue
            seen.add(nb)
            if game.can_stop(foe, *nb):
                out[nb] = d + 1
            q.append((nb[0], nb[1], d + 1))
    return out


# --------------------------------------------------------------------------
# 效果落地
# --------------------------------------------------------------------------
def apply_sneak(game, gen, dest):
    """暗度陈仓：人就那么跃过去。不扣体力，代价早在用出去时结过了。"""
    frm = game.describe(gen.row, gen.col)
    gen.row, gen.col = dest
    game.push_log(f"🎴 {gen.name} 暗度陈仓，从 {frm} 跃入 {game.describe(*dest)}。")
    return True


def apply_lure(game, foe, dest, steps):
    """调虎离山：中计的敌将被挪到 dest（不含他原本站的那格）。"""
    frm = game.describe(foe.row, foe.col)
    foe.row, foe.col = dest
    game.push_log(f"🎴 {foe.name} 中计被调走，从 {frm} 走到 {game.describe(*dest)}"
                  f"（{steps} 格）。")
    return True


def apply_infight(game, first, second):
    """内讧：两名敌将自相残杀一回合，谁都不挪窝 -> (first 掉血, second 掉血)。

    掉血用的就是交战那一套（各按对方武力取 [1, LOSS_MAX_PER_MIGHT * 对方武力]），
    但**不算守城加成**——他们是在自家人堆里互砍，不是在据城防守。
    两边同时结算，谁掉到 0 谁当场阵亡。
    """
    loss_first = game.rng.randint(1, LOSS_MAX_PER_MIGHT * second.might)
    loss_second = game.rng.randint(1, LOSS_MAX_PER_MIGHT * first.might)
    first.add_stamina(-loss_first)
    second.add_stamina(-loss_second)
    for gen, loss in ((first, loss_first), (second, loss_second)):
        if gen.stamina <= 0:
            gen.alive = False
        game.push_log(f"🎴 {gen.name} 掉 {loss} 点体力"
                      f"（{gen.stamina + loss}→{max(0, gen.stamina)}）"
                      + ("，力竭阵亡！" if not gen.alive else "。"))
    duel = f"{first.name}（武力 {first.might}）与 {second.name}（武力 {second.might}）"
    game.push_log(f"🎴 内讧：{duel}自相残杀一回合，两败俱伤，谁都没挪窝。")
    return loss_first, loss_second


def apply_raid(game, gen, cell):
    """劫粮：把目标格上的粮草全部搬到用计方脚下 -> 搬回来几石。"""
    amount = game.take_grain(cell[0], cell[1], game.grain_at(*cell))
    if amount <= 0:
        return 0
    game.add_grain(gen.row, gen.col, amount)
    game.push_log(f"🎴 {gen.name} 劫粮，把 {game.describe(*cell)} 上的 "
                  f"{amount} 石粮草搬到了 {game.describe(gen.row, gen.col)}。")
    return True
