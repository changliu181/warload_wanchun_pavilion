# -*- coding: utf-8 -*-
"""电脑对手（1P 模式）：棋盘走位 + 交战屏决策。

从 warlords.py 拆出。所有函数都只读 game / battle 的公开状态，不 import 它们，
所以不依赖 pygame，可以脱离图形环境单独测试。

## 这一版的思路：一切换算成"分数"

这一版把电脑的判断全部换成**同一套货币：分**——就是侧边栏比分板上那一套
（将领分 = 每名存活武将的 (100+体力)×武力；地盘分 = 每格地形分 + 格上粮草分）。
理由有两条：

* 分数是这局游戏里唯一有定义的目标函数（回合用尽就是比它），拿它当评估函数，
  电脑"这一手赚不赚"的判断和玩家看到的比分永远一致，不用再靠一堆拍出来的常数；
* 它天生包含"打死对方一名武将 = 对方掉一大块"——一个满血武力 21 的武将值 4200 分，
  比一座城池还贵。所以**歼灭**这个目的不需要另外写死，它自己就是最赚的一手。

不过分数是"此刻的账面"，它看不见两件更要紧的事，所以电脑在账面之外另算两项：

* **死人不会再回来**：歼灭的价值要在账面之上再放大（AI_KILL_WORTH）。账面上杀掉他
  只是他掉一次分；实际上他还少了一个能一直赚分、能守土的子。
* **阵亡是断崖**：掉体力是线性掉分（(100+体力)×武力），掉光却是整名武将消失，
  所以"站在刀口下的风险"要按身价折算（AI_DEATH_WORTH），而不是只看这回合会掉多少体力。

## 这一版学会的战术

* **逼退也是赢**：守将赢不下这场又会撤（活命 > 守格），所以能打赢的仗代价往往只有
  "第一场必须挨的那一回合"，比按"死战到底"估算便宜得多——这是它比上一版敢打的原因。
  而且守方会**真的挪窝**：地盘按"谁的行动距离更近"算，逼退一格，后面一串格子就跟着易主，
  所以"推进"在它眼里是能算成分的。
* **围而歼之**：守将**退无可退**（被我方堵住、或这回合撤退额度用完）就只能死战，
  这是本作唯一的歼灭入口。电脑会数对方还剩几个落脚点，也会主动去堵那几格。
* **抱团**：走位时按"谁离我方前线最近"挑一个共同目标，全军朝那儿压；身边有能打赢对方的
  队友时，对方的威胁就不算数——各自找最近的敌人只会把兵力摊开，两格堆两个人互相瞪眼，
  局面就冻住了。
* **吃饱再打**：吃一口粮能把"打不赢"变成"打得赢"，就先吃——吃粮和打仗用同一套分数，
  可以直接比大小，所以"吃一口救命的粮"能排在"打一场无关痛痒的仗"前面。
* **便宜的换贵重的**：守将被磨到拼不过攻方时，如果死战能把攻方磨薄到后面的守将接得住，
  那这一位就该顶住不撤（值不值由这一格和磨损跟他这条命比出来）。

## 它不会什么

它**只看一步**：把候选走法摆出来、按计分板算一遍分，挑最高的，下一步重新评估。
一步之内连着打几仗是靠"每步都重算"自然串起来的（所以会出现"第一个先磨、第二个补刀"），
但跨回合的长期计划（比如"这城池里堆着两名守将，我先磨三回合再总攻"）它看不到——
碰上死守不出的对手，它多半是把对方围在城里、靠地盘分赢下来，而不是硬啃。
"""

import itertools
import math
from collections import deque, namedtuple

from config import neighbors
from constants import (
    AI_CITY_PULL, AI_DEATH_WORTH, AI_DEBT_WORTH, AI_EAT_BELOW, AI_GRAIN_CARRY,
    AI_GRAIN_PULL, AI_IDLE_PENALTY, AI_KILL_WORTH, AI_LOOKAHEAD, AI_SIEGE_WORTH,
    AI_STEP_FRAMES, AI_TAKE_EDGE, AI_THREAT_WORTH, CITY, CITY_DEFENSE_MULT, GRAIN_HEAL,
    LOSS_MAX_PER_MIGHT, P1, P2, REGEN, RETREAT_MAX, SCORE_GENERAL_BASE, SCORE_GRAIN,
    SCORE_TERRAIN,
)

# --------------------------------------------------------------------------
# 一、通用货币：分数
# --------------------------------------------------------------------------
def general_value(gen):
    """一名武将的身价 = 他为本方贡献的将领分：(100 + 体力) × 武力。

    这也是"打死他"能让对方掉多少分。歼灭之所以值钱，就是因为这一项整个消失，
    而不是像掉体力那样一点点缩水。
    """
    return (SCORE_GENERAL_BASE + max(0, gen.stamina)) * gen.might


