#!/usr/bin/env python3
"""CLI for generating images (up to 4K) with the Gemini API.

Usage:
    export GEMINI_API_KEY=...
    ./imagegen.py "a lighthouse at dusk, oil painting" -o lighthouse.png
    ./imagegen.py "product shot of a mug" --aspect 4:3 --size 4K -n 2

Standard library only; no dependencies.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3-pro-image-preview"  # supports imageSize 1K/2K/4K
ASPECTS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


def generate(api_key, model, prompt, aspect, size, timeout):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect, "imageSize": size},
        },
    }
    req = urllib.request.Request(
        f"{API_ROOT}/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")


def extract_images(data):
    """Yield (bytes, mime_type) for each inline image; print any text parts."""
    cands = data.get("candidates") or []
    if not cands:
        sys.exit(f"No candidates returned: {json.dumps(data.get('promptFeedback', data))}")
    for part in cands[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            yield base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type", "image/png")
        elif part.get("text"):
            print(part["text"], file=sys.stderr)


def output_paths(base, count, ext):
    root, given = os.path.splitext(base)
    ext = given or ext
    for i in range(count):
        yield f"{root}{ext}" if count == 1 else f"{root}_{i + 1}{ext}"


def main():
    p = argparse.ArgumentParser(description="Generate images with Gemini (up to 4K).")
    p.add_argument("prompt", nargs="?", help="Image prompt (or use --prompt-file)")
    p.add_argument("-f", "--prompt-file", help="Read the prompt from a file")
    p.add_argument("-o", "--output", default="image.png", help="Output path (default: image.png)")
    p.add_argument("-s", "--size", choices=["1K", "2K", "4K"], default="4K", help="Resolution (default: 4K)")
    p.add_argument("-a", "--aspect", choices=ASPECTS, default="1:1", help="Aspect ratio (default: 1:1)")
    p.add_argument("-m", "--model", default=os.environ.get("GEMINI_IMAGE_MODEL", DEFAULT_MODEL))
    p.add_argument("-n", "--count", type=int, default=1, help="Number of requests/images (default: 1)")
    p.add_argument("--timeout", type=int, default=300, help="Per-request timeout seconds (default: 300)")
    args = p.parse_args()

    prompt = open(args.prompt_file).read().strip() if args.prompt_file else args.prompt
    if not prompt:
        p.error("provide a prompt or --prompt-file")
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("Set GEMINI_API_KEY in your environment.")

    saved = []
    for i in range(args.count):
        data = generate(key, args.model, prompt, args.aspect, args.size, args.timeout)
        for img, mime in extract_images(data):
            ext = mimetypes.guess_extension(mime) or ".png"
            path = next(output_paths(args.output, 1, ext)) if args.count == 1 else \
                list(output_paths(args.output, args.count, ext))[i]
            with open(path, "wb") as fh:
                fh.write(img)
            saved.append(path)
            print(f"Saved {path} ({len(img) / 1e6:.1f} MB)")
    if not saved:
        sys.exit("No image returned (the model may have refused the prompt).")


if __name__ == "__main__":
    main()
