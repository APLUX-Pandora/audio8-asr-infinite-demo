"""Transcribe floating PCM with its source sampling rate."""
import soundfile as sf
from pandora_audio8_asr_infinite import ASRModel

# Both packages use these same scripts. Select a package here.
MODEL_DIR = "models"
AUDIO = "examples/audio/speech.wav"

pcm, sample_rate = sf.read(AUDIO, dtype="float32")
with ASRModel.from_pretrained(MODEL_DIR) as model:
    result = model.transcribe(pcm, sample_rate=sample_rate, language='en')
    print(result.text)
