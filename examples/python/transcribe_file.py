"""Transcribe a local file using the installed public SDK."""
from pandora_audio8_asr_infinite import ASRModel

# Both packages use these same scripts. Select a package here.
MODEL_DIR = "models"
AUDIO = "examples/audio/speech.wav"

with ASRModel.from_pretrained(MODEL_DIR) as model:
    # The bundled recording is English. Omit language for a Chinese file.
    result = model.transcribe(AUDIO, language='en')
    print(result.text)
