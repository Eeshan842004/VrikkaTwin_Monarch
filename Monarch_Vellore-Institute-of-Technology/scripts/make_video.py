"""Narrated overview video from the slides -> deliverables/VrikkaTwin_overview.mp4 (a draft; the live demo recording
follows docs/VIDEO_SCRIPT.md).

    python scripts/make_video.py        # needs PowerPoint (slide export) and internet (gTTS) at build time

Each slide is shown for as long as its narration lasts. Narration numbers are read from reports/*.json, like the slides.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import av
import numpy as np
from gtts import gTTS
from PIL import Image

from vrikka.config import PROJECT_ROOT, REPORTS_DIR

OUT = PROJECT_ROOT / "deliverables"
W, H, FPS, RATE, PAD_S = 1280, 720, 2, 24000, 0.8


def R(name: str) -> dict:
    return json.loads((REPORTS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def narration() -> list[str]:
    demo, r1, r3, r4 = R("demo_numbers"), R("r1_validation"), R("r3_tawam"), R("r4_pmdata")
    k = demo["scenarios"]["S1_kamala"]
    w = list(k["whatif_72h_risk"].values())
    ev = R("fastclock_eval_mismatched")
    ops = [ev[s]["M_hybrid_core25"]["alerts"]["sensitivity_red"] for s in ("internal_test_2024", "test_2025",
                                                                            "test_2026")]
    return [
        "VrikkaTwin, from Team Monarch at VIT. A kidney digital twin that warns of kidney injury during heatwaves and "
        "sick days, up to three days ahead, for people with high blood pressure and kidney disease. Everything shown "
        "uses synthetic or fictional people.",
        "The problem. In India's 2024 heat season, surveillance recorded tens of thousands of suspected heatstroke "
        "cases. A blood pressure tablet, a water tablet and a painkiller together raise the risk of kidney injury, "
        "and the injury is silent at home.",
        "How it works. Observed data only feed a personal twin. It simulates the next three days on the weather "
        "forecast, a calibrated model explains the risk, and every action passes safety rules and one trust layer.",
        "The twin is an unscented Kalman filter over body water and creatinine, updated every morning from weight and "
        "resting heart rate. Every morning it simulates the next seventy-two hours many times and applies the same "
        "kidney injury rule used for the labels.",
        f"Kamala is fictional. On a blood pressure tablet, a water tablet and Combiflam, with a fever, her twin turns "
        f"red the morning before her simulated injury. Swapping the painkiller lowers her risk from about "
        f"{round(100 * w[0])} percent to about {round(100 * w[1])} percent, and adding oral rehydration brings it "
        "below a few percent. Medicine pauses come last, and the doctor decides.",
        "The slow clock shows long-term kidney function as ranges, never a single number. One injury this season is "
        "associated with a lower range ten years out.",
        "Safety comes first. Red flags run before any model: a person who may have heatstroke is told to call 108 or "
        "112, and no kidney score is shown. Guardrails cover rehydration salts, paracetamol, potassium and heart "
        "failure.",
        "Trust by construction. Every read checks the role and a signed consent artefact and is written to a "
        "hash-chained, signed audit log. Device readings that are implausible or replayed are rejected.",
        f"Results on the synthetic world. Our pre-registered rule says the hybrid model leads, because it beats the "
        f"simple baselines. But a plain LightGBM beats it on the mismatched world, and we say so. Red alerts caught "
        f"between {round(100 * min(ops))} and {round(100 * max(ops))} percent of injuries. Our lead-time target was "
        "missed.",
        f"Reality checks. Our labelling agreed with the official MIMIC code {r1['R1a']['agreement_pct']} percent of "
        f"the time. Carrying the last creatinine forward beat our filter. On the Tawam cohort the slow clock ranked "
        f"risk as well as eGFR alone. On {r4['people']} healthy people it raised "
        f"{'no' if r4['red_notifications_per_100_patient_days'] == 0 else 'some'} red alerts.",
        "Robustness. With the model frozen, we removed wearables, made everyone Tier zero, dropped data, doubled "
        "noise and gave a perfect forecast, and we screened every assumption in the registry. All results are in the "
        "repository.",
        "What we do not claim. This is synthetic validation only, creatinine rises only after filtration falls, and "
        f"some checks failed. The {r3['patients']}-patient Tawam check and the others are reported as they came out. "
        "It is not a medical device.",
        "Try it locally with Streamlit. Every number in the app, the README and these slides is read from the report "
        "files. Thank you.",
    ]


def export_slides(pptx: Path, folder: Path) -> list[Path]:
    ps = (f"$pp = New-Object -ComObject PowerPoint.Application; $p = $pp.Presentations.Open('{pptx}', $true, $false, "
          f"$false); foreach ($i in 1..$p.Slides.Count) {{ $p.Slides.Item($i).Export('{folder}\\s' + $i + '.png', "
          f"'PNG', {W}, {H}) }}; $p.Close(); $pp.Quit()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=600)
    return sorted(folder.glob("s*.png"), key=lambda p: int(p.stem[1:]))


def speech(text: str, path: Path) -> np.ndarray:
    gTTS(text, lang="en", tld="co.in").save(str(path))
    res = av.AudioResampler(format="flt", layout="mono", rate=RATE)
    chunks = []
    with av.open(str(path)) as c:
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
    return np.concatenate(chunks)


def main() -> int:
    pptx = OUT / "VrikkaTwin_slides.pptx"
    texts = narration()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        slides = export_slides(pptx, tmp)
        if len(slides) != len(texts):
            print(f"{len(slides)} slides but {len(texts)} narrations; rebuild the slides first")
            return 1
        audio, images = [], []
        for i, (img, txt) in enumerate(zip(slides, texts, strict=True)):
            a = speech(txt, tmp / f"n{i}.mp3")
            frames = int(np.ceil((len(a) / RATE + PAD_S) * FPS))          # whole video frames for this slide
            a = np.concatenate([a, np.zeros(frames * RATE // FPS - len(a), dtype=np.float32)])   # audio = video
            audio.append(a)
            images.append((Image.open(img).convert("RGB").resize((W, H)), frames / FPS))
            print(f"slide {i + 1}: {len(a) / RATE:.1f} s", flush=True)
        out = OUT / "VrikkaTwin_overview.mp4"
        with av.open(str(out), "w") as c:
            vs = c.add_stream("libx264", rate=FPS)
            vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
            vs.options = {"crf": "28", "preset": "medium"}
            ast = c.add_stream("aac", rate=RATE)
            ast.layout = "mono"
            for img, dur in images:
                frame = av.VideoFrame.from_image(img)
                for _ in range(round(dur * FPS)):
                    for p in vs.encode(frame):
                        c.mux(p)
            for p in vs.encode():
                c.mux(p)
            pcm = np.concatenate(audio).astype(np.float32)
            n = 1024
            for j in range(0, len(pcm), n):
                block = pcm[j:j + n]
                if len(block) < n:
                    block = np.pad(block, (0, n - len(block)))
                af = av.AudioFrame.from_ndarray(block.reshape(1, -1), format="fltp", layout="mono")
                af.sample_rate = RATE
                af.pts = j
                for p in ast.encode(af):
                    c.mux(p)
            for p in ast.encode():
                c.mux(p)
        total = sum(d for _, d in images)
        print(f"wrote {out} ({total / 60:.1f} min, {out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