def cell_value(game, cell):
    """一格地值多少分：地形分（通路 200 / 城池 3000）+ 格上粮草每石 150。"""
    row, col = cell
    return SCORE_TERRAIN[game.grid[row][col]] + SCORE_GRAIN * game.grain_at(row, col)


# --------------------------------------------------------------------------
# 二、单挑与强攻的推演（不掷骰子，只用平均伤害）
# --------------------------------------------------------------------------
def average_damage(might):
    """每回合平均打掉对方多少体力：[1, LOSS_MAX_PER_MIGHT * might] 的均值。"""
    return 0.5 + LOSS_MAX_PER_MIGHT * might / 2


def rounds_to_drop(stamina, might):
    """按平均伤害算，把 stamina 点体力打光要几回合（向上取整，至少 1）。"""
    return max(1, math.ceil(stamina / average_damage(might)))


def duel_race(my_stamina, my_might, foe_stamina, foe_might):
    """双方死战不退的赛跑 -> (我几回合打光他, 他几回合打光我)。

    这两个数一比就是单挑的结论：我小就是我赢；打平就是同归于尽；我大就是我拼不过。
    """
    return (rounds_to_drop(foe_stamina, my_might),
            rounds_to_drop(my_stamina, foe_might))


def wins_duel(my_stamina, my_might, foe_stamina, foe_might):
    """双方死战不退的话，我是不是先把他打倒（同时倒算没赢）。"""
    mine, theirs = duel_race(my_stamina, my_might, foe_stamina, foe_might)
    return mine < theirs


def _defender_stamina(game, gen, cell):
    """守城加成：守方在城池里开打，体力先 ×CITY_DEFENSE_MULT（四舍五入）。

    交战界面上守军的体力**已经**抬过一次（General.apply_city_boost），所以这里看
    city_boost 认一下，别重复加成。
    """
    if game.grid[cell[0]][cell[1]] == CITY and not gen.city_boost:
        return int(math.floor(gen.stamina * CITY_DEFENSE_MULT + 0.5))
    return gen.stamina


def _after_battle_stamina(game, gen, cell, stamina):
    """打完把守城加成压回去（和 General.drop_city_boost 同一套取整），夹回上限。"""
    if game.grid[cell[0]][cell[1]] == CITY:
        stamina = int(math.floor(stamina / CITY_DEFENSE_MULT + 0.5))
    return max(0, min(gen.max_stamina, stamina))


def escape_routes(game, gen, threat_from, cell=None):
    """gen 被 threat_from 那一格上的敌人逼住时，还有几个落脚点可退（0 = 退无可退）。

    复刻 Battle.retreat_paths 的那几条规矩：第一步不能迎着威胁来的方向（那是朝刀口上撞）；
    中途每格都得过得去（敌方挡路）；落脚那格还得停得下；总数还受"这一回合还剩多少
    撤退额度"限制（RETREAT_MAX 与 gen.retreat_room 取小）。

    返回落脚点个数。**0 就是被围死了**——守将退无可退只能死战，这是歼灭的入口，
    所以这个数在下面被反复用到。
    """
    cell = gen.pos if cell is None else cell
    limit = min(RETREAT_MAX, gen.retreat_room)
    if limit <= 0:
        return 0
    came = ((threat_from[0] > cell[0]) - (threat_from[0] < cell[0]),
            (threat_from[1] > cell[1]) - (threat_from[1] < cell[1]))
    seen = {cell}
    found = 0
    q = deque([(cell[0], cell[1], 0)])
    while q:
        r, c, d = q.popleft()
        if d >= limit:
            continue
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if d == 0 and (dr, dc) == came:
                continue
            step = (r + dr, c + dc)
            if step in seen or not game.can_transit(gen, *step):
                continue
            seen.add(step)
            if game.can_stop(gen, *step):
                found += 1
            q.append((step[0], step[1], d + 1))
    return found


def retreat_spot(game, gen, threat_from, cell=None):
    """守将被逼退之后会落在哪（落脚点由守方自己挑）。

    他**最想少欠行动力**（退得越远，下回合越迈不开腿），所以先挑步数最少的，
    步数一样再挑离威胁最远的。这样估出来"逼退能拿走多少地"是保守的：
    他退一格就只让出一格，后面那条走廊多半还是争夺中——而那本来就是实情。

    这事看着小，其实是**推进的实质**：地盘是按"谁的行动距离更近"算的，
    把守将逼走，所属就会跟着变，所以模型里必须让他真的挪窝。
    """
    cell = gen.pos if cell is None else cell
    limit = min(RETREAT_MAX, gen.retreat_room)
    if limit <= 0:
        return None
    came = ((threat_from[0] > cell[0]) - (threat_from[0] < cell[0]),
            (threat_from[1] > cell[1]) - (threat_from[1] < cell[1]))
    seen = {cell}
    best, best_score = None, None
    q = deque([(cell[0], cell[1], 0)])
    while q:
        r, c, d = q.popleft()
        if d >= limit:
            continue
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if d == 0 and (dr, dc) == came:
                continue
            step = (r + dr, c + dc)
            if step in seen or not game.can_transit(gen, *step):
                continue
            seen.add(step)
            if game.can_stop(gen, *step):
                gap = max(abs(threat_from[0] - step[0]), abs(threat_from[1] - step[1]))
                score = (-d, gap)
                if best_score is None or score > best_score:
                    best, best_score = step, score
            q.append((step[0], step[1], d + 1))
    return best


