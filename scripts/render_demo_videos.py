import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import subprocess
import os
import math

FFMPEG = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\.venv\lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
ASSETS = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\app\build\web\assets"
TEMP_DIR = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\temp_renders"
os.makedirs(TEMP_DIR, exist_ok=True)

FONT_PATH = r"C:\Windows\Fonts\segoeui.ttf"
FONT_BOLD_PATH = r"C:\Windows\Fonts\segoeuib.ttf"

def get_font(size, bold=False):
    try:
        p = FONT_BOLD_PATH if bold else FONT_PATH
        return ImageFont.truetype(p, size)
    except:
        return ImageFont.load_default()

def draw_glass_panel(draw, xy, fill=(255, 255, 255, 210), outline=(220, 240, 230, 255), radius=16):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=1)

# ==========================================
# VIDEO 1: Pipette Scientist Screen Recording
# ==========================================
def render_video_1():
    print("Rendering Video 1: Pipette Scientist Screen Recording...")
    src_video = os.path.join(ASSETS, "real_phone_bench_pipetting.mp4")
    src_audio = os.path.join(ASSETS, "voice_larvis_pipette_bench.wav")
    raw_video = os.path.join(TEMP_DIR, "v1_raw.mp4")
    out_video = os.path.join(ASSETS, "demo_1_pipette_scientist_screen_recording.mp4")

    cap = cv2.VideoCapture(src_video)
    fps = 24.0
    duration = 14.1  # seconds
    total_frames = int(fps * duration)
    W, H = 1280, 720

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_video, fourcc, fps, (W, H))

    font_title = get_font(20, bold=True)
    font_bold = get_font(16, bold=True)
    font_reg = get_font(14, bold=False)
    font_mono = get_font(13, bold=False)

    for i in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        t = i / fps
        # Canvas background (Apple subtle light emerald gradient)
        canvas = np.full((H, W, 3), (245, 253, 248), dtype=np.uint8)
        img_pil = Image.fromarray(canvas)
        draw = ImageDraw.Draw(img_pil, "RGBA")

        # Top Bar
        draw_glass_panel(draw, (40, 24, W - 40, 80), fill=(255, 255, 255, 240), outline=(200, 235, 215, 255), radius=14)
        draw.rounded_rectangle((56, 38, 140, 66), radius=8, fill=(16, 185, 129, 255))
        draw.text((68, 43), "LARVIS", font=get_font(14, bold=True), fill=(255, 255, 255, 255))
        draw.text((155, 43), "● LIVE BENCHTOP SCIENTIST SCREEN RECORDING · CH01–CH12", font=font_title, fill=(15, 40, 30, 255))
        draw.rounded_rectangle((W - 240, 38, W - 56, 66), radius=8, fill=(240, 253, 244, 255), outline=(16, 185, 129, 180), width=1)
        draw.text((W - 225, 43), "STEP 05: LOAD SAMPLES", font=font_bold, fill=(5, 150, 105, 255))

        # Crop & place smartphone video
        # Phone video is vertical 1080x1920. Scale to 380x676 or fit inside 480x560
        f_h, f_w, _ = frame.shape
        crop_h = int(f_w * (540 / 460))
        crop_y1 = max(0, int(f_h * 0.25))
        crop_y2 = min(f_h, crop_y1 + crop_h)
        crop_frame = frame[crop_y1:crop_y2, :]
        resized_video = cv2.resize(crop_frame, (480, 560))

        # Paste video onto canvas
        video_x, video_y = 60, 105
        # Convert resized video (BGR) to RGB
        resized_video_rgb = cv2.cvtColor(resized_video, cv2.COLOR_BGR2RGB)
        img_pil.paste(Image.fromarray(resized_video_rgb), (video_x, video_y))

        # Dynamic Bounding Box on pipette tip in video
        # Pipette tips dips into well between t=2 and t=8
        cycle = (t % 6.0) / 6.0
        dip = math.sin(cycle * math.pi)
        box_y1 = int(video_y + 110 + dip * 130)
        box_y2 = box_y1 + 140
        box_x1 = video_x + 160
        box_x2 = box_x1 + 160

        draw.rounded_rectangle((box_x1, box_y1, box_x2, box_y2), radius=8, outline=(16, 185, 129, 255), width=3)
        # Bounding box tag
        draw.rounded_rectangle((box_x1, box_y1 - 26, box_x1 + 220, box_y1), radius=4, fill=(15, 23, 42, 220))
        draw.text((box_x1 + 8, box_y1 - 22), "micropipette tip · 10 µL", font=font_mono, fill=(52, 211, 153, 255))

        # Side Telemetry Panel (Right Side)
        panel_x = 580
        draw_glass_panel(draw, (panel_x, 105, W - 60, 580), fill=(255, 255, 255, 230), outline=(210, 240, 225, 255), radius=16)

        draw.text((panel_x + 28, 130), "REAL-TIME BENCH OBSERVATION", font=font_title, fill=(20, 50, 35, 255))
        draw.line((panel_x + 28, 165, W - 90, 165), fill=(230, 245, 235, 255), width=1)

        labels = [
            ("Active Protocol", "12-Ch Sandwich Immunoassay (CEA)"),
            ("Current Step", "step_05 · Load samples and standards (15 min)"),
            ("Target Vessel", "96-Well Microplate Well C04 -> Chip Inlet"),
            ("Aspiration Volume", "10.0 µL (Tolerance ±0.2 µL)"),
            ("Meniscus Stability", "99.4% · ZERO Bubble Ingress (Nominal)"),
            ("Channel Assignment", "CH01 to CH12 (Standards & Patient Sera)"),
            ("Vision Classifier", "LARVIS Kinematic Sceptic Pipeline v2")
        ]

        curr_y = 185
        for k, v in labels:
            draw.text((panel_x + 28, curr_y), k, font=font_reg, fill=(100, 116, 139, 255))
            draw.text((panel_x + 28, curr_y + 20), v, font=font_bold, fill=(15, 23, 42, 255))
            curr_y += 50

        # Subtitle glass toast at bottom
        draw_glass_panel(draw, (panel_x + 20, 595, W - 60, 680), fill=(16, 185, 129, 240), outline=(5, 150, 105, 255), radius=12)
        draw.text((panel_x + 36, 608), "🔊 LARVIS COPILOT (VOICE ACTIVE):", font=get_font(12, bold=True), fill=(255, 255, 255, 220))
        draw.text((panel_x + 36, 628), '"Tracking micropipette aspiration. Liquid meniscus stable at 10 µL."', font=font_bold, fill=(255, 255, 255, 255))

        out.write(cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR))

    cap.release()
    out.release()

    # Mux with audio using ffmpeg
    cmd = [
        FFMPEG, "-y",
        "-i", raw_video,
        "-i", src_audio,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_video
    ]
    subprocess.run(cmd, check=True)
    if os.path.exists(raw_video):
        os.remove(raw_video)
    print(f"Finished Video 1: {out_video} ({os.path.getsize(out_video)} bytes)")

