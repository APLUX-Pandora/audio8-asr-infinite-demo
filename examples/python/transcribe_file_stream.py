"""Submit a complete audio file and print incremental text updates."""
from pandora_audio8_asr_infinite import ASRModel

# Both packages use this same script. Select a package here.
MODEL_DIR = "models"
AUDIO = "examples/audio/speech.wav"

with ASRModel.from_pretrained(MODEL_DIR) as model:
    with model.transcribe_stream(AUDIO, language='en') as stream:
        for update in stream:
            print(update.delta, end="", flush=True)
        result = stream.result
        print("\nFinal transcript:", result.text)