class _Snapshot:
    """临时把局面改一改再算分用的存档；算完**必须**原样还回去。

    推演回答的是"如果这样走会怎样"，所以真实局面（位置、体力、死活、粮草）不能被弄脏。
    """

    def __init__(self, game):
        self.game = game
        self.saved = [(g, g.row, g.col, g.stamina, g.alive) for g in game.generals]
        self.grain = dict(game.grain)

    def restore(self):
        for gen, row, col, stamina, alive in self.saved:
            gen.row, gen.col, gen.stamina, gen.alive = row, col, stamina, alive
        self.game.grain.clear()
        self.game.grain.update(self.grain)


# 一次强攻的推演结果。score 是换算好的分数，正数才值得打。
Assault = namedtuple("Assault", "score gen cell kills driven taken cost rounds")


def defender_stands_firm(game, dfd, atk, cell, mates=()):
    """守将 dfd 被 atk 逼到这一步时，是**死战不退**（True）还是撤（False）。

    这是 ai_should_continue 里守方那一支，抽出来给攻方的推演共用——两边必须用同一套
    判断。攻方要是自作主张假设"守方打不过就会撤"，碰上守方宁可死战的情形就会把代价
    算少，而且是往乐观的方向算少。

    撤退 = 保住这条命、把格子让出去；死战 = 拿命换"守住这一格"或"把攻方磨薄给后面的
    守将接手"。所以它要决断的就一件事：**这一格加上多磨掉的那些体力，够不够抵他这条命**。
    模型的"打平"在真打起来是掷骰子，所以按对半开算。
    """
    mine, theirs = duel_race(_defender_stamina(game, dfd, cell), dfd.might,
                             atk.stamina, atk.might)
    if mine < theirs:
        return True                           # 守方赢得下这场，顶住就守住了
    if escape_routes(game, dfd, threat_from=atk.pos, cell=cell) == 0:
        return True                           # 退无可退，只能死战
    if mine > theirs:                         # 打不过（不是打平）
        worn_after = atk.stamina - mine * average_damage(dfd.might)
        if not (mates and worn_after > 0
                and wins_duel(mates[0].stamina, mates[0].might, worn_after, atk.might)):
            return False                      # 后面没人接得住，那这条命是白搭
    worth = cell_value(game, cell) + (mine - 1) * average_damage(dfd.might) * atk.might
    return worth * (0.5 if mine == theirs else 1.0) > general_value(dfd)


def _resolve_assault(game, gen, cell, order):
    """按给定的守将出场顺序把一次强攻走完。

    返回 (打死谁, 逼退谁, 拿没拿到格子, 我还剩多少体力, 总回合数, 我是否也倒下)。
    守方的应对走 defender_stands_firm，也就是他真打起来会用的那套判断：
      * 他顶得住 —— 我啃不动，这一仗到此为止；
      * 他撤 —— 我付一回合（第一位必须挨的那下；第二场起他连开打前都能走，就不付了）；
      * 他死战 —— 他输就是被**歼灭**，打平就是同归于尽（那是拿我的命换他的命）。
    """
    stamina = gen.stamina
    kills, driven = [], []                       # driven: [(守将, 他掉了多少体力)]
    rounds_total = 0
    for i, dfd in enumerate(order):
        foe_stamina = _defender_stamina(game, dfd, cell)
        mine, theirs = duel_race(stamina, gen.might, foe_stamina, dfd.might)
        if mine > theirs:
            return kills, driven, False, stamina, rounds_total, False     # 拼不过，收手
        mates = list(order[i + 1:])              # 还没上场的守将（守方可以替他铺路）
        if defender_stands_firm(game, dfd, gen, cell, mates=mates):
            rounds = mine
            stamina -= rounds * average_damage(dfd.might)
            kills.append(dfd)
            if mine == theirs:                   # 同归于尽
                return kills, driven, False, stamina, rounds_total + rounds, True
        else:
            rounds = 1 if i == 0 else 0          # 他撤；第一位必须应战一回合
            stamina -= rounds * average_damage(dfd.might)
            driven.append((dfd, min(foe_stamina, rounds * average_damage(gen.might))))
        rounds_total += rounds
    return kills, driven, True, stamina, rounds_total, False


