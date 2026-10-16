"""Regenera assets/icon.png + icon.ico (quadrado escuro + zigue-zague verde)."""
from PIL import Image, ImageDraw


def main() -> None:
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56,
                        fill=(29, 29, 33, 255), outline=(46, 46, 53, 255), width=6)
    d.line([(48, 88), (104, 88), (104, 128), (152, 128), (152, 168), (208, 168)],
           fill=(34, 197, 94, 255), width=16, joint="curve")
    d.ellipse([150, 40, 216, 106], outline=(59, 130, 246, 255), width=12)
    img.save("assets/icon.png")
    img.save("assets/icon.ico",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon ok")


if __name__ == "__main__":
    main()
