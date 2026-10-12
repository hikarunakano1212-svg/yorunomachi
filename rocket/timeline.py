"""動画の時刻表 [s]。scene.py(映像)と audio.py(音)が同じ値を使う。"""
import geometry as G

FPS = 24
T_END = 20.0                       # 本編
LOGO_LEN = 3.5                     # 最後のロゴ
T_TOTAL = T_END + LOGO_LEN

SCAN = (0.25, 2.9)                 # 図面の走査
RISE = (3.1, 5.3)                  # 線 → 光のワイヤー
BUILD = (5.2, 8.5)                 # 積み上げ
DISSOLVE = (8.6, 10.9)             # 図面が溶けて夜の射点へ
LIGHT_ON = [10.05 + 0.22 * i for i in range(4)]   # 照明塔の点灯
ARMS = (11.0, 12.9)                # アクセスアームの離脱
COUNTS = [12.5, 13.5, 14.5]        # T-3, T-2, T-1
TI = G.LAUNCH["t_ignition"]        # 点火
TL = G.LAUNCH["t_liftoff"]         # リフトオフ
T_CUT = 17.6                       # 海上のカメラへ
T_TITLE = 18.2                     # タイトル
