"""Audio8 models.json packaging contract; no inference or application policy."""
import json
import stat
from pathlib import Path, PurePosixPath

# Resource roles are model semantics; file names and locations come only from models.json.
COMMON_ROLES = {
    'config': ('frontend_config',), 'rows_const': ('audio_constants',),
    'mel_filters': ('mel_filters',), 'token_bytes': ('vocabulary',),
    'encoder_prefix_kv': ('prefix', 'encoder'), 'decoder_prefix_kv_zh': ('prefix', 'decoder_zh'),
    'decoder_prefix_kv_en': ('prefix', 'decoder_en'), 'embedding': ('token_vectors', 'path'),
    'rotation': ('rotation',), 'vad_W': ('semantic_vad', 'weight'),
    'vad_b': ('semantic_vad', 'bias'), 'vad_meta': ('semantic_vad', 'config'),
}
VOCABULARY_SIZE = 151936  # Native loading checks that the token table has this many entries.
GRAPH_ROLES = ('encoder', 'adapter', 'decoder_1', 'decoder_2')
SOCS = {603: 'qcs8550', 702: 'qcs8625', 675: 'qcs8275', 676: 'qcs9075'}


def _soc_id():
    try:
        return int(Path('/sys/devices/soc0/soc_id').read_text(encoding='ascii').strip())
    except (OSError, ValueError):
        return -1


def _file_size(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def contained(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('invalid relative model path')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('.', '..') for x in name.split('/')) or str(p) != name:
        raise ValueError('invalid relative model path')
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('model resource escapes package root: ' + name)
    return path


def inspect(root):
    root = Path(root)
    try:
        doc = json.loads((root / 'models.json').read_text(encoding='utf-8'))
        clock = doc['audio_clock_ms']
        if (type(doc['format_version']) is not int or doc['format_version'] != 2
                or type(clock) is not int or clock not in (80, 160)
                or doc['model_name'] != f'Audio8-ASR-Infinite-{clock}ms'):
            raise ValueError('unsupported models.json format, model identity or audio clock')
        resources = doc['resources']
        spec = resources['token_vectors']
        if (spec['dtype'] != 'float32-le' or not isinstance(spec['shape'], list)
                or len(spec['shape']) != 2 or any(type(d) is not int for d in spec['shape'])
                or spec['shape'] != [VOCABULARY_SIZE, 2048]
                or spec['layout'] != 'row-major'):
            raise ValueError('unsupported embedding metadata')
        layout = {}
        for role, keys in COMMON_ROLES.items():
            value = resources
            for key in keys:
                value = value[key]
            contained(root, value)
            layout[role] = value
        tokenizer = resources['tokenizer']
        if _file_size(contained(root, tokenizer)) <= 0:
            raise ValueError('missing or empty tokenizer resource')
        soc_id = _soc_id()
        local = SOCS.get(soc_id)
        declared, available = set(), {}
        if not isinstance(doc['targets'], list):
            raise ValueError('models.json targets must be a list')
        for target in doc['targets']:
            if target['soc'] not in SOCS.values() or target['qnn_version'] != '2.48':
                raise ValueError('unsupported SoC or QNN version')
            tid = target['soc'] + '_qnn248'
            folder = target['directory']
            if tid in declared:
                raise ValueError('invalid or duplicate model target')
            declared.add(tid)
            target_root = contained(root, folder).resolve()
            files = {role: target['files'][role] for role in GRAPH_ROLES}
            paths = [contained(root, name) for name in files.values()]
            for path in paths:
                if path.suffix != '.aidem':
                    raise ValueError('matching AIDEM graph resources are required')
                if not path.resolve().is_relative_to(target_root):
                    raise ValueError('graph resource is outside its declared target directory')
            if all(_file_size(path) > 0 for path in paths):
                available[target['soc']] = files
        selected = available.get(local)
        if selected is None and local == 'qcs8275':
            selected = available.get('qcs8625')
        if selected is None:
            found = ', '.join(soc + '_qnn248' for soc in available) or 'none'
            device = local or f'ID {soc_id}'
            raise ValueError(f'no complete model target for local SoC {device}; complete targets found: {found}')
        for role in ('encoder_prefix_kv', 'decoder_prefix_kv_zh', 'decoder_prefix_kv_en'):
            if PurePosixPath(layout[role]).suffix in ('.aidem', '.pdm'):
                raise ValueError('prefix must be an ordinary KV resource')
        for role, name in layout.items():
            size = _file_size(root / name)
            if size <= 0:
                raise ValueError('missing or empty model file: ' + name)
            if role == 'embedding' and size != VOCABULARY_SIZE * 2048 * 4:
                raise ValueError('incorrect-size embedding.bin')
        layout.update(selected)
        return {'format': 3, 'clocks': {str(clock): layout},
                'extras': {'tokenizer': tokenizer}}
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError('missing or invalid models.json package: ' + str(error)) from error
