import subprocess
import os

ffmpeg = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\.venv\lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"

assets_to_convert = [
    ("app/build/web/assets/real_phone_bench_pipetting.ogv", "app/build/web/assets/real_phone_bench_pipetting.mp4"),
    ("app/build/web/assets/real_phone_bench_pipetting.ogv", "app/build/web/assets/real_phone_bench_pipetting.webm"),
    ("app/build/web/assets/real_elisa_immunoassay.ogv", "app/build/web/assets/real_elisa_immunoassay.mp4"),
]

for src, dst in assets_to_convert:
    if os.path.exists(src):
        cmd = [ffmpeg, "-y", "-i", src, "-c:v", "libx264" if dst.endswith(".mp4") else "libvpx-vp9", "-pix_fmt", "yuv420p", dst]
        print(f"Converting {src} -> {dst}...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(f"Result {dst}: ret={res.returncode}, size={os.path.getsize(dst) if os.path.exists(dst) else 0}")
    else:
        print(f"Src {src} not found!")