# ==========================================
# VIDEO 2: LARVIS Bubble Obstruction Alert
# ==========================================
def render_video_2():
    print("Rendering Video 2: LARVIS Bubble Obstruction Alert & Protocol Change...")
    src_video = os.path.join(ASSETS, "real_microfluidics_bubbles.webm")
    src_audio = os.path.join(ASSETS, "voice_larvis_bubble_alert.wav")
    raw_video = os.path.join(TEMP_DIR, "v2_raw.mp4")
    out_video = os.path.join(ASSETS, "demo_2_larvis_bubble_critical_alert.mp4")

    cap = cv2.VideoCapture(src_video)
    fps = 24.0
    duration = 15.2  # seconds
    total_frames = int(fps * duration)
    W, H = 1280, 720

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_video, fourcc, fps, (W, H))

    font_title = get_font(20, bold=True)
    font_bold = get_font(16, bold=True)
    font_reg = get_font(14, bold=False)
    font_alert = get_font(18, bold=True)
    font_mono = get_font(13, bold=False)

    for i in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        t = i / fps
        canvas = np.full((H, W, 3), (245, 253, 248), dtype=np.uint8)
        img_pil = Image.fromarray(canvas)
        draw = ImageDraw.Draw(img_pil, "RGBA")

        # Top Bar
        draw_glass_panel(draw, (40, 24, W - 40, 80), fill=(255, 255, 255, 240), outline=(200, 235, 215, 255), radius=14)
        draw.rounded_rectangle((56, 38, 140, 66), radius=8, fill=(239, 68, 68, 255) if t > 3.0 else (16, 185, 129, 255))
        draw.text((68, 43), "LARVIS", font=get_font(14, bold=True), fill=(255, 255, 255, 255))
        status_text = "● CRITICAL CHANNEL OBSTRUCTION DETECTED · CH01" if t > 3.0 else "● 50,000 FPS MULTIPHASE MICROFLUIDIC INSPECTION"
        draw.text((155, 43), status_text, font=font_title, fill=(220, 38, 38, 255) if t > 3.0 else (15, 40, 30, 255))

        # Scale microfluidic video to fit (width 740, height 480)
        resized_video = cv2.resize(frame, (740, 480))
        video_x, video_y = 60, 105
        resized_video_rgb = cv2.cvtColor(resized_video, cv2.COLOR_BGR2RGB)
        img_pil.paste(Image.fromarray(resized_video_rgb), (video_x, video_y))

        # Microfluidic Bounding Boxes
        cycle = (t % 5.0) / 5.0
        b1_x = int(video_x + 90 + cycle * 500)
        b1_y = video_y + 140
        b1_w, b1_h = 130, 200

        # When bubble enters constriction (cycle between 0.35 and 0.70)
        is_critical = 0.30 <= cycle <= 0.75 or t > 3.5
        box_color = (239, 68, 68, 255) if is_critical else (16, 185, 129, 255)
        tag_text = "bubble #1 · 62% obs (CRITICAL)" if is_critical else "bubble #1 · 18% obs (nominal)"

        # Draw box
        draw.rounded_rectangle((b1_x, b1_y, b1_x + b1_w, b1_y + b1_h), radius=10, outline=box_color, width=3)
        draw.rounded_rectangle((b1_x, b1_y + b1_h, b1_x + 220, b1_y + b1_h + 26), radius=4, fill=(15, 23, 42, 230))
        draw.text((b1_x + 8, b1_y + b1_h + 4), tag_text, font=font_mono, fill=(248, 113, 113, 255) if is_critical else (52, 211, 153, 255))

        # Satellite bubble
        b2_x = video_x + 480
        b2_y = video_y + 180
        draw.rounded_rectangle((b2_x, b2_y, b2_x + 90, b2_y + 140), radius=8, outline=(245, 158, 11, 255), width=2)
        draw.text((b2_x + 6, b2_y + 145), "bubble #2 · 8% obs", font=font_mono, fill=(245, 158, 11, 255))

        # Right Side: Interactive Protocol Recovery Panel
        panel_x = 830
        draw_glass_panel(draw, (panel_x, 105, W - 50, 680), fill=(255, 255, 255, 245), outline=(254, 202, 202, 255) if is_critical else (210, 240, 225, 255), radius=16)

        # Alert Badge
        badge_bg = (254, 242, 242, 255) if is_critical else (240, 253, 244, 255)
        badge_border = (239, 68, 68, 255) if is_critical else (16, 185, 129, 255)
        draw.rounded_rectangle((panel_x + 24, 125, W - 74, 175), radius=10, fill=badge_bg, outline=badge_border, width=2)
        draw.text((panel_x + 40, 140), "⚠️ CRITICAL OBSTRUCTION (62%)", font=font_alert, fill=(185, 28, 28, 255) if is_critical else (5, 150, 105, 255))

        # Diagnostics details
        info_lines = [
            ("Affected Channel", "CH01 (CEA Calibrated Standard STD01)"),
            ("Obstruction Ratio", "62.4% (> 60.0% Critical Red Threshold)"),
            ("Sauter Diameter d32", "48.2 µm (Compressed Oblate Spheroid)"),
            ("Impacted Entities", "7 Downstream Calculations (Full Standard Curve)"),
            ("Antigen Binding Eff.", "Compromised: 100% -> 64.1%"),
            ("State Status", "Flagged 'pending_review' (Audit Locked)")
        ]

        curr_y = 195
        for k, v in info_lines:
            draw.text((panel_x + 24, curr_y), k, font=font_reg, fill=(100, 116, 139, 255))
            draw.text((panel_x + 24, curr_y + 18), v, font=font_bold, fill=(15, 23, 42, 255))
            curr_y += 46

        # Interactive Recovery Prompt & Action Buttons
        draw.text((panel_x + 24, 485), "LARVIS AUTONOMOUS RECOVERY PROMPT:", font=get_font(13, bold=True), fill=(185, 28, 28, 255))
        draw.text((panel_x + 24, 508), '"Would you like to adjust the protocol', font=font_bold, fill=(30, 41, 59, 255))
        draw.text((panel_x + 24, 530), 'or initiate bubble aspiration?"', font=font_bold, fill=(30, 41, 59, 255))

        # Button 1: Adjust Protocol
        draw.rounded_rectangle((panel_x + 24, 565, W - 74, 605), radius=8, fill=(16, 185, 129, 255))
        draw.text((panel_x + 50, 577), "✅ Adjust Protocol (-1.5 µL Wash / +3 min)", font=font_bold, fill=(255, 255, 255, 255))

        # Button 2: Initiate Bubble Aspiration
        draw.rounded_rectangle((panel_x + 24, 620, W - 74, 660), radius=8, fill=(37, 99, 235, 255))
        draw.text((panel_x + 50, 632), "🔬 Initiate Closed-Loop Aspiration", font=font_bold, fill=(255, 255, 255, 255))

        # Bottom Subtitle on Video
        draw_glass_panel(draw, (60, 600, 740 + 60, 680), fill=(15, 23, 42, 235), outline=(239, 68, 68, 200), radius=12)
        draw.text((78, 612), "🔊 LARVIS PROACTIVE ALERT (SIRI VOICE / DR. VANCE):", font=get_font(12, bold=True), fill=(248, 113, 113, 255))
        draw.text((78, 634), '"Warning from LARVIS: Critical channel obstruction detected in Channel 1. 62% blockage."', font=font_bold, fill=(255, 255, 255, 255))

        out.write(cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR))

    cap.release()
    out.release()

    cmd = [
        FFMPEG, "-y",
        "-i", raw_video,
        "-i", src_audio,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_video
    ]
    subprocess.run(cmd, check=True)
    if os.path.exists(raw_video):
        os.remove(raw_video)
    print(f"Finished Video 2: {out_video} ({os.path.getsize(out_video)} bytes)")

