"""Generate app.ico for the executable icon."""
import os
from PIL import Image, ImageDraw


def generate_icon():
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "图标.png")

    if os.path.exists(icon_path):
        src = Image.open(icon_path).convert("RGBA")
        sizes = [16, 32, 48, 64, 128, 256]
        images = []
        for size in sizes:
            img = src.resize((size, size), Image.LANCZOS)
            images.append(img)
        images[0].save("app.ico", format="ICO",
                       sizes=[(s, s) for s in sizes],
                       append_images=images[1:])
        print("Generated app.ico from 图标.png")
        return

    # Fallback: draw a clock icon
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pad = max(1, size // 16)
        draw.ellipse([pad, pad, size - pad, size - pad],
                     fill=(10, 132, 255), outline=(64, 156, 255),
                     width=max(1, size // 32))
        cx, cy = size // 2, size // 2
        hand_top = size // 5
        draw.line([cx, cy, cx, hand_top], fill="white",
                  width=max(1, size // 20))
        import math
        angle = -math.radians(50)
        hx = cx + int(size // 4 * math.cos(angle))
        hy = cy + int(size // 4 * math.sin(angle))
        draw.line([cx, cy, hx, hy], fill="white",
                  width=max(1, size // 20))
        dot_r = max(1, size // 20)
        draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                     fill="white")
        images.append(img)
    images[0].save("app.ico", format="ICO",
                   sizes=[(s, s) for s in sizes],
                   append_images=images[1:])
    print("Generated app.ico (fallback)")


if __name__ == "__main__":
    generate_icon()
