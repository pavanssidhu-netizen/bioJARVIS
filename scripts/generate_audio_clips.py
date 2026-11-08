import subprocess
import os

script_dir = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\scripts"
output_dir = r"C:\Users\Yeeye\.gemini\antigravity\scratch\bioJARVIS\app\build\web\assets"

audio_scripts = {
    "voice_larvis_bubble_alert.wav": (
        "Warning from LARVIS: Critical channel obstruction detected in Channel 1. "
        "62 percent blockage. Antigen binding efficiency compromised to 64 percent. "
        "Would you like to adjust the protocol or initiate bubble aspiration?"
    ),
    "voice_scientist_question.wav": (
        "Hi LARVIS, what is the protocol today?"
    ),
    "voice_larvis_protocol_answer.wav": (
        "Hello, Scientist. Today's protocol is the 12-channel Microfluidic Sandwich Immunoassay "
        "for Carcinoembryonic Antigen, CEA. We are on Step 5: Loading samples and standards "
        "into channels CH01 through CH12 for a 15-minute incubation."
    ),
    "voice_larvis_pipette_bench.wav": (
        "LARVIS benchtop copilot active. Tracking micropipette aspiration in 96-well plate. "
        "Liquid meniscus confirmed stable at 10 microlitres. Zero bubble ingress. You are clear to dispense."
    )
}

for filename, text in audio_scripts.items():
    vbs_path = os.path.join(script_dir, "gen_temp.vbs")
    wav_path = os.path.join(output_dir, filename)
    vbs_content = f'''Set speaker = CreateObject("SAPI.SpVoice")
Set fileStream = CreateObject("SAPI.SpFileStream")
fileStream.Open "{wav_path.replace(chr(92), chr(92)+chr(92))}", 3
Set speaker.AudioOutputStream = fileStream
speaker.Rate = 2
speaker.Speak "{text.replace('"', '""')}"
fileStream.Close
'''
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs_content)
    subprocess.run(["cscript", "//nologo", vbs_path], check=True)
    if os.path.exists(vbs_path):
        os.remove(vbs_path)
    print(f"Generated {filename} ({os.path.getsize(wav_path)} bytes)")
