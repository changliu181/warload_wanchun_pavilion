# -*- coding: utf-8 -*-
"""电脑对手（1P 模式）：棋盘走位 + 交战屏决策。

从 warlords.py 拆出。所有函数都只读 game / battle 的公开状态，不 import 它们，
所以不依赖 pygame，可以脱离图形环境单独测试。
"""
import itertools
import math

from constants import (
    AI_ATTACK_EDGE, AI_CITY_SCORE, AI_DANGER_SCORE, AI_EAT_BELOW, AI_GRAIN_CARRY,
    AI_GRAIN_SCORE, AI_RETREAT_EDGE, AI_STEP_FRAMES, AI_THREAT_SCORE, CITY, GRAIN_HEAL,
    LOSS_MAX_PER_MIGHT,
)

# 电脑不偷看未来，只用**当前局面**能算出来的东西做判断，分两层：
#
#   棋盘上（ai_map_step）：能打且划得来的仗就打，带伤又站在粮上就吃粮，
#                          否则走位（顺路把粮草带走），实在没正经事做就结束回合。
#   交战屏（ai_battle_step）：替电脑那一方按"继续 / 撤退 / 往哪撤 / 谁先出阵"的按钮。
#
# 判断"这仗划不划得来"用的是**期望值**，不是真跑一遍随机数：
# 每回合掉多少体力是 [1, LOSS_MAX_PER_MIGHT * 对方武力] 里的均匀随机数，
# 所以平均值就是 0.5 + 对方武力。拿"我能撑几回合"和"对方能撑几回合"一比，
# 谁的数字大谁后倒——双方同时掉血，后倒的就是赢家。
#
# 这套判断偏保守：强攻时假设守方**死战不退**（真的打起来守方多半会先撤，
# 所以实际代价通常比估算的小），撤退判断则要求"能比对方明显后倒"才继续缠斗。

def average_damage(might):
    """每回合平均打掉对方多少体力：[1, LOSS_MAX_PER_MIGHT * might] 的均值。"""
    return 0.5 + LOSS_MAX_PER_MIGHT * might / 2


def rounds_to_fall(stamina, foe_might):
    """这点体力在对方手里还能撑几回合（除以每回合平均挨的打）。"""
    return stamina / average_damage(foe_might)


def outlasts_stats(my_stamina, my_might, foe, edge=1.0):
    """这点体力对拼下去，我是不是比 foe 后倒（edge > 1 要求赢得更明显）。"""
    return rounds_to_fall(my_stamina, foe.might) > rounds_to_fall(foe.stamina, my_might) * edge


def outlasts(me, foe, edge=1.0):
    """我是不是耗得过 foe。"""
    return outlasts_stats(me.stamina, me.might, foe, edge)


def duel_survivors(gen, defenders):
    """强攻这一格的预计结果：打完我还剩多少体力；打不赢就是负数。

    守方会一个个上，顺序由守方定，所以按**对我最不利**的顺序算。
    每一位守将只看一件事：只要我比对方后倒，就是我把对方逼退——
    守方打不赢会自己撤（撤退规则见 Battle），我不需要真把他打到 0 体力，
    只需付出"打光他所需的回合数"那么多代价。哪一位我耗不过，这仗就算了。
    """
    worst = None
    for order in itertools.permutations(defenders):
        left = gen.stamina
        for foe in order:
            if not outlasts_stats(left, gen.might, foe, AI_ATTACK_EDGE):
                left = -1.0                            # 耗不过，强攻到此为止
                break
            rounds = math.ceil(foe.stamina / average_damage(gen.might))
            left -= rounds * average_damage(foe.might)
        worst = left if worst is None else min(worst, left)
    return worst