def _assault_score(game, board, gen, cell, kills, driven, taken, stamina_left, died):
    """把这次强攻换算成分数：先按计分板算账面变化，再补两条账面看不见的。

    账面变化是**真的改一遍局面算出来的**（体力、死活、谁站在哪都会影响将领分和地盘分），
    算完原样还回去。补的那两条是"死人不会再回来"（歼灭加成）和"下场也是死"（阵亡代价）。
    """
    before = game.scoreboard()[0]
    origin = gen.pos                              # 攻方是从哪一格打过来的（结算前先记下）
    snap = _Snapshot(game)
    try:
        # 守军的去向先落定，再让攻方进占（顺序反了的话退路会被自己挡住）
        for dfd, dealt in driven:
            left = _defender_stamina(game, dfd, cell) - dealt
            dfd.stamina = _after_battle_stamina(game, dfd, cell, left)
            spot = retreat_spot(game, dfd, threat_from=origin, cell=cell)
            if spot is not None:                  # 被逼退 = 往后挪窝，这一步很值钱
                dfd.row, dfd.col = spot
        for dfd in kills:
            dfd.stamina, dfd.alive = 0, False
        gen.stamina = max(0, stamina_left)
        if died:
            gen.alive = False
        if taken:
            gen.row, gen.col = cell
        now = game.scoreboard()[0]
        profit = now[gen.owner][0] - now[1 - gen.owner][0]
        if taken and not died:
            # 进占了这一格，那就得算"下一步站在敌人的地盘上会不会被反吃"。
            # 没拿到格子的那种（只是磨了他一回合）位置没变，威胁是本来就有的，
            # 不该记在这一仗头上，否则会把它吓得连磨都不敢磨。
            gone = tuple(kills) + tuple(dfd for dfd, _dealt in driven)
            profit -= threat_penalty(game, board, gen, gen.pos, ignore=gone)
    finally:
        snap.restore()
    extra = (AI_KILL_WORTH - 1) * sum(general_value(dfd) for dfd in kills)
    if died:
        extra -= AI_DEATH_WORTH * general_value(gen)
    return profit - (before[gen.owner][0] - before[1 - gen.owner][0]) + extra


def plan_assault(game, board, gen, cell):
    """推演 gen 从现在的格子踏进 cell 强攻值多少分 -> Assault；没敌人可打就是 None。

    守方最多两名，出场顺序由守方定，所以按**对我最不利**的那个顺序结算
    （他一定把最难啃的排前面）。
    """
    defenders = [g for g in game.generals_at(*cell) if g.owner != gen.owner]
    if not defenders or gen.exhausted:
        return None
    plans = []
    for order in itertools.permutations(defenders):
        kills, driven, taken, left, rounds, died = _resolve_assault(game, gen, cell, order)
        plans.append(Assault(
            _assault_score(game, board, gen, cell, kills, driven, taken, left, died),
            gen, cell, tuple(kills), tuple(dfd for dfd, _dealt in driven), taken,
            gen.stamina - left, rounds))
    return min(plans, key=lambda plan: plan.score)


# --------------------------------------------------------------------------
# 三、一步之内反复要用的局面缓存
# --------------------------------------------------------------------------
class Board:
    """一步之内反复要用的局面缓存。

    每走一步都要重算（局面变了），但**一步之内**的所有候选评估都复用同一份：
    这样"某个敌人这一回合能不能打到我"就只是一次查表，而不是每次现做一遍 BFS。
    """

    def __init__(self, game):
        self.game = game
        self.reach = {}                      # 武将 -> {落脚格: 步数}（原地记 0 步）
        self.garrison = {}                   # 格子 -> [活着的武将]
        for gen in game.generals:
            if not gen.alive:
                continue
            self.garrison.setdefault(gen.pos, []).append(gen)
            self.reach[gen] = dict(game.compute_reachable(gen))
            self.reach[gen][gen.pos] = 0
        # 地盘归属：谁的行动距离更近，那格就算谁的（和计分板同一套判定）
        self.field = {player: game.distance_field(player) for player in (P1, P2)}
        # 全军这一轮盯着谁打（见 focus_target）
        self.focus = {player: focus_target(self, player) for player in (P1, P2)}

    def focus_gap(self, player, cell):
        """cell 离"我方这一轮盯着的目标"还差几格；没有目标就是 0。"""
        target = self.focus[player]
        if target is None:
            return 0
        return max(abs(target.row - cell[0]), abs(target.col - cell[1]))

    def owner_of(self, cell):
        """这一格现在归谁：距离更近的那一方；一样近或都到不了就是争夺中 -> None。"""
        d1, d2 = self.field[P1].get(cell), self.field[P2].get(cell)
        if d1 is None and d2 is None:
            return None
        if d1 is None:
            return P2
        if d2 is None:
            return P1
        return P1 if d1 < d2 else (P2 if d2 < d1 else None)


