"""Minimal dependency-free audio I/O for filter impulse responses.

Handles the formats rePhase / REW / BruteFIR actually use around here:
  * WAV: PCM 8/16/24/32 bit integer, IEEE float 32/64 bit, mono or multi
  * RAW: headerless samples, format chosen by the caller
  * TXT: one sample per line
"""

import os
import struct

import numpy as np

# name -> (numpy dtype, bits, is_float)
RAW_FORMATS = {
    'float32': ('<f4', 32, True),
    'float64': ('<f8', 64, True),
    'int32': ('<i4', 32, False),
    'int24': (None, 24, False),
    'int16': ('<i2', 16, False),
}
WAV_FORMATS = ['float32', 'float64', 'int32', 'int24', 'int16']

_FMT_PCM = 1
_FMT_FLOAT = 3
_FMT_EXT = 0xFFFE


def _int24_to_float(raw):
    n = len(raw) // 3
    b = np.frombuffer(raw[:n * 3], dtype=np.uint8).reshape(n, 3).astype(np.int32)
    v = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16))
    v = np.where(v & 0x800000, v - 0x1000000, v)
    return v.astype(np.float64) / (2.0 ** 23)


def _float_to_int24(x):
    v = np.clip(np.rint(x * (2.0 ** 23 - 1)), -(2 ** 23), 2 ** 23 - 1)
    v = v.astype(np.int32) & 0xFFFFFF
    out = np.empty((len(v), 3), dtype=np.uint8)
    out[:, 0] = v & 0xFF
    out[:, 1] = (v >> 8) & 0xFF
    out[:, 2] = (v >> 16) & 0xFF
    return out.tobytes()


def read_wav(path):
    """-> (samples float64 [n, channels], sample_rate, description)."""
    with open(path, 'rb') as fh:
        b = fh.read()
    if len(b) < 12 or b[:4] != b'RIFF' or b[8:12] != b'WAVE':
        raise ValueError(f'{os.path.basename(path)}: not a RIFF/WAVE file')
    i, fmt, data = 12, None, None
    while i + 8 <= len(b):
        cid = b[i:i + 4]
        size = struct.unpack('<I', b[i + 4:i + 8])[0]
        body = b[i + 8:i + 8 + size]
        if cid == b'fmt ' and len(body) >= 16:
            fmt = struct.unpack('<HHIIHH', body[:16])
            if fmt[0] == _FMT_EXT and len(body) >= 26:
                sub = struct.unpack('<H', body[24:26])[0]
                fmt = (sub,) + fmt[1:]
        elif cid == b'data':
            data = body
        i += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError(f'{os.path.basename(path)}: missing fmt or data chunk')
    tag, ch, rate, _, _, bits = fmt
    if tag == _FMT_FLOAT and bits == 32:
        x, desc = np.frombuffer(data, '<f4').astype(np.float64), 'float32'
    elif tag == _FMT_FLOAT and bits == 64:
        x, desc = np.frombuffer(data, '<f8').copy(), 'float64'
    elif tag == _FMT_PCM and bits == 32:
        x, desc = np.frombuffer(data, '<i4') / 2.0 ** 31, 'int32'
    elif tag == _FMT_PCM and bits == 24:
        x, desc = _int24_to_float(data), 'int24'
    elif tag == _FMT_PCM and bits == 16:
        x, desc = np.frombuffer(data, '<i2') / 2.0 ** 15, 'int16'
    elif tag == _FMT_PCM and bits == 8:
        x, desc = (np.frombuffer(data, 'u1').astype(np.float64) - 128) / 128, 'uint8'
    else:
        raise ValueError(f'{os.path.basename(path)}: unsupported WAV format '
                         f'(tag {tag}, {bits} bit)')
    ch = max(1, ch)
    x = np.asarray(x, dtype=np.float64)
    x = x[:len(x) - (len(x) % ch)].reshape(-1, ch)
    return x, int(rate), f'WAV {desc}, {ch} ch, {rate} Hz, {x.shape[0]} samples'


def read_raw(path, fmt='float32', channels=1):
    """Headerless samples -> (samples float64 [n, channels], description)."""
    if fmt not in RAW_FORMATS:
        raise ValueError(f'unknown raw format {fmt}')
    with open(path, 'rb') as fh:
        b = fh.read()
    if fmt == 'int24':
        x = _int24_to_float(b)
    else:
        dt, bits, is_float = RAW_FORMATS[fmt]
        n = len(b) // np.dtype(dt).itemsize
        x = np.frombuffer(b, dt, count=n).astype(np.float64)
        if not is_float:
            x = x / float(2 ** (bits - 1))
    ch = max(1, channels)
    x = x[:len(x) - (len(x) % ch)].reshape(-1, ch)
    return x, f'RAW {fmt}, {ch} ch, {x.shape[0]} samples'