def cell_appeal(game, gen, cell):
    """走位时给每个能停的格子打分：占城加分，贴敌人分两种（打得过 / 打不过），有粮加分。

    粮草只有带伤时才加分——满血的武将没必要为了粮草挪窝；带伤的往粮上走，
    下几步就能吃上（吃粮在 ai_map_step 的第 2 步）。
    """
    row, col = cell
    score = AI_CITY_SCORE if game.grid[row][col] == CITY else 0
    if gen.stamina < gen.stamina_cap * AI_EAT_BELOW:
        score += AI_GRAIN_SCORE if game.grain_at(row, col) else 0
    foes = [g for g in game.generals if g.alive and g.owner != gen.owner]
    if not foes:
        return score
    near = [(abs(g.row - row) + abs(g.col - col), g) for g in foes]
    score += max(0, 4 - min(d for d, _g in near))       # 离敌人越近越有威胁
    for dist, foe in near:
        if dist == 1:                                    # 贴上去：能冲锋 / 白挨打
            score += AI_THREAT_SCORE if outlasts(gen, foe) else AI_DANGER_SCORE
    return score


def ai_map_step(game):
    """电脑在棋盘上走一步：能打就打，带伤就吃粮，其次走位，没事干就结束回合。

    每走一步都真的花掉移动力（或结束回合），所以一回合内必然收敛，不会卡住。
    """
    player = game.current
    mine = [g for g in game.generals if g.alive and g.owner == player and not g.exhausted]

    # 1) 划算的进攻：估算下来耗得过对方、且这一格打光之后我还在，就打
    charges = []
    for gen in mine:
        for cell in game.compute_attackable(gen):
            defenders = game.generals_at(*cell)
            left = duel_survivors(gen, defenders)
            if left > 0:
                charges.append((left, gen.name, cell, gen))
    if charges:
        charges.sort(key=lambda t: (-t[0], t[1], t[2]))   # 打完剩得最多、再按名字和坐标定序
        gen, cell = charges[0][3], charges[0][2]
        game.charge(gen, *cell)
        return

    # 2) 吃粮：带伤又站在粮上，先吃一口再干别的
    #    伤得最重的先吃；吃的量按体力缺口算，夹在"这一口能吃到的范围"里（不至于吃过头）。
    #    吃 k 石要花 k 点移动力，所以吃完这回合可能就走不动了。
    hungry = [gen for gen in mine
              if gen.stamina < gen.stamina_cap * AI_EAT_BELOW and game.eat_amounts(gen)]
    if hungry:
        hungry.sort(key=lambda gen: (gen.stamina / gen.stamina_cap, gen.name))
        gen = hungry[0]
        options = game.eat_amounts(gen)                   # [1..n]，n 受粮草和移动力限制
        want = math.ceil((gen.stamina_cap - gen.stamina) / GRAIN_HEAL)
        game.eat_grain(gen, max(options[0], min(want, options[-1])))
        return

    # 3) 走位：挑全场最顺眼的落脚点（顺手选中，让人看得见是谁在动）
    best = None
    for gen in mine:
        for cell in game.compute_reachable(gen):
            score = cell_appeal(game, gen, cell)
            if best is None or score > best[0]:
                best = (score, gen, cell)
    if best is not None and best[0] > 0:
        gen, cell = best[1], best[2]
        game.select(gen)
        # 顺路搬粮。注意搬运的净效果是"把粮从出发格挪到落点格"，不是背在自己身上
        # （见 Game.walk），所以不能见粮就搬——那会把城池的存粮一路拖散在野地里。
        # 只在两种情况下搬：自己带着伤（落到地方正好就地吃）、或者要进城（入库囤起来）。
        # 显式传 carry：电脑不走"问玩家带多少"那条路（见 Game.move）。
        carry = 0
        if gen.stamina < gen.stamina_cap * AI_EAT_BELOW or game.grid[cell[0]][cell[1]] == CITY:
            carry = AI_GRAIN_CARRY
        game.move(gen, *cell, carry=carry)
        return

    # 4) 没事可做：收工，把回合交给对方
    game.end_turn()


