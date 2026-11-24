"""Check model files before the web application switches engines."""
from pathlib import Path

from pandora_audio8_asr_infinite import A8Error, installed_clocks


class PackageVerifier:
    def __init__(self, model_dir):
        self.root = Path(model_dir)

    def error(self, clock):
        """Return a reason if this clock cannot be loaded."""
        return self.available()[1].get(str(clock))

    def available(self):
        try:
            clocks = [str(clock) for clock in installed_clocks(self.root)]
            return clocks, {clock: 'audio clock is not installed' for clock in ('160', '80')
                            if clock not in clocks}
        except A8Error as error:
            return [], {clock: str(error) for clock in ('160', '80')}
