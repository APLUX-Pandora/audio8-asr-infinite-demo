"""Feed source PCM chunks and explicitly finish the recording."""
import soundfile as sf
from pandora_audio8_asr_infinite import ASRModel

# Both packages use these same scripts. Select a package here.
MODEL_DIR = "models"
AUDIO = "examples/audio/speech.wav"

with sf.SoundFile(AUDIO) as audio:
    with ASRModel.from_pretrained(MODEL_DIR) as model:
        with model.create_stream(sample_rate=audio.samplerate,
                                 channels=audio.channels, language='en') as stream:
            while True:
                pcm = audio.read(1600, dtype="float32", always_2d=True)
                if len(pcm) == 0:
                    break
                update = stream.feed(pcm)
                print(update.delta, end="", flush=True)
                if update.finish_reason is not None:
                    break
            result = stream.finish()
            print("\nFinal transcript:", result.text)
