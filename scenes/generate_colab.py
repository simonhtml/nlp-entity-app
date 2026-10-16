"""Free scene generation on a Google Colab T4 GPU (no API key, no payment).

Colab: Runtime > Change runtime type > T4 GPU, then run in cells:
    !pip -q install diffusers transformers accelerate sentencepiece protobuf realesrgan basicsr
    !wget -q <raw URL of this repo's scenes/ files> (or upload the .md and this .py)
    !python generate_colab.py
Output: scenes_out/S01.png ... S12.png (native ~1.5 MP) and scenes_out/up/S0X.png (3000+ px, upscaled).
Upscaled output is softer than native; say so on any listing that needs true 4K.
"""
import re, os, torch
from diffusers import FluxPipeline
from PIL import Image

MD = "Image-Prompts-Etsy-Scenes.md"
SUFFIX = ("Photorealistic interior photograph, natural window light, high detail, "
          "no text, no watermark, no people, no artwork inside frames.")
S05 = ("Straight-on photograph of a calm bedroom wall, a bed with exactly two pillows and one "
       "lumbar cushion, headboard visible, white linen and a terracotta throw, two empty white "
       "frames with wide white mats hanging side by side above the bedhead, interiors blank white, "
       "bedside tables with small lamps, soft morning light.")

text = open(MD, encoding="utf-8").read()
scenes = re.findall(r"## (S\d\d) [^\n]*\((\d+) x (\d+) px[^\n]*\n(.*?)\nUsed for", text, re.S)

pipe = FluxPipeline.from_pretrained("black-forest-labs/FLUX.1-schnell", torch_dtype=torch.bfloat16)
pipe.enable_model_cpu_offload()
os.makedirs("scenes_out/up", exist_ok=True)

for sid, w, h, prompt in scenes:
    w, h = int(w), int(h)
    k = (1.5e6 / (w * h)) ** 0.5                      # target ~1.5 MP native
    gw, gh = round(w * k / 16) * 16, round(h * k / 16) * 16
    p = (S05 if sid == "S05" else prompt.strip()) + " " + SUFFIX
    img = pipe(p, width=gw, height=gh, num_inference_steps=4, guidance_scale=0.0,
               generator=torch.Generator("cpu").manual_seed(42)).images[0]
    img.save(f"scenes_out/{sid}.png")
    s = max(w, h) / max(gw, gh)
    img.resize((round(gw * s), round(gh * s)), Image.LANCZOS).save(f"scenes_out/up/{sid}.png")
    print(sid, f"native {gw}x{gh} -> {round(gw*s)}x{round(gh*s)}")