def ai_pick_defender(battle):
    """守方挑谁先出阵 -> 下标。

    把两种出场顺序各推演一遍：攻方一个个打过来，守将被打光就算损失，
    挑"我方最后剩得最多"的那种顺序。推演里假设双方都死战不退；
    打平就沿用守将原本的站位顺序，保证同样的局面电脑的选择是确定的。
    """
    best, best_left = 0, None
    for i in range(len(battle.defenders)):
        first = battle.defenders[i]
        order = [first] + [g for g in battle.defenders if g is not first]
        atk_left = battle.atk.stamina
        our_left = sum(g.stamina for g in battle.defenders)
        for foe in order:
            rounds = math.ceil(foe.stamina / average_damage(battle.atk.might))
            atk_left -= rounds * average_damage(foe.might)
            our_left -= foe.stamina                   # 这位守将被打光（阵亡或被迫撤走）
            if atk_left <= 0:                         # 攻方先倒，后面的守将不用上了
                break
        if best_left is None or our_left > best_left:
            best, best_left = i, our_left
    return best


def ai_should_continue(battle, gen):
    """电脑这一方要不要继续缠斗；不划算就撤（撤退权另算，没退路时只能接着打）。"""
    return outlasts(gen, battle.foe_of(gen), AI_RETREAT_EDGE)


def ai_pick_retreat(battle):
    """守方往哪撤 -> retreat_choices 里的下标。

    先看安全（别撤到敌人嘴边，尤其别贴着武力高的），再看是不是城池（能多回血），
    最后才比代价（少退一格就少欠一点下回合的行动力）。
    """
    game = battle.game
    best, best_score = 0, None
    for i, (dest, steps) in enumerate(battle.retreat_choices):
        row, col = dest
        score = -2 * steps                                   # 退得越远欠得越多
        if game.grid[row][col] == CITY:
            score += AI_CITY_SCORE
        for foe in game.generals:
            if not foe.alive or foe.owner == battle.dfd.owner:
                continue
            dist = abs(foe.row - row) + abs(foe.col - col)
            if dist == 1:
                score -= 4 + foe.might                       # 撤到强敌旁边，等于白撤
            elif dist == 2:
                score -= 1
        if best_score is None or score > best_score:
            best, best_score = i, score
    return best


def ai_battle_step(battle):
    """电脑在交战屏上做一步决定；轮不到它或正在放动画时就什么都不做。"""
    game = battle.game
    if battle.state == battle.PICK_DEFENDER:
        if game.is_ai(battle.defenders[0].owner):
            battle.pick_defender(ai_pick_defender(battle))
    elif battle.state == battle.READY:
        if game.is_ai(battle.atk.owner):
            battle.act("roll")
    elif battle.state in (battle.CHOOSE_ATK, battle.CHOOSE_DFD):
        who = battle.chooser
        if not game.is_ai(who.owner):
            return
        if ai_should_continue(battle, who):
            battle.act("hold")
        elif battle.can_retreat():
            battle.act("atk_retreat" if who is battle.atk else "dfd_retreat")
        else:
            battle.act("hold")                  # 没退路，只能接着缠斗
    elif battle.state == battle.RETREAT_PICK:
        if game.is_ai(battle.dfd.owner):
            battle.act(f"retreat:{ai_pick_retreat(battle)}")
    elif battle.state == battle.OVER and game.is_ai(battle.atk.owner):
        battle.act("close")                     # 电脑自己打完的，自己收场


def ai_pump(game):
    """电脑的驱动器：每 AI_STEP_FRAMES 帧走一步，让人类看得清它在干什么。

    棋盘和交战屏共用这一个节拍器——交战屏多半也是电脑回合里打起来的。
    """
    if game.ai_timer > 0:
        game.ai_timer -= 1
        return
    game.ai_timer = AI_STEP_FRAMES
    if game.over:
        return
    if game.battle is not None:
        ai_battle_step(game.battle)
    elif game.is_ai():
        ai_map_step(game)
