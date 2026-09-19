# -*- coding: utf-8 -*-
"""无头回归测试：让两个电脑互相对打整局，不需要图形界面。

    python smoke_test.py           # 只跑规则和电脑决策，逐局打印局面
    python smoke_test.py --draw    # 顺便把整局画一遍（dummy 显卡驱动），检查绘制路径

改过规则 / 电脑判断之后跑一下，看结果有没有变：种子固定，同样的代码每次输出都一样，
所以搬移模块、重构前后可以拿输出逐字节对比。每名武将的体力、位置、移动力都打全了，
任何一步走歪都会露出来。
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")     # 无头运行：不进真窗口
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warlords as W

SEEDS = (1, 7, 42, 2026)


def run(seed, draw=False, max_frames=200000):
    screen = buttons = None
    if draw:
        import pygame
        pygame.init()
        screen = pygame.display.set_mode((W.WIN_W, W.WIN_H))
        buttons = W.make_buttons()

    game = W.Game(seed=seed)
    game.start_match(players=2)
    game.controllers = {W.P1: W.AI, W.P2: W.AI}      # 两边都托管，整局无人操作

    frames = battle_frames = 0
    while not game.over and frames < max_frames:
        battle = game.battle                         # 照 play_match 每帧的顺序来
        if battle is not None:
            battle.update()                          # 掉血动画放完后自动进入下一步
            W.ai_pump(game)                          # 轮到电脑就让它走一步
            if draw:
                battle.draw(screen, (0, 0))
            battle_frames += 1
        else:
            game.tick()
            W.ai_pump(game)
            if draw:
                game.draw(screen, (0, 0), buttons)
        if draw:
            pygame.display.flip()
        frames += 1

    print(f"== seed={seed} frames={frames} battle_frames={battle_frames} "
          f"turn={game.turn} over={game.over} winner={game.winner}")
    print("-- 武将：名字 存活 行 列 体力 移动力")
    for g in game.generals:
        print(f"   {g.name} {g.alive} {g.row} {g.col} {g.stamina} {g.move_points}")
    print("-- 战报")
    for i, line in enumerate(game.log):
        print(f"   [{i}] {line}")


def main():
    draw = "--draw" in sys.argv
    for seed in SEEDS:
        run(seed, draw=draw)


if __name__ == "__main__":
    main()