def guess_raw_format(path):
    """Cheap heuristic: valid float32 data stays finite and roughly in +-8."""
    with open(path, 'rb') as fh:
        b = fh.read(1 << 20)
    for fmt, dt in (('float32', '<f4'), ('float64', '<f8')):
        n = len(b) // np.dtype(dt).itemsize
        if n < 16:
            continue
        v = np.frombuffer(b, dt, count=n)
        if np.all(np.isfinite(v)) and np.max(np.abs(v)) < 8.0:
            return fmt
    return 'int32'


def read_txt(path):
    x = np.loadtxt(path)
    if x.ndim > 1:
        x = x[:, 0]
    return x.reshape(-1, 1), f'TXT, {len(x)} samples'


def read_ir(path, raw_fmt='float32', raw_rate=48000, channels=1):
    """Read any supported impulse-response file -> (mono float64, fs, desc)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.wav':
        x, fs, desc = read_wav(path)
    elif ext in ('.txt', '.dat', '.csv'):
        x, desc = read_txt(path)
        fs = raw_rate
    else:
        x, desc = read_raw(path, raw_fmt, channels)
        fs = raw_rate
    return x[:, 0].copy(), fs, desc


def _to_int(x, bits):
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    scale = 1.0
    if peak > 1.0:
        scale = 1.0 / peak
    full = 2 ** (bits - 1) - 1
    return np.clip(np.rint(x * scale * full), -full - 1, full), scale


def write_wav(path, x, fs, fmt='float32'):
    """Write mono float64 samples as a WAV in the requested sample format."""
    x = np.asarray(x, dtype=np.float64).ravel()
    scale = 1.0
    if fmt == 'float32':
        body, tag, bits = x.astype('<f4').tobytes(), _FMT_FLOAT, 32
    elif fmt == 'float64':
        body, tag, bits = x.astype('<f8').tobytes(), _FMT_FLOAT, 64
    elif fmt == 'int32':
        v, scale = _to_int(x, 32)
        body, tag, bits = v.astype('<i4').tobytes(), _FMT_PCM, 32
    elif fmt == 'int24':
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        scale = 1.0 / peak if peak > 1.0 else 1.0
        body, tag, bits = _float_to_int24(x * scale), _FMT_PCM, 24
    elif fmt == 'int16':
        v, scale = _to_int(x, 16)
        body, tag, bits = v.astype('<i2').tobytes(), _FMT_PCM, 16
    else:
        raise ValueError(f'unsupported WAV output format {fmt}')
    ch, ba = 1, bits // 8
    fmt_chunk = struct.pack('<HHIIHH', tag, ch, int(fs), int(fs) * ba, ba, bits)
    chunks = b'fmt ' + struct.pack('<I', len(fmt_chunk)) + fmt_chunk
    if tag == _FMT_FLOAT:
        chunks += b'fact' + struct.pack('<II', 4, len(x))
    chunks += b'data' + struct.pack('<I', len(body)) + body
    if len(body) & 1:
        chunks += b'\0'
    with open(path, 'wb') as fh:
        fh.write(b'RIFF' + struct.pack('<I', 4 + len(chunks)) + b'WAVE' + chunks)
    return scale


def write_raw(path, x, fmt='float32'):
    """Write mono float64 samples headerless in the requested format."""
    x = np.asarray(x, dtype=np.float64).ravel()
    scale = 1.0
    if fmt == 'float32':
        body = x.astype('<f4').tobytes()
    elif fmt == 'float64':
        body = x.astype('<f8').tobytes()
    elif fmt == 'int24':
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        scale = 1.0 / peak if peak > 1.0 else 1.0
        body = _float_to_int24(x * scale)
    elif fmt in ('int32', 'int16'):
        bits = 32 if fmt == 'int32' else 16
        v, scale = _to_int(x, bits)
        body = v.astype('<i4' if bits == 32 else '<i2').tobytes()
    else:
        raise ValueError(f'unsupported raw output format {fmt}')
    with open(path, 'wb') as fh:
        fh.write(body)
    return scale


def write_txt(path, x):
    with open(path, 'w', encoding='utf-8') as fh:
        for v in np.asarray(x).ravel():
            fh.write(f'{v:.15g}\n')
    return 1.0
