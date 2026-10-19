"""Pre-generate the spoken messages for the Patient / Family page (EN / HI / KN / TE) -> app/assets/audio/<lang>/.

    python scripts/pregenerate_tts.py

The hosted app never synthesises speech live (and never runs live speech recognition): the audio files are made once
here from config/i18n/<lang>.yaml with gTTS (needs internet at build time) and committed. HI / KN / TE text is a draft
translation awaiting native-speaker review, so the audio is too. Writes app/assets/audio/manifest.json.
"""
from __future__ import annotations

import json
import sys

from gtts import gTTS

from vrikka.config import PROJECT_ROOT
from vrikka.i18n import LANGUAGES, strings

OUT = PROJECT_ROOT / "app" / "assets" / "audio"
LEVELS = ("green", "amber", "red", "purple")
FLAGS = ("redflag.heatstroke.body", "redflag.kidney_test_today.body", "redflag.vomiting_review.body")


def messages(lang: str) -> dict[str, str]:
    s = strings(lang)
    out = {f"level_{lv}": f"{s[f'level.{lv}']}. {s[f'action.{lv}']}" for lv in LEVELS}
    out.update({k.replace(".", "_"): s[k] for k in FLAGS})
    return out


def main() -> int:
    manifest = {}
    for lang in LANGUAGES:
        (OUT / lang).mkdir(parents=True, exist_ok=True)
        for name, text in messages(lang).items():
            f = OUT / lang / f"{name}.mp3"
            gTTS(text, lang=lang).save(str(f))
            manifest[f"{lang}/{name}"] = {"file": f"{lang}/{name}.mp3", "text": text}
            print(lang, name, flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
