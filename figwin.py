import numpy as np, rewio as R, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
FS=48000.0; N=131072; f=np.fft.rfftfreq(N,1/FS)
D='/home/giacomo/devel/DRC/DRC-120.blue/'

# real measured IR (L.120.Blue, unsmoothed)
H0=R.spec_from_fr(D+'LEFT-measured.csv')
h0=np.fft.irfft(H0,N); pk=int(np.argmax(np.abs(h0)))
h0=np.roll(h0,-pk)                      # peak at sample 0 -> causal half

def halfwin(kind,n):
    t=np.arange(n)/max(n-1,1)
    if kind=='Rectangular': return np.ones(n)
    if kind=='Hann':        return 0.5*(1+np.cos(np.pi*t))
    if kind=='Hamming':     return 0.54+0.46*np.cos(np.pi*t)
    if kind=='Blackman-Harris':
        a=[0.35875,0.48829,0.14128,0.01168]
        return a[0]+a[1]*np.cos(np.pi*t)+a[2]*np.cos(2*np.pi*t)+a[3]*np.cos(3*np.pi*t)
    if kind.startswith('Tukey'):
        al=float(kind.split()[1]); w=np.ones(n); s=int((1-al)*n)
        if s<n: w[s:]=0.5*(1+np.cos(np.pi*(np.arange(s,n)-s)/max(n-s-1,1)))
        return w
    raise ValueError(kind)

SHAPES=['Rectangular','Tukey 0.25','Tukey 0.5','Hann','Hamming','Blackman-Harris']
COL=dict(zip(SHAPES,['#d62728','#1f77b4','#2ca02c','#ff7f0e','#9467bd','#8c564b']))
T=0.173; n=int(T*FS)

fig,ax=plt.subplots(3,1,figsize=(11,13))
stats=[]
for s in SHAPES:
    w=halfwin(s,n)
    ax[0].plot(np.arange(n)/FS*1000,w,color=COL[s],lw=1.4,label=s)
    # kernel = FT of the one-sided window
    W=np.fft.rfft(w,N); Wd=20*np.log10(np.abs(W)/np.abs(W[0])+1e-30)
    ax[1].plot(f,Wd,color=COL[s],lw=1.2,label=s)
    # measured main-lobe -3 dB half-width and worst sidelobe beyond it
    i3=np.argmax(Wd<-3.0); bw=f[i3]*2
    lo=int(3*f[i3]/(FS/N)); hi=int(300/(FS/N))
    side=Wd[lo:hi].max() if hi>lo else np.nan
    stats.append((s,bw,side))
    # apply to the real IR
    hw=h0.copy(); hw[:n]*=w; hw[n:]=0.0
    S=20*np.log10(np.abs(np.fft.rfft(hw,N))+1e-30)
    ax[2].plot(f,S,color=COL[s],lw=1.1,label=s)

S0=20*np.log10(np.abs(H0)+1e-30)
ax[2].plot(f,S0,color='k',lw=0.7,alpha=.45,label='unwindowed (raw)')

ax[0].set_xlim(0,T*1000); ax[0].set_ylim(-.05,1.05)
ax[0].set_xlabel('ms after the impulse peak'); ax[0].set_ylabel('amplitude')
ax[0].set_title('(a) The right-hand IR window in TIME — REW applies a half window, 1 at the peak falling to 0')
ax[0].grid(alpha=.3); ax[0].legend(fontsize=8,ncol=3)

ax[1].set_xlim(0,60); ax[1].set_ylim(-90,3)
ax[1].set_xlabel('frequency offset (Hz)'); ax[1].set_ylabel('dB')
ax[1].set_title('(b) …and the SAME window in FREQUENCY. This is the smoothing kernel the response gets convolved with')
ax[1].grid(alpha=.3); ax[1].legend(fontsize=8,ncol=3)

ax[2].set_xlim(30,120); ax[2].set_ylim(50,88)
ax[2].set_xlabel('Hz'); ax[2].set_ylabel('SPL (dB)')
ax[2].set_title('(c) The consequence on the real measurement (L.120.Blue), 173 ms window')
ax[2].grid(alpha=.3); ax[2].legend(fontsize=8,ncol=3)
plt.tight_layout()
plt.savefig('fig-window-shapes.png',dpi=105)

print('%-18s %14s %18s'%('shape','-3dB width (Hz)','worst sidelobe (dB)'))
for s,bw,sl in stats: print('%-18s %14.2f %18.1f'%(s,bw,sl))
