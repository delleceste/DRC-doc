import numpy as np, struct

FS=48000.0; N=131072; DF=FS/N

def read_fr(p):
    """REW frequency-response export -> (freq, spl_db, phase_deg)"""
    F,S,P=[],[],[]
    for line in open(p,encoding='utf-8',errors='replace'):
        s=line.strip()
        if not s or s.startswith('*'): continue
        q=s.replace(',',' ').split()
        if len(q)<2: continue
        try:
            f=float(q[0]); a=float(q[1]); ph=float(q[2]) if len(q)>2 else 0.0
        except ValueError: continue
        F.append(f); S.append(a); P.append(ph)
    return np.array(F),np.array(S),np.array(P)

def spec_from_fr(p, fill=0.0):
    """Map a linear-grid REW export onto the exact 131072-pt rfft grid."""
    F,S,P=read_fr(p)
    H=np.full(N//2+1, fill, dtype=complex)
    k=np.round(F/DF).astype(int)
    m=(k>=0)&(k<=N//2)
    H[k[m]]=10**(S[m]/20)*np.exp(1j*np.radians(P[m]))
    return H

def ir_from_fr(p, fill=0.0):
    return np.fft.irfft(spec_from_fr(p,fill), N)

def rdwav(p):
    b=open(p,'rb').read()
    assert b[:4]==b'RIFF' and b[8:12]==b'WAVE', p
    i=12; fmt=None; data=None
    while i+8<=len(b):
        cid=b[i:i+4]; sz=struct.unpack('<I',b[i+4:i+8])[0]; body=b[i+8:i+8+sz]
        if cid==b'fmt ': fmt=body
        elif cid==b'data': data=body
        i+=8+sz+(sz&1)
    tag,ch,fs,_,_,bits=struct.unpack('<HHIIHH',fmt[:16])
    if tag==0xFFFE: tag=struct.unpack('<H',fmt[24:26])[0]
    if tag==3:   a=np.frombuffer(data,dtype='<f4' if bits==32 else '<f8').astype(float)
    elif tag==1:
        if bits==32: a=np.frombuffer(data,dtype='<i4').astype(float)/2**31
        elif bits==16: a=np.frombuffer(data,dtype='<i2').astype(float)/2**15
        elif bits==24:
            v=np.frombuffer(data,dtype=np.uint8).reshape(-1,3).astype(np.int32)
            w=(v[:,0]|(v[:,1]<<8)|(v[:,2]<<16)); w=np.where(w>=1<<23,w-(1<<24),w)
            a=w.astype(float)/2**23
        else: raise RuntimeError(bits)
    else: raise RuntimeError(tag)
    if ch>1: a=a.reshape(-1,ch)[:,0]
    return a,fs

def read_ir_txt(p):
    """REW 'Impulse Response data' export.
    Metadata lines carry a '//' comment (peak value, peak index, response
    length, sample interval, start time, data offset). Data lines never do."""
    vals=[]; meta={}
    for line in open(p,encoding='utf-8',errors='replace'):
        s=line.strip()
        if not s or s.startswith('*'): continue
        if '//' in s:
            tok,_,cmt=s.partition('//')
            try: meta[cmt.strip()]=float(tok.strip())
            except ValueError: pass
            continue
        try: vals.append(float(s))
        except ValueError: continue
    pk=meta.get('Peak value before normalisation')
    pi=meta.get('Peak index'); ln=meta.get('Response length')
    return (np.array(vals), pk,
            int(pi) if pi is not None else None,
            int(ln) if ln is not None else None)
