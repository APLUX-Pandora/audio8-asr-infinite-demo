"""Decode audio uploads to a single browser- and SDK-compatible PCM format."""
import subprocess
import wave

AUDIO_FORMATS = {".wav": "wav", ".mp3": "mp3", ".flac": "flac", ".m4a": "mov",
                 ".aac": "aac", ".ogg": "ogg", ".opus": "ogg"}
MAX_AUDIO_UPLOAD_BYTES = 256 * 1024**2
MAX_AUDIO_FILE_S = 30 * 60


def normalize_audio(source, destination, extension):
    """Write mono 16 kHz WAV, or return an error suitable for the upload form."""
    demuxer = ["-protocol_whitelist", "file", "-f", AUDIO_FORMATS[extension]]
    try:
        video = subprocess.run(
            ["ffprobe", "-v", "error", *demuxer, "-select_streams", "V",
             "-show_entries", "stream=index", "-of", "csv=p=0", source],
            capture_output=True, text=True, timeout=30, check=True,
        )
        if video.stdout.strip():
            return "This file has a video track. Use Upload video."
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-xerror", *demuxer, "-i", source,
             "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
             "-t", str(MAX_AUDIO_FILE_S + 1), "-f", "wav", "-y", destination],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True,
        )
        with wave.open(destination, "rb") as decoded:
            samples = decoded.getnframes()
            if samples > MAX_AUDIO_FILE_S * decoded.getframerate():
                return "Audio files must be 30 minutes or shorter."
            if samples:
                return None
    except subprocess.TimeoutExpired:
        return "Audio decoding timed out. Try a shorter file."
    except (subprocess.CalledProcessError, wave.Error, EOFError):
        pass
    return "Could not decode this audio file. Try WAV, MP3, FLAC, M4A, AAC, Ogg or Opus."
