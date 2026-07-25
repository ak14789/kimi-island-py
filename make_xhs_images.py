# -*- coding: utf-8 -*-
"""小红书宣传图生成：封面 + 三种形态 + 上手指南（1080x1440）"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 1080, 1440
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
OUT_DIR = "宣传物料"
REPO = "github.com/ak14789/kimi-island-py"

GREEN = (74, 222, 128)
GREEN_SOFT = (134, 239, 172)
BLUE = (96, 165, 250)
WHITE = (255, 255, 255)
GRAY = (185, 193, 212)


def font(size, bold=True):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def make_bg(top=(16, 20, 42), bottom=(26, 30, 66)):
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-260, -320, 640, 420], fill=(59, 130, 246, 60))
    gd.ellipse([620, 980, 1500, 1760], fill=(34, 197, 94, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(130))
    return Image.alpha_composite(bg.convert("RGBA"), glow)


def rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *img.size], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def autocrop(img, thresh=18, pad=20):
    rgb = img.convert("RGB")
    bg_c = rgb.getpixel((2, 2))
    px = rgb.load()
    w, h = rgb.size
    xs, ys = [], []
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            p = px[x, y]
            if sum(abs(p[i] - bg_c[i]) for i in range(3)) > thresh:
                xs.append(x)
                ys.append(y)
    if not xs:
        return img
    box = (max(0, min(xs) - pad), max(0, min(ys) - pad),
           min(w, max(xs) + pad), min(h, max(ys) + pad))
    return img.crop(box)


def fit(img, max_w, max_h):
    r = min(max_w / img.width, max_h / img.height)
    return img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)


def center_x(d, text, f):
    return (W - d.textlength(text, font=f)) / 2


def tag_pill(d, text, y, fg=(170, 200, 255), outline=(120, 170, 255),
             fill=(46, 126, 247, 60), size=34):
    f = font(size)
    tw = d.textlength(text, font=f)
    tx = (W - tw) / 2
    d.rounded_rectangle([tx - 28, y, tx + tw + 28, y + size + 26],
                        (size + 26) // 2, fill=fill, outline=outline, width=2)
    d.text((tx, y + 13), text, font=f, fill=fg)


def badges_row(d, items, y, size=32):
    f = font(size)
    gap = 26
    widths = [d.textlength(b, font=f) + 52 for b in items]
    total = sum(widths) + gap * (len(items) - 1)
    x = (W - total) / 2
    for b, bw in zip(items, widths):
        d.rounded_rectangle([x, y, x + bw, y + size + 30],
                            (size + 30) // 2, fill=(34, 197, 94, 45),
                            outline=GREEN, width=2)
        d.text((x + 26, y + 15), b, font=f, fill=GREEN_SOFT)
        x += bw + gap


def footer(d, y):
    f = font(30, bold=False)
    text = REPO
    d.text((center_x(d, text, f), y), text, font=f, fill=(130, 140, 165))


exp_raw = autocrop(Image.open("screenshots/expanded.png"))
com_raw = autocrop(Image.open("screenshots/compact.png"))
dot_raw = autocrop(Image.open("screenshots/dot.png"))


# ================= 封面 =================
def cover():
    bg = make_bg()
    d = ImageDraw.Draw(bg)

    tag_pill(d, "GitHub 开源 · Windows 桌面神器", 78)

    d.text((center_x(d, "Kimi 额度还剩多少？", font(108)), 176),
           "Kimi 额度还剩多少？", font=font(108), fill=WHITE)
    d.text((center_x(d, "抬头一眼就知道", font(108)), 310),
           "抬头一眼就知道", font=font(108), fill=GREEN)

    sub = "悬浮屏顶的灵动岛 · 会员额度 / 周用量 / 频限实时监控"
    d.text((center_x(d, sub, font(38, bold=False)), 466),
           sub, font=font(38, bold=False), fill=GRAY)

    # 截图卡片：白底 + 圆角，完整展示
    card_y = 570
    exp = fit(exp_raw, 820, 640)
    cx = (W - exp.width) // 2
    d.rounded_rectangle([cx - 24, card_y - 24, cx + exp.width + 24,
                         card_y + exp.height + 24], 36, fill=(255, 255, 255, 255))
    bg.paste(rounded(exp, 24), (cx, card_y), rounded(exp, 24))

    # 悬浮胶囊压在卡片顶边，模拟真实灵动岛
    com = fit(com_raw, 380, 80)
    d.rounded_rectangle([W // 2 - com.width // 2 - 14, card_y - 66,
                         W // 2 + com.width // 2 + 14, card_y - 66 + com.height + 28],
                        40, fill=(8, 10, 20, 255), outline=(70, 80, 110), width=2)
    bg.paste(rounded(com, com.height // 2),
             (W // 2 - com.width // 2, card_y - 52), rounded(com, com.height // 2))

    by = card_y + exp.height + 64
    badges_row(d, ["开源免费", "免安装 双击即用", "实时自动刷新"], by)
    footer(d, by + 118)

    out = os.path.join(OUT_DIR, "cover.png")
    bg.convert("RGB").save(out, quality=95)
    print("saved:", out)


CARD_FILL = (33, 38, 62, 255)
CARD_LINE = (88, 98, 135, 255)


# ================= 图2：三种形态 =================
def modes():
    bg = make_bg()
    d = ImageDraw.Draw(bg)

    tag_pill(d, "一个工具 · 三种形态", 80)
    d.text((center_x(d, "贴着屏幕顶部 不占地", font(96)), 180),
           "贴着屏幕顶部 不占地", font=font(96), fill=WHITE)
    sub = "点击展开 · 移开自动收起 · 位置随意拖动并记忆"
    d.text((center_x(d, sub, font(38, bold=False)), 320),
           sub, font=font(38, bold=False), fill=GRAY)

    def card(x, y, w, h):
        d.rounded_rectangle([x, y, x + w, y + h], 32,
                            fill=CARD_FILL, outline=CARD_LINE, width=2)

    def label(x, y, text):
        d.text((x, y), text, font=font(40), fill=GREEN_SOFT)

    # 左：展开面板（大）
    exp = fit(exp_raw, 560, 500)
    card(60, 430, 640, 720)
    label(96, 470, "展开面板")
    d.text((96, 532), "额度 / 频限 / 到期时间一目了然",
           font=font(30, bold=False), fill=GRAY, spacing=10)
    bg.paste(rounded(exp, 20), (60 + (640 - exp.width) // 2, 430 + 720 - exp.height - 36),
             rounded(exp, 20))

    # 右上：紧凑胶囊
    com = fit(com_raw, 300, 74)
    card(740, 430, 280, 330)
    label(776, 470, "紧凑胶囊")
    d.text((776, 532), "平时只显示\n一行进度", font=font(30, bold=False),
           fill=GRAY, spacing=10)
    bg.paste(rounded(com, com.height // 2), (740 + (280 - com.width) // 2, 656),
             rounded(com, com.height // 2))

    # 右下：圆点
    dot = fit(dot_raw, 120, 120)
    card(740, 800, 280, 350)
    label(776, 840, "圆点模式")
    d.text((776, 902), "只剩一颗\n呼吸灯", font=font(30, bold=False),
           fill=GRAY, spacing=10)
    bg.paste(rounded(dot, 30), (740 + (280 - dot.width) // 2, 996),
             rounded(dot, 30))

    # 底部：变色预警说明
    y = 1210
    d.rounded_rectangle([60, y, 1020, y + 120], 28,
                        fill=CARD_FILL, outline=CARD_LINE, width=2)
    for i, (c, t) in enumerate([((74, 222, 128), "充足"),
                                ((250, 204, 21), "偏低"),
                                ((248, 113, 113), "告急")]):
        x = 150 + i * 300
        d.ellipse([x, y + 43, x + 34, y + 77], fill=c)
        d.text((x + 52, y + 38), t, font=font(36), fill=WHITE)
    cap = "剩余额度自动变色预警 · 刷新间隔自适应"
    d.text((center_x(d, cap, font(28, bold=False)), 1352),
           cap, font=font(28, bold=False), fill=(150, 160, 185))
    footer(d, 1390)

    out = os.path.join(OUT_DIR, "modes.png")
    bg.convert("RGB").save(out, quality=95)
    print("saved:", out)


# ================= 图3：三步上手 =================
def guide():
    bg = make_bg()
    d = ImageDraw.Draw(bg)

    tag_pill(d, "无需安装 Python · 绿色单文件", 80)
    d.text((center_x(d, "三步上手", font(110)), 180), "三步上手",
           font=font(110), fill=WHITE)
    sub = "下载即用，凭证全自动"
    d.text((center_x(d, sub, font(40, bold=False)), 330),
           sub, font=font(40, bold=False), fill=GRAY)

    steps = [
        ("去 Releases 下载 exe",
         "GitHub 搜 kimi-island-py，双击即用\nWindows 10 1903+ / Win11 都能跑"),
        ("登录凭证自动获取",
         "登录过 Kimi CLI 就直接读取\n也可以在面板里粘贴浏览器 token"),
        ("胶囊出现在屏幕顶部",
         "托盘右键可隐藏 / 收起为圆点\nToken 只存本地，不上传任何服务器"),
    ]
    y = 470
    for i, (title, body) in enumerate(steps, 1):
        d.rounded_rectangle([70, y, 1010, y + 220], 30,
                            fill=CARD_FILL, outline=CARD_LINE, width=2)
        d.ellipse([110, y + 40, 190, y + 120], fill=(22, 101, 52, 255),
                  outline=GREEN, width=3)
        num = str(i)
        nf = font(44)
        nw = d.textlength(num, font=nf)
        d.text((150 - nw / 2, y + 56), num, font=nf, fill=GREEN_SOFT)
        d.text((220, y + 42), title, font=font(46), fill=WHITE)
        d.text((220, y + 116), body, font=font(32, bold=False), fill=GRAY, spacing=12)
        y += 260

    # 底部 Star 引导
    d.rounded_rectangle([70, y + 10, 1010, y + 126], 30,
                        fill=(113, 88, 4, 255), outline=(250, 204, 21), width=2)
    tip = "觉得好用，顺手点个 Star 支持一下"
    d.text((center_x(d, tip, font(40)), y + 44), tip, font=font(40),
           fill=(253, 224, 71))
    footer(d, 1388)

    out = os.path.join(OUT_DIR, "guide.png")
    bg.convert("RGB").save(out, quality=95)
    print("saved:", out)


os.makedirs(OUT_DIR, exist_ok=True)
cover()
modes()
guide()