def focus_target(board, player):
    """全军这一轮盯着谁打 -> 敌方武将（挑最靠近我方前线的那位，同距离挑便宜的）。

    为什么要有这个东西：让每个人各自朝"离自己最近的敌人"走，兵力就摊开了——
    两格堆两个人互相瞪眼、谁也打不下谁，局面就冻住了。**盯着同一个目标**压过去，
    才凑得出局部优势（2 打 1），也才有围住人、逼人死战的机会。
    """
    mine = [g for g in board.reach if g.owner == player]
    foes = [g for g in board.reach if g.owner != player]
    if not mine or not foes:
        return None
    best, best_score = None, None
    for foe in foes:
        gap = min(max(abs(g.row - foe.row), abs(g.col - foe.col)) for g in mine)
        # 先看远近（每一格都算数），再看值不值得打（便宜的优先，打残的更优先）
        score = -gap * 10 - general_value(foe) / 100.0
        if best_score is None or score > best_score:
            best, best_score = foe, score
    return best


# --------------------------------------------------------------------------
# 四、威胁与猎物：走位时最要紧的两件事
# --------------------------------------------------------------------------
def can_strike(board, gen, cell):
    """gen 这一回合能不能踏进 cell 跟人开打：先走到隔壁，再花 1 点移动力冲进去。"""
    if gen.exhausted:
        return False
    if gen.pos in tuple(neighbors(*cell)):        # 已经贴着了，原地就能冲
        return True
    return any(board.reach[gen].get(nb, 99) < gen.move_points for nb in neighbors(*cell))


def strikers(board, cell, owner):
    """这一回合能踏进 cell 开打的 owner 方武将 -> [武将]。"""
    return [gen for gen in board.reach
            if gen.owner == owner and can_strike(board, gen, cell)]


def foes_around(board, cell, owner):
    """贴着 cell 的敌方格上站着谁（用于"贴上去能打谁 / 能围住谁"）。"""
    out = []
    for nb in neighbors(*cell):
        for gen in board.garrison.get(nb, ()):
            if gen.owner != owner:
                out.append(gen)
    return out


def threat_penalty(game, board, gen, cell, ignore=()):
    """设想 gen 站在 cell，下回合挨吃的风险 -> 折算成分数惩罚。

    只看"这一步能打到我、而且对拼耗得过我、而且我方没人能反手打回去"的敌人
    （最后一个条件是**互相照应**：身边有能打赢他的队友，他就不敢来）。
    后果分两档，差一个量级：
      * 我退得掉：只是掉点体力（按一回合的必挨伤害算，乘武力换成分数）；
      * 我退无可退、或者来的人比我逃跑的落脚点还多：这名武将可能就没了。
        被吃掉的概率按"来的人比我退路多出几成"算，再乘身价重罚——旷野里落脚点多，
        这一项基本是 0（可以边打边退），真正致命的是关隘里被堵住。
    """
    owner = 1 - gen.owner
    threats = [f for f in strikers(board, cell, owner)
               if f not in ignore
               and wins_duel(f.stamina, f.might, _defender_stamina(game, gen, cell), gen.might)
               and not _can_be_punished(game, board, gen, owner, f)]
    if not threats:
        return 0.0
    penalty = average_damage(threats[0].might) * gen.might       # 第一回合必挨的那一下
    escapes = escape_routes(game, gen, threat_from=threats[0].pos, cell=cell)
    cornered = max(0, len(threats) - escapes) / len(threats)
    return penalty + cornered * AI_THREAT_WORTH * general_value(gen)


def _can_be_punished(game, board, gen, owner, foe):
    """foe 想动 gen，我方有没有人能反手打到 foe 身上（有人能，foe 就不算威胁）。

    这就是"抱团"的收益：两三个人凑在一起，单枪匹马的敌人不敢先动手。
    """
    for mate in board.reach:
        if mate is gen or mate.owner != owner or not mate.alive:
            continue
        if (wins_duel(mate.stamina, mate.might,
                      _defender_stamina(game, foe, foe.pos), foe.might)
                and can_strike(board, mate, foe.pos)):
            return True
    return False


def siege_bonus(game, board, gen, cell, ignore=()):
    """我站在 cell 上堵断了谁的路 -> 值多少分。

    敌人退无可退就只能死战，下一次开打就是**歼灭**。这是铺垫而不是已经到嘴的肉，
    所以按那名敌将身价的 AI_SIEGE_WORTH 计入。
    """
    total = 0.0
    for foe in foes_around(board, cell, gen.owner):
        if foe in ignore:
            continue
        if not wins_duel(gen.stamina, gen.might, _defender_stamina(game, foe, foe.pos), foe.might):
            continue                              # 打不过就别惦记围歼
        if escape_routes(game, foe, threat_from=cell) == 0:
            total += AI_SIEGE_WORTH * general_value(foe)
    return total


