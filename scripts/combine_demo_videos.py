import os
import subprocess

ffmpeg_path = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\.venv\lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
assets_dir = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\app\build\web\assets"

v1 = os.path.join(assets_dir, "demo_1_pipette_scientist_screen_recording.mp4")
v2 = os.path.join(assets_dir, "demo_2_larvis_bubble_critical_alert.mp4")
v3 = os.path.join(assets_dir, "demo_3_larvis_protocol_today_voice_qa.mp4")
out_combined = os.path.join(assets_dir, "demo_combined_larvis_three_demos.mp4")

# Create concat list file
concat_list = os.path.join(assets_dir, "concat_list.txt")
with open(concat_list, "w") as f:
    f.write(f"file '{v1}'\n")
    f.write(f"file '{v2}'\n")
    f.write(f"file '{v3}'\n")

print("Running FFmpeg concat demuxer...")
cmd = [
    ffmpeg_path,
    "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", concat_list,
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "128k",
    out_combined
]

res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode == 0:
    size = os.path.getsize(out_combined)
    print(f"SUCCESS! Created {out_combined} (size: {size:,} bytes)")
else:
    print("FFmpeg error:", res.stderr)
