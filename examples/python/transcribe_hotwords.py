"""Transcribe a bounded excerpt with request-specific hotword hints."""
import soundfile as sf
from pandora_audio8_asr_infinite import ASRModel

# Both profiles use this script. Select the package and your input here.
MODEL_DIR = "models"
AUDIO = "examples/audio/speech.wav"
EXCERPT_SECONDS = 30
# Replace these phrases with hints relevant to your recording.
HOTWORDS = ["quick brown fox", "speech recognition"]

# Limit the example to a short excerpt.
with sf.SoundFile(AUDIO) as source:
    sample_rate = source.samplerate
    pcm = source.read(frames=EXCERPT_SECONDS * sample_rate, dtype="float32")

with ASRModel.from_pretrained(MODEL_DIR) as model:
    result = model.transcribe(
        pcm, sample_rate=sample_rate, language="en", hotwords=HOTWORDS
    )
    print(result.text)