# --------------------------------------------------------------------------
# 五、走位：给每个落脚点打分
# --------------------------------------------------------------------------
def rough_appeal(game, board, gen, cell, steps):
    """走位的**便宜**打分（不推演，只看现有局面），用来给候选落脚点排序

    真分数由 exact_move_score 算（那一步要临时改局面、按计分板精算），
    所以这里只要能排出个大概次序就行——省下的时间留给头几名去精算。
    猎物那两项只按身价的四分之一给个量级（真值留给精算），别让好位置排到后面去。
    """
    row, col = cell
    score = REGEN[game.grid[row][col]] * gen.might
    score += AI_CITY_PULL * cell_value(game, cell)
    if game.grain_at(row, col):
        score += AI_GRAIN_PULL * min(game.grain_at(row, col), AI_GRAIN_CARRY) * SCORE_GRAIN
    score -= threat_penalty(game, board, gen, cell)
    if gen.move_points - steps >= 1:              # 走过去还能再冲一仗
        for foe in foes_around(board, cell, gen.owner):
            if wins_duel(gen.stamina, gen.might, _defender_stamina(game, foe, foe.pos), foe.might):
                score += 0.25 * AI_KILL_WORTH * general_value(foe)
            if escape_routes(game, foe, threat_from=cell) == 0:
                score += AI_SIEGE_WORTH * general_value(foe)
    score -= AI_IDLE_PENALTY * board.focus_gap(gen.owner, cell)
    return score


def exact_move_score(game, board, gen, cell, steps):
    """把 gen 摆到 cell 上，算这一次走位值多少分（算完原样还回去）。

    要临时改局面才准的有三件，所以整段都在存档里做：
      * 地盘归属会因为一个人挪窝而变（计分板上的确切变化只能真算）；
      * 站在这里下一步能打谁——同一回合内敌人插不进手，所以这一步几乎能兑现；
      * 站过去之后堵断了谁的退路（退路一断，下次开打就是歼灭）。
    返回的是**绝对**分数差，要跟"原地不动"的同一个数相减才是这次的净收益。
    """
    snap = _Snapshot(game)
    try:
        gen.row, gen.col = cell
        now = game.scoreboard()[0]
        score = now[gen.owner][0] - now[1 - gen.owner][0]
        # 回血：落脚地形的每回合回血（城池 +3 / 通路 +2），体力终将换成分数
        score += REGEN[game.grid[cell[0]][cell[1]]] * gen.might
        if game.grain_at(*cell):
            score += AI_GRAIN_PULL * min(game.grain_at(*cell), AI_GRAIN_CARRY) * SCORE_GRAIN
        # 下一步能打谁：连同那一仗的收益一起算进来（同一回合内可以兑现）
        victims = ()
        if gen.move_points - steps >= 1:
            for target in game.compute_attackable(gen):
                plan = plan_assault(game, board, gen, target)
                if plan is not None and plan.score > 0:
                    score += plan.score
                    victims += plan.kills + plan.driven
        # 别把自己送到刀口下（刚算过的那一仗能清掉的敌人不算数）
        score -= threat_penalty(game, board, gen, cell, ignore=victims)
        score += siege_bonus(game, board, gen, cell, ignore=victims)
        score -= AI_IDLE_PENALTY * board.focus_gap(gen.owner, cell)
        return score
    finally:
        snap.restore()


def best_move(game, board, ready):
    """挑一步最划算的走位 -> (武将, 落脚格, 搬多少粮)；不值得动就返回 None。

    分两轮：先用便宜的分项给所有落脚点排序，再对头几名真的走一遍、按计分板精算
    （一个人挪窝会让好几格的归属跟着变，这个只有真算才知道），取净赚最多的那个。
    """
    rough = []
    for gen in ready:
        for cell, steps in board.reach[gen].items():
            if cell == gen.pos:
                continue
            rough.append((rough_appeal(game, board, gen, cell, steps), gen.name, cell, gen, steps))
    if not rough:
        return None
    rough.sort(key=lambda item: (-item[0], item[1], item[2]))

    best, best_score, base = None, None, {}
    for _appeal, _name, cell, gen, steps in rough[:AI_LOOKAHEAD]:
        if gen not in base:                       # 原地不动 = 这一次走位的基准
            base[gen] = exact_move_score(game, board, gen, gen.pos, 0)
        score = exact_move_score(game, board, gen, cell, steps)
        if score <= base[gen] + AI_TAKE_EDGE:     # 挪过去还不如歇着，别来回蹭
            continue
        if best_score is None or score > best_score:
            best, best_score = (gen, cell), score
    if best is None:
        return None
    gen, cell = best
    # 顺路搬粮。搬运的净效果是"把粮从出发格挪到落点格"（武将身上不存粮，见 Game.walk），
    # 所以不能见粮就搬——那只会把城里的存粮一路拖散在野地里。只在两种情况下搬：
    # 带伤（落到地方就地吃）、或者要进城（囤进自己的城池）。
    carry = 0
    if gen.stamina < gen.stamina_cap * AI_EAT_BELOW or game.grid[cell[0]][cell[1]] == CITY:
        carry = min(game.grain_at(*gen.pos), AI_GRAIN_CARRY)
    return gen, cell, carry


