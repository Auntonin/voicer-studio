"""
assets/generate_icon.py
=======================
Generates high-resolution studio icons for Voicer Studio:
- assets/app_icon.png (512x512 RGBA transparent)
- assets/app_icon.ico (multi-size: 256, 128, 64, 48, 32, 16)
Based on the official studio logo reference (assets/logo_reference.jpg).
"""

from pathlib import Path
from PIL import Image
import numpy as np

def generate_icons(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    ref_path = output_dir / "logo_reference.jpg"

    if ref_path.exists():
        import cv2
        img = cv2.imread(str(ref_path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # The outer checkerboard has gray > 180, while the squircle is dark < 100
        thresh = (gray < 160).astype(np.uint8) * 255
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        largest = max(contours, key=cv2.contourArea)

        # Create smooth anti-aliased mask
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [largest], -1, 255, thickness=cv2.FILLED)
        mask_smooth = cv2.GaussianBlur(mask, (3, 3), 0.8)

        # Convert BGR to RGB and attach alpha mask
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        rgba = np.dstack((rgb, mask_smooth))

        # Crop around squircle bounding box with slight padding
        x, y, w, h = cv2.boundingRect(largest)
        pad = 8
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(img.shape[1], x + w + pad)
        y1 = min(img.shape[0], y + h + pad)

        cropped = rgba[y0:y1, x0:x1]
        pil_img = Image.fromarray(cropped)
        img_512 = pil_img.resize((512, 512), Image.Resampling.LANCZOS)
    else:
        # Fallback procedural generation
        from PIL import ImageDraw
        size = 512
        img_512 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_512)
        margin = 20
        radius = 110
        rect_box = [margin, margin, size - margin, size - margin]
        draw.rounded_rectangle(rect_box, radius=radius, fill=(20, 22, 27, 255), outline=(48, 56, 70, 255), width=6)

    # Save 512x512 PNG
    png_path = output_dir / "app_icon.png"
    img_512.save(png_path, format="PNG")

    # Save Multi-size ICO for Windows
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    ico_path = output_dir / "app_icon.ico"
    img_512.save(ico_path, format="ICO", sizes=ico_sizes)

    print(f"[OK] Generated {png_path} and {ico_path}")

if __name__ == "__main__":
    assets_dir = Path(__file__).resolve().parent
    generate_icons(assets_dir)
