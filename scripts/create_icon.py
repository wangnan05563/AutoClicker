# -*- coding: utf-8 -*-
"""
图标生成脚本 - 为自动点击工具创建多尺寸图标
"""

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("请安装Pillow库: pip install Pillow")
    exit(1)

import os

def create_icon(size):
    """创建指定尺寸的图标"""
    # 创建透明背景
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 计算比例
    scale = size / 256.0
    
    # 绘制圆形背景（渐变效果用纯色模拟）
    margin = int(20 * scale)
    center = size // 2
    radius = (size - 2 * margin) // 2
    
    # 外圈 - 深蓝色
    draw.ellipse(
        [center - radius, center - radius, center + radius, center + radius],
        fill='#1a73e8',
        outline='#0d47a1',
        width=int(4 * scale)
    )
    
    # 内圈 - 浅蓝色
    inner_radius = int(radius * 0.75)
    draw.ellipse(
        [center - inner_radius, center - inner_radius, center + inner_radius, center + inner_radius],
        fill='#4285f4',
        outline=None
    )
    
    # 绘制鼠标指针图标
    pointer_width = int(30 * scale)
    pointer_height = int(45 * scale)
    pointer_x = center - pointer_width // 2
    pointer_y = center - pointer_height // 2 + int(10 * scale)
    
    # 鼠标指针形状（三角形）
    pointer_points = [
        (center, pointer_y),  # 顶点
        (pointer_x + pointer_width, pointer_y + int(20 * scale)),  # 右边
        (center, pointer_y + pointer_height),  # 底部中心
        (pointer_x, pointer_y + int(20 * scale)),  # 左边
    ]
    draw.polygon(pointer_points, fill='white', outline='#1a73e8')
    
    # 绘制点击效果（小圆圈）
    click_radius = int(8 * scale)
    click_x = center + int(15 * scale)
    click_y = center + int(15 * scale)
    draw.ellipse(
        [click_x - click_radius, click_y - click_radius, 
         click_x + click_radius, click_y + click_radius],
        fill='#ff9800',
        outline='#f57c00',
        width=int(2 * scale)
    )
    
    return img

def main():
    """生成多尺寸图标"""
    # 创建icons目录
    icons_dir = os.path.join(os.path.dirname(__file__), 'icons')
    if not os.path.exists(icons_dir):
        os.makedirs(icons_dir)
    
    # 托盘图标尺寸
    tray_sizes = [16, 32, 48]
    
    # 程序图标尺寸
    app_sizes = [256, 128, 64, 48, 32, 16]
    
    print("正在生成图标...")
    
    # 生成托盘图标
    tray_images = []
    for size in tray_sizes:
        img = create_icon(size)
        tray_images.append(img)
        img.save(os.path.join(icons_dir, f'tray_{size}x{size}.png'))
        print(f"  - 生成托盘图标: {size}x{size}")
    
    # 生成程序图标
    app_images = []
    for size in app_sizes:
        img = create_icon(size)
        app_images.append(img)
        img.save(os.path.join(icons_dir, f'app_{size}x{size}.png'))
        print(f"  - 生成程序图标: {size}x{size}")
    
    # 生成ICO文件（Windows程序图标）
    ico_path = os.path.join(icons_dir, 'autoclicker.ico')
    app_images[0].save(
        ico_path,
        format='ICO',
        sizes=[(img.width, img.height) for img in app_images],
        append_images=app_images[1:]
    )
    print(f"\n✅ 程序图标已生成: {ico_path}")
    
    # 生成托盘ICO文件
    tray_ico_path = os.path.join(icons_dir, 'tray.ico')
    tray_images[0].save(
        tray_ico_path,
        format='ICO',
        sizes=[(img.width, img.height) for img in tray_images],
        append_images=tray_images[1:]
    )
    print(f"✅ 托盘图标已生成: {tray_ico_path}")
    
    print("\n所有图标生成完成！")

if __name__ == '__main__':
    main()
