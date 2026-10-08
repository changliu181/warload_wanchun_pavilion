# -*- coding: utf-8 -*-
"""计谋的无头回归测试：算式、合法目标、代价、四种效果都过一遍。

    python smoke_test.py       # 整局对打的回归（改规则后主要跑这个）
    python stratagem_test.py   # 计谋这一块（改 stratagems.py / 计谋界面后跑这个）

不用图形界面，也不用 pytest：每项自己算一遍期望值，对不上就记一笔，最后统一报有几项没过。
需要窗口的只有最后那几帧绘制自检，走 dummy 显卡驱动。
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pygame

import stratagems as S
import warlords as W
from constants import (CELL, MARGIN, OBSTACLE, STRATAGEM_MOVE_COST,
                       STRATAGEM_STAMINA_COST, WIN_H, WIN_W)

FAILS = []


def check(label, got, want):
    """比一项；对不上就记下来（都跑完再一起报，免得第一处就断了）。"""
    if got == want:
        print(f"  ✔ {label}")
    else:
        print(f"  ✘ {label}：得到 {got!r}，应为 {want!r}")
        FAILS.append(label)


def scene(caster, foes, grain=None):
    """摆一个只有这几名武将的干净局面。"""
    game = W.Game(seed=11)
    game.generals = [caster] + list(foes)
    game.grain = dict(grain or {})
    game.selected = caster
    return game


def gen(name, might, intellect, owner, row, col):
    return W.General(name, might, intellect, owner, row, col)


# --------------------------------------------------------------------------
print("\n[1] 成功率算式")
# --------------------------------------------------------------------------
check("暗度陈仓 智力22", round(S.chance("sneak", 22, 0), 4), 0.88)
check("暗度陈仓 智力1", round(S.chance("sneak", 1, 0), 4), 0.04)
check("调虎离山 (22-10-6)/8", S.chance("lure", 22, 10), 0.75)
check("调虎离山 差值不够夹到 0", S.chance("lure", 5, 10), 0.0)
check("内讧 (22-10-8)/8", S.chance("infight", 22, 10), 0.5)
check("劫粮 (22-10)/20", S.chance("raid", 22, 10), 0.6)
check("劫粮 夹到 1", S.chance("raid", 22, 1), 1.0)
check("劫粮 夹到 0", S.chance("raid", 1, 22), 0.0)

# --------------------------------------------------------------------------
print("\n[2] 调动格数上限 min(floor((差-2)/2), 6)")
# --------------------------------------------------------------------------
check("差 12 -> (12-2)/2 = 5", S.lure_move_cap(22, 10), 5)
check("差 21 -> 9 但封顶 6", S.lure_move_cap(22, 1), 6)
check("差 2 -> 0（调不动）", S.lure_move_cap(22, 20), 0)
check("差 0 -> 0", S.lure_move_cap(10, 10), 0)

# --------------------------------------------------------------------------
print("\n[3] 欧氏距离（射程 3）")
# --------------------------------------------------------------------------
check("正交 3 格刚好在射程上", S.distance((0, 0), (3, 0)), 3.0)
check("(2,2) 距离 2.828 在射程内", round(S.distance((0, 0), (2, 2)), 3), 2.828)
check("(3,3) 距离 4.243 在射程外", round(S.distance((0, 0), (3, 3)), 3) > 3, True)

# --------------------------------------------------------------------------
print("\n[4] 敌方智力怎么取")
# --------------------------------------------------------------------------
g = scene(gen("谋士", 5, 22, W.P1, 3, 6),
          [gen("敌甲", 20, 5, W.P2, 3, 8), gen("敌乙", 18, 20, W.P2, 3, 8)])
foe, mate = g.generals[1], g.generals[2]
check("同格同伴智力更高 -> 取平均", S.foe_intellect_of(g, foe), 12.5)
mate.intellect = 3
check("同伴智力更低 -> 只算自己", S.foe_intellect_of(g, foe), 5.0)
mate.row, mate.col = 3, 7
check("同伴挪走 -> 只算自己", S.foe_intellect_of(g, foe), 5.0)

g2 = scene(gen("谋士", 5, 22, W.P1, 3, 6), [])
check("劫粮：空场按 10 算", S.foe_intellect_at(g2, (4, 3), W.P1), 10.0)
g2.generals.append(gen("我副将", 8, 20, W.P1, 4, 3))
check("劫粮：只有己方也按 10 算", S.foe_intellect_at(g2, (4, 3), W.P1), 10.0)
g2.generals += [gen("敌甲", 20, 4, W.P2, 4, 3), gen("敌乙", 18, 19, W.P2, 4, 3)]
check("劫粮：取格上敌将最高智力", S.foe_intellect_at(g2, (4, 3), W.P1), 19.0)

# --------------------------------------------------------------------------
print("\n[5] 代价：1 点行动力 + 10 点体力，用出去才结账")
# --------------------------------------------------------------------------
a = gen("谋士", 5, 22, W.P1, 4, 3)
check("够用时可以付", S.cost_ok(a), True)
a.stamina = STRATAGEM_STAMINA_COST
check("体力正好 10 -> 不能付（付完就归零）", S.cost_ok(a), False)
a.stamina = STRATAGEM_STAMINA_COST + 1
check("体力 11 -> 可以付", S.cost_ok(a), True)
a.move_points = 0
check("行动力 0 -> 不能付", S.cost_ok(a), False)

g = scene(gen("谋士", 5, 22, W.P1, 4, 3), [gen("敌甲", 20, 8, W.P2, 5, 1)])
me = g.generals[0]
me.row, me.col, me.intellect = 2, 0, 22          # 天水：唯一一个能跳的地方
g.aim = W.CunningAim(g, me, "sneak")
check("瞄准态收手不扣代价", (g.aim.cancel(), me.move_points, me.stamina), (True, 3, 100))

me.stamina, me.move_points = 100, 3
g.aim = W.CunningAim(g, me, "sneak")
g.rng.random = lambda: 0.99                       # 0.99 > 0.88，必失手
g.aim.handle_click(2, 2)
check("失手也照付代价", (me.move_points, me.stamina), (2, 90))
check("失手后原地不动", me.pos, (2, 0))

# --------------------------------------------------------------------------
print("\n[6] 暗度陈仓：跃过障碍")
# --------------------------------------------------------------------------
g = scene(gen("谋士", 5, 22, W.P1, 2, 0), [gen("敌甲", 20, 8, W.P2, 9, 9)])
me = g.generals[0]
aim = W.CunningAim(g, me, "sneak")
check("天水只能跳到子午谷", sorted(aim.highlight()), [(2, 2)])
check("障碍本身不是落脚点", g.grid[2][1], OBSTACLE)
g.rng.random = lambda: 0.5
aim.handle_click(2, 2)
check("跳过去之后落点对", me.pos, (2, 2))
check("跳一次扣一份代价", (me.move_points, me.stamina), (2, 90))

g2 = scene(gen("谋士", 5, 22, W.P1, 4, 3), [])    # 上庸：四面都没有"障碍+落脚"
check("没有可跃的障碍就没有目标", W.CunningAim(g2, g2.generals[0], "sneak").highlight(), set())

# --------------------------------------------------------------------------
print("\n[7] 劫粮：目标格所有粮搬到脚下")
# --------------------------------------------------------------------------
g = scene(gen("谋士", 5, 22, W.P1, 7, 0), [], {(7, 1): 4, (7, 3): 1})
me = g.generals[0]
aim = W.CunningAim(g, me, "raid")
check("两堆粮都在目标里", sorted(aim.highlight()), [(7, 1), (7, 3)])
check("自己脚下那格不算目标", me.pos in aim.highlight(), False)
g.grain[(7, 0)] = 2
check("脚下有粮也不算目标", sorted(W.CunningAim(g, me, "raid").highlight()), [(7, 1), (7, 3)])
g.rng.random = lambda: 0.1
aim.handle_click(7, 1)
check("粮全搬过来了", g.grain_at(7, 0), 6)
check("原格被搬空", g.grain_at(7, 1), 0)

# --------------------------------------------------------------------------
print("\n[8] 内讧：两名敌将自相残杀一回合，谁都不挪窝")
# --------------------------------------------------------------------------
g = scene(gen("谋士", 5, 22, W.P1, 3, 6),
          [gen("敌甲", 20, 5, W.P2, 3, 7), gen("敌乙", 18, 20, W.P2, 3, 8)])
me, e1, e2 = g.generals
aim = W.CunningAim(g, me, "infight")
# 敌甲智力 5 -> (22-5-8)/8 = 1.125 夹到 1，可点；敌乙智力 20 -> (22-20-8)/8 < 0，
# 虽然边上也有人，但成功率是 0，不摆出来当死路
check("智力差够的那名可点", sorted(aim.highlight()), [(3, 7)])
check("智力差不够的那名不摆出来", S.chance("infight", 22, 20), 0.0)
aim2 = W.CunningAim(g, gen("独夫", 5, 22, W.P1, 9, 5),
                    "infight")
check("边上凑不出第二个人 -> 没目标", sorted(aim2.highlight()), [])

g.rng.random = lambda: 0.1
g.rng.randint = lambda lo, hi: 7                  # 钉死掉血，好算
aim.handle_click(3, 7)
check("进了挑第二个人的阶段", aim.state, "partner")
check("第二个人只能是合肥那边的敌乙", sorted(aim.highlight()), [(3, 8)])
aim.handle_click(3, 8)
check("两边各掉 7 点", (e1.stamina, e2.stamina), (93, 93))
check("内讧期间谁都没挪窝", (e1.pos, e2.pos), ((3, 7), (3, 8)))
check("结算完瞄准态关掉", g.aim, None)

g2 = scene(gen("谋士", 5, 22, W.P1, 3, 6), [gen("敌甲", 20, 5, W.P2, 3, 7)])
e = g2.generals[1]
g2.generals.append(gen("陪葬", 5, 5, W.P2, 3, 8))
e.stamina = 6
g2.aim = W.CunningAim(g2, g2.generals[0], "infight")
g2.rng.random = lambda: 0.1
g2.rng.randint = lambda lo, hi: 20                # 一下打死
g2.aim.handle_click(3, 7)
g2.aim.handle_click(3, 8)
check("内讧能打死人", e.alive, False)

# --------------------------------------------------------------------------
print("\n[9] 调虎离山：牵着他走，不看他的移动力")
# --------------------------------------------------------------------------
g = scene(gen("谋士", 5, 22, W.P1, 4, 3), [gen("敌甲", 20, 8, W.P2, 5, 1)])
me, foe = g.generals
foe.move_points = 0                               # 他自己这回合已经走完了
aim = W.CunningAim(g, me, "lure")
check("射程内可点", sorted(aim.highlight()), [(5, 1)])
g.rng.random = lambda: 0.1
g.rng.randint = lambda lo, hi: 2                  # 这次能调 2 格
aim.handle_click(5, 1)
check("掷出 2 格", aim.steps, 2)
check("进了挑落脚点的阶段", aim.state, "lure")
dests = aim.options
check("落脚点都在 2 格以内", max(dests.values()) <= 2, True)
check("不会把他调到他原来那格", foe.pos in dests, False)
foe.move_points = 0
dest = sorted(dests, key=lambda c: dests[c])[0]
aim.handle_click(*dest)
check("人确实被挪走了", foe.pos, dest)
check("被牵走不看他自己的移动力", foe.move_points, 0)

g2 = scene(gen("谋士", 5, 22, W.P1, 4, 3), [gen("敌甲", 12, 8, W.P2, 5, 1)])
foe2 = g2.generals[1]
check("智力差 14 -> 上限 6", S.lure_move_cap(22, 8), 6)
check("2 格以内的落脚点非空", len(S.lure_dests(g2, foe2, 2)) > 0, True)
check("掷出 0 格就无处可去", S.lure_dests(g2, foe2, 0), {})

# --------------------------------------------------------------------------
print("\n[10] 界面上能不能开")
# --------------------------------------------------------------------------
g = scene(gen("谋士", 5, 22, W.P1, 4, 3), [gen("敌甲", 20, 8, W.P2, 5, 1)])
me = g.generals[0]
check("都够时能开", W.cunning_block_reason(me), None)
me.stamina = STRATAGEM_STAMINA_COST
check("体力不够时报原因", "体力不够" in W.cunning_block_reason(me), True)
me.stamina = 100
me.move_points = 0
check("行动力不够时报原因", "行动力不够" in W.cunning_block_reason(me), True)
me.move_points = 3
g.selected = None
check("没选武将时不开", W.cunning_block_reason(None), "先选一名己方武将")

# --------------------------------------------------------------------------
print("\n[11] 绘制自检（dummy 显卡）")
# --------------------------------------------------------------------------
pygame.init()
screen = pygame.display.set_mode((WIN_W, WIN_H))
buttons = W.make_buttons()
g = scene(gen("诸葛亮", 5, 22, W.P1, 4, 3),
          [gen("张辽", 20, 8, W.P2, 5, 1), gen("徐晃", 18, 20, W.P2, 5, 1)])
g.grain = {(7, 1): 3}
g.selected = g.generals[0]
for key in ("sneak", "lure", "infight", "raid"):
    g.aim = W.CunningAim(g, g.generals[0], key)
    g.draw(screen, (0, 0), buttons)
g.aim = None
g.open_cunning()
g.draw(screen, (0, 0), buttons)
check("弹窗 + 四种瞄准态都能画出来", g.cunning is not None, True)


def painted(r, c):
    """这一格中心被计谋色染过吗（紫：蓝比红绿都高）。"""
    p = screen.get_at((MARGIN + c * CELL + CELL // 2, MARGIN + r * CELL + CELL // 2))
    return p[2] > p[0] + 8 and p[2] > p[1] + 8


g.cunning = None
g.aim = W.CunningAim(g, g.generals[0], "lure")
g.draw(screen, (0, 0), buttons)
check("棋盘上只高亮该高亮的那格", [(r, c) for r in range(10) for c in range(10)
                                    if painted(r, c)], sorted(g.aim.highlight()))

# --------------------------------------------------------------------------
print()
if FAILS:
    print(f"✘ 有 {len(FAILS)} 项没过：")
    for label in FAILS:
        print("   -", label)
    sys.exit(1)
print("✔ 全部通过")