# --------------------------------------------------------------------------
# 六、吃粮：把体力换成分数，还要算上"这一口救不救命"
# --------------------------------------------------------------------------
def eat_gain(game, board, gen, amount):
    """吃 amount 石粮换来的分数。

    回的那点体力直接就是将领分（(100+体力)×武力，每点体力值一个武力的分）；
    代价是这堆粮本来算在我的地盘分里（每石 150）——**只有那堆现在归我**才算代价，
    在别人地盘上吃掉的粮，等于白赚。
    最后加上"救命分"：吃这一口能把"守不住"变成"守得住"，那就不是算小账的时候。
    """
    gained = min(amount * GRAIN_HEAL, gen.stamina_cap - gen.stamina)
    score = gained * gen.might
    if board.owner_of(gen.pos) == gen.owner:
        score -= amount * SCORE_GRAIN
    return score + _rescue_worth(game, board, gen, amount)


def _rescue_worth(game, board, gen, amount):
    """吃这一口把"可能被打死"变成"守得住"，值多少分（快死的时候这一口是救命）。"""
    before = threat_penalty(game, board, gen, gen.pos)
    snap = _Snapshot(game)
    try:
        gen.stamina = min(gen.stamina_cap, gen.stamina + amount * GRAIN_HEAL)
        after = threat_penalty(game, board, gen, gen.pos)
    finally:
        snap.restore()
    return max(0.0, before - after)


def best_eat(game, board, ready, attack):
    """最值的一口粮 -> (分数, 武将, 吃几石)；都不值就返回 None。

    attack 是这一步最赚的那一仗：如果吃粮的正是那位武将、而且吃完就走不动了，
    那就得把这一仗的收益从吃粮的好处里扣掉——否则它会为了一口粮放过一个好机会。
    """
    best = None
    for gen in ready:
        for amount in game.eat_amounts(gen):
            gain = eat_gain(game, board, gen, amount)
            if attack is not None and attack.gen is gen and gen.move_points - amount < 1:
                gain -= max(0.0, attack.score)
            if best is None or gain > best[0]:
                best = (gain, gen, amount)
    return best


# --------------------------------------------------------------------------
# 七、棋盘上的一步
# --------------------------------------------------------------------------
def best_assault(game, board, ready):
    """手头最赚的一仗 -> Assault（没有能打的就返回 None）。

    只考虑**现在**就能踏进去的敌方格（相邻、且还剩移动力）。要走一步再打的那种
    放在走位里一起算（走位的分数里含"下一步能打谁"）。
    """
    best = None
    for gen in ready:
        for cell in game.compute_attackable(gen):
            plan = plan_assault(game, board, gen, cell)
            if plan is not None and (best is None or plan.score > best.score):
                best = plan
    return best


def ai_map_step(game):
    """电脑在棋盘上走一步："打一仗 / 吃一口 / 挪一步"里挑此刻最赚的那个。

    三种动作换算成同一套货币（分），所以能直接比大小——"吃一口救命的粮"
    排在"打一场无关痛痒的仗"前面是理所当然的，不需要额外的优先级规则。
    """
    board = Board(game)
    ready = [g for g in game.generals
             if g.alive and g.owner == game.current and not g.exhausted]

    attack = best_assault(game, board, ready)
    eat = best_eat(game, board, ready, attack)
    if eat is not None and eat[0] > 0 and (attack is None or eat[0] > max(0.0, attack.score)):
        _gain, gen, amount = eat
        game.eat_grain(gen, amount)
        return
    if attack is not None and attack.score > 0:
        game.charge(attack.gen, *attack.cell)
        return
    move = best_move(game, board, ready)
    if move is not None:
        gen, cell, carry = move
        game.select(gen)                          # 选中一下，让人看得见是谁在动
        game.move(gen, *cell, carry=carry)        # 电脑不走"问玩家带多少"那条路，见 Game.move
        return
    game.end_turn()                               # 没事可做：收工，把回合交给对方