# ==========================================
# VIDEO 3: Voice Interaction "What is protocol today?"
# ==========================================
def render_video_3():
    print("Rendering Video 3: Voice Interaction (What is the protocol today?)...")
    src_audio = os.path.join(ASSETS, "voice_qa_full.wav")
    raw_video = os.path.join(TEMP_DIR, "v3_raw.mp4")
    out_video = os.path.join(ASSETS, "demo_3_larvis_protocol_today_voice_qa.mp4")

    fps = 24.0
    duration = 20.6  # seconds
    total_frames = int(fps * duration)
    W, H = 1280, 720

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_video, fourcc, fps, (W, H))

    font_title = get_font(22, bold=True)
    font_bold = get_font(16, bold=True)
    font_reg = get_font(14, bold=False)
    font_quote = get_font(18, bold=True)
    font_mono = get_font(13, bold=False)

    for i in range(total_frames):
        t = i / fps
        canvas = np.full((H, W, 3), (245, 253, 248), dtype=np.uint8)
        img_pil = Image.fromarray(canvas)
        draw = ImageDraw.Draw(img_pil, "RGBA")

        # Top Header Bar
        draw_glass_panel(draw, (40, 24, W - 40, 80), fill=(255, 255, 255, 240), outline=(200, 235, 215, 255), radius=14)
        draw.rounded_rectangle((56, 38, 140, 66), radius=8, fill=(16, 185, 129, 255))
        draw.text((68, 43), "LARVIS", font=get_font(14, bold=True), fill=(255, 255, 255, 255))
        draw.text((155, 43), "● BI-DIRECTIONAL HANDS-FREE LAB ASSISTANT · LIVE VOICE SESSION", font=font_title, fill=(15, 40, 30, 255))

        # Central Liquid Orb (Glowing pulsing 3D sphere)
        orb_x, orb_y = 260, 240
        orb_radius = 56 + int(math.sin(t * 6.0) * 6)
        # Pulse rings
        for ring_idx in range(3):
            ring_r = orb_radius + (ring_idx + 1) * 22 + int((t * 24) % 22)
            draw.ellipse((orb_x - ring_r, orb_y - ring_r, orb_x + ring_r, orb_y + ring_r),
                         outline=(16, 185, 129, max(0, 120 - ring_idx * 40)), width=2)
        # Orb body
        draw.ellipse((orb_x - orb_radius, orb_y - orb_radius, orb_x + orb_radius, orb_y + orb_radius),
                     fill=(16, 185, 129, 255), outline=(5, 150, 105, 255), width=3)
        # High-gloss specular highlight
        draw.ellipse((orb_x - int(orb_radius * 0.4), orb_y - int(orb_radius * 0.5),
                      orb_x - int(orb_radius * 0.1), orb_y - int(orb_radius * 0.2)),
                     fill=(255, 255, 255, 220))

        # Dialogue Cards Area
        is_scientist_turn = t < 3.2

        # Card 1: Scientist Utterance (Voice In)
        draw_glass_panel(draw, (440, 110, W - 60, 205),
                         fill=(240, 253, 244, 255) if is_scientist_turn else (255, 255, 255, 200),
                         outline=(16, 185, 129, 255) if is_scientist_turn else (226, 232, 240, 255),
                         radius=14)
        draw.text((465, 125), "🎙️ SCIENTIST (VOICE INPUT):", font=get_font(13, bold=True), fill=(5, 150, 105, 255) if is_scientist_turn else (100, 116, 139, 255))
        draw.text((465, 152), '"Hi LARVIS, what is the protocol today?"', font=font_quote, fill=(15, 23, 42, 255))

        # Card 2: LARVIS Response (Speech Out)
        is_larvis_turn = t >= 3.2
        draw_glass_panel(draw, (440, 225, W - 60, 370),
                         fill=(255, 255, 255, 255) if is_larvis_turn else (248, 250, 252, 160),
                         outline=(16, 185, 129, 255) if is_larvis_turn else (226, 232, 240, 255),
                         radius=14)
        draw.text((465, 240), "🔊 LARVIS (AUTONOMOUS COPILOT VOICE):", font=get_font(13, bold=True), fill=(5, 150, 105, 255) if is_larvis_turn else (100, 116, 139, 255))
        if is_larvis_turn:
            draw.text((465, 270), '"Hello, Scientist. Today\'s protocol is the 12-channel Microfluidic', font=font_bold, fill=(15, 23, 42, 255))
            draw.text((465, 296), 'Sandwich Immunoassay for Carcinoembryonic Antigen (CEA).', font=font_bold, fill=(15, 23, 42, 255))
            draw.text((465, 322), 'We are on Step 5: Loading samples and standards for 15-minute incubation."', font=font_bold, fill=(5, 150, 105, 255))
        else:
            draw.text((465, 285), '(Listening to researcher utterance via Gemini Live / WebAudio)...', font=font_reg, fill=(148, 163, 184, 255))

        # Bottom Protocol Timeline & Channel Matrix
        timeline_y = 395
        draw_glass_panel(draw, (60, timeline_y, W - 60, H - 40), fill=(255, 255, 255, 240), outline=(210, 240, 225, 255), radius=16)

        draw.text((85, timeline_y + 20), "PROTOCOL EXECUTION TIMELINE · 9-STEP CEA ASSAY", font=font_title, fill=(20, 50, 35, 255))

        steps = [
            ("Step 1: Block", "10 min", True),
            ("Step 2: Wash", "3 min", True),
            ("Step 3: Capture Ab", "15 min", True),
            ("Step 4: Wash", "3 min", True),
            ("Step 5: Load Samples", "15 min (ACTIVE)", False),
            ("Step 6: Wash", "3 min", False),
            ("Step 7: Detection Ab", "10 min", False),
            ("Step 8: Wash", "3 min", False),
            ("Step 9: Readout", "Fluorescence", False)
        ]

        step_w = 115
        start_x = 85
        for s_idx, (s_name, s_dur, s_done) in enumerate(steps):
            sx = start_x + s_idx * 128
            sy = timeline_y + 70
            is_active = (s_idx == 4)

            # Box
            if s_done:
                box_bg = (240, 253, 244, 255)
                box_border = (16, 185, 129, 200)
            elif is_active:
                box_bg = (16, 185, 129, 255) if is_larvis_turn else (240, 253, 244, 255)
                box_border = (5, 150, 105, 255)
            else:
                box_bg = (248, 250, 252, 255)
                box_border = (226, 232, 240, 255)

            draw.rounded_rectangle((sx, sy, sx + step_w, sy + 75), radius=8, fill=box_bg, outline=box_border, width=2 if is_active else 1)

            text_color = (255, 255, 255, 255) if (is_active and is_larvis_turn) else (15, 23, 42, 255)
            sub_color = (220, 252, 231, 255) if (is_active and is_larvis_turn) else (100, 116, 139, 255)

            draw.text((sx + 8, sy + 10), s_name, font=get_font(12, bold=True), fill=text_color)
            draw.text((sx + 8, sy + 32), s_dur, font=get_font(11, bold=False), fill=sub_color)
            if s_done:
                draw.text((sx + 8, sy + 52), "✓ Verified", font=get_font(10, bold=True), fill=(16, 185, 129, 255))
            elif is_active:
                draw.text((sx + 8, sy + 52), "● RUNNING", font=get_font(10, bold=True), fill=(255, 255, 255, 255) if is_larvis_turn else (16, 185, 129, 255))

        # Channel mapping chip list at the bottom
        draw.text((85, timeline_y + 175), "12-Channel Microfluidic Layout:", font=font_bold, fill=(71, 85, 105, 255))
        draw.text((320, timeline_y + 176), "CH01–CH05: Standards STD01–05  |  CH06: Blank (STD00)  |  CH07–CH12: Patient Sera S01–S06", font=font_mono, fill=(15, 23, 42, 255))

        out.write(cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR))

    out.release()

    cmd = [
        FFMPEG, "-y",
        "-i", raw_video,
        "-i", src_audio,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_video
    ]
    subprocess.run(cmd, check=True)
    if os.path.exists(raw_video):
        os.remove(raw_video)
    print(f"Finished Video 3: {out_video} ({os.path.getsize(out_video)} bytes)")

if __name__ == "__main__":
    render_video_1()
    render_video_2()
    render_video_3()
    print("ALL 3 VIDEOS SUCCESSFULLY GENERATED!")