# --------------------------------------------------------------------------
# 八、交战屏上的决策
# --------------------------------------------------------------------------
def ai_pick_defender(battle):
    """守方挑谁先出阵 -> 下标。

    第一位必须应战一回合（规则如此），所以这件事等于"派谁去挨那一下"。
    把两种出场顺序各推演一遍，挑我方损失最小的（和攻方推演共用同一套守方判断）：
      * 谁单挑就拼得过攻方，派谁先上最省事——他顶住，攻方就得撤，这一格连同
        攻方一路掉下来的体力都白赚；
      * 都拼不过，那这一格多半保不住，就看谁去挡刀划算（值不值得拿命换，
        以及能替后面那位磨掉攻方多少）。
    打平就沿用守将原本的站位顺序，保证同样的局面电脑的选择是确定的。

    推演里攻方"一路打下来"的体力是估的（真打起来要掷骰子），所以这只是两种顺序
    之间的比较，不追求绝对值准。
    """
    best, best_score = 0, None
    for i, first in enumerate(battle.defenders):
        order = [first] + [g for g in battle.defenders if g is not first]
        score = _defense_score(battle, order)
        if best_score is None or score > best_score:
            best, best_score = i, score
    return best


def _defense_score(battle, order):
    """按给定出场顺序守这一格，我方值多少分（相对"弃守、各自逃命"）。"""
    game, cell = battle.game, battle.cell
    spare, worn = battle.atk.stamina, battle.atk.stamina     # 攻方打到这里还剩多少体力
    score = 0.0
    for k, dfd in enumerate(order):
        mine, theirs = duel_race(_defender_stamina(game, dfd, cell), dfd.might,
                                 worn, battle.atk.might)
        if mine < theirs:
            # 这位守得住：攻方拼不过就得收手，格子保住，还白换他一路掉下来的体力
            return score + cell_value(game, cell) + (spare - worn) * battle.atk.might
        if defender_stands_firm(game, dfd, battle.atk, cell, mates=order[k + 1:]):
            score -= general_value(dfd)                      # 拿命挡刀
            worn -= mine * average_damage(dfd.might)
            if worn <= 0:                                    # 攻方也被磨倒了
                return score + cell_value(game, cell)
        elif k == len(order) - 1:
            score -= cell_value(game, cell)                  # 最后一位也撤了，格子丢
    return score


def ai_should_continue(battle, gen):
    """这一方要不要接着缠斗；不划算就撤（撤退权另算，没退路时只能接着打）。

    攻方：只要**不输**这场对拼就压上去——守方赢不下来就只剩两条路，跑得掉就撤
    （格子归我），跑不掉就死战（被我歼灭）。反过来，拼不过就立刻收手，
    没必要拿命去换对方几点体力。打平又退无可退是"同归于尽"，只有换得贵才值。
    守方：交给 defender_stands_firm（和攻方推演共用同一套判断，两边不会算出两套账）。
    """
    game = battle.game
    foe = battle.foe_of(gen)
    if gen is battle.atk:
        foe_stamina = _defender_stamina(game, foe, battle.cell)
        mine, theirs = duel_race(gen.stamina, gen.might, foe_stamina, foe.might)
        if mine < theirs:
            return True                                  # 赢定了，压上去
        if mine > theirs:
            return False                                 # 拼不过，收手
        return escape_routes(game, foe, threat_from=battle.origin,
                             cell=battle.cell) > 0       # 打平：他跑得掉就逼他跑
    mates = [g for g in battle.defenders
             if g is not gen and g.alive and g.pos == battle.cell]
    if defender_stands_firm(game, gen, foe, battle.cell, mates=mates):
        return True
    return False                                         # 守不住，撤（能撤就撤，见 ai_battle_step）


def ai_pick_retreat(battle):
    """守方往哪撤 -> retreat_choices 里的下标。

    撤退本身就判负（这一格让出去），还要欠下回合的行动力，所以挑落脚点看两件事：
    撤完之后**别贴着比我强的敌人**（那是换个地方死），以及**能多回血、多拿分**（城池）。
    """
    game = battle.game
    gen = battle.dfd
    best, best_score = 0, None
    for i, (dest, steps) in enumerate(battle.retreat_choices):
        row, col = dest
        score = -AI_DEBT_WORTH * steps                     # 退得越远，下回合越迈不开腿
        score += AI_CITY_PULL * cell_value(game, (row, col))
        for foe in game.generals:
            if not foe.alive or foe.owner == gen.owner:
                continue
            gap = max(abs(foe.row - row), abs(foe.col - col))
            if gap == 1 and wins_duel(foe.stamina, foe.might, gen.stamina, gen.might):
                score -= AI_THREAT_WORTH * general_value(gen)   # 撤到强敌嘴边，等于白撤
            elif gap <= 2:
                score -= AI_IDLE_PENALTY
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
