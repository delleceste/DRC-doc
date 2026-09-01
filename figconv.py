"""Figure for NOTES.md §22 - convolution as a sum of scaled, delayed copies,
and the same operation producing §18's audible symptom.

A third panel (band-limited filter decay) was dropped: at 28.7 Hz it was
contaminated by circular wrap-around of the 2731 ms filter and by the analysis
band-filter's own ringing, i.e. exactly the uncontrolled measurement that
produced §18's original error."""
import numpy as np, rewio as R, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import fftconvolve, hilbert
FS=48000.0; N=131072
D='/home/giacomo/devel/DRC/DRC-120.blue/'

fig,ax=plt.subplots(2,1,figsize=(11,8))

# (a) the idea: input * [direct + two echoes] = sum of three scaled delayed copies
n=int(0.040*FS); t=np.arange(n)/FS
burst=np.sin(2*np.pi*120*t)*np.hanning(n)
h=np.zeros(int(0.130*FS)); h[0]=1.0; h[int(0.035*FS)]=0.55; h[int(0.080*FS)]=0.3
y=fftconvolve(burst,h)
tt=np.arange(len(y))/FS*1000
for d,a,c,lab in [(0,1.0,'#1f77b4','direct  x1.00'),(0.035,0.55,'#2ca02c','echo 1  x0.55  (+35 ms)'),
                  (0.080,0.30,'#d62728','echo 2  x0.30  (+80 ms)')]:
    s=np.zeros_like(y); k=int(d*FS); s[k:k+n]=burst*a
    ax[0].plot(tt,s-0,color=c,lw=1.0,alpha=.85,label=lab)
ax[0].plot(tt,y+2.6,color='k',lw=1.1,label='their SUM = the convolution')
ax[0].set_xlim(0,150); ax[0].set_yticks([])
ax[0].set_xlabel('ms'); ax[0].legend(fontsize=8,ncol=2,loc='upper right')
ax[0].set_title('(a) Convolution = every input sample fires a scaled, delayed copy of the impulse response; the output is their sum')

# (b) the same operation with a REAL filter: why the woofer keeps moving
def gated(h,f0=28.7,dur=1.0,ramp=0.005):
    m=int(dur*FS); tt=np.arange(m)/FS; x=np.sin(2*np.pi*f0*tt)
    r=int(ramp*FS); w=np.ones(m); w[:r]=0.5*(1-np.cos(np.pi*np.arange(r)/r)); w[-r:]=w[:r][::-1]
    x=np.concatenate([x*w,np.zeros(int(2.2*FS))])
    y=fftconvolve(x,h)[:len(x)]
    e=np.abs(hilbert(y)); d=int(np.argmax(np.abs(h)))
    off=m+d; ss=np.median(e[off-int(.3*FS):off-int(.02*FS)])
    return (np.arange(len(e))-off)/FS*1000, 20*np.log10(np.maximum(e,1e-30)/ss)

def smooth_lf(H,frac,fhi=200.,fb=300.):
    f=np.fft.rfftfreq(N,1/FS); L=20*np.log10(np.maximum(np.abs(H),1e-12)); out=L.copy()
    sig=frac/2.3548; lf=np.log2(np.maximum(f,1e-9))
    for k in range(1,int(fb/(FS/N))+2):
        d=lf-lf[k]; w=np.exp(-0.5*(d/sig)**2); w[np.abs(d)>4*sig]=0; w[0]=0
        out[k]=np.dot(w,L)/w.sum()
    a=np.clip((f-fhi)/(fb-fhi),0,1); return 10**((out*(1-a)+L*a)/20)
def minphase(mag):
    lm=np.log(np.maximum(mag,1e-12)); full=np.concatenate([lm,lm[-2:0:-1]])
    c=np.fft.ifft(full).real; w=np.zeros(N); w[0]=1; w[1:N//2]=2; w[N//2]=1
    return np.exp(np.fft.fft(c*w)[:N//2+1])

# The deployed filter, named explicitly. NOT D+'FLX-trimmed-48k.wav': that is a
# STABLE name meaning "whatever build is current" (DRC-120.blue/CLAUDE.md), so it
# silently became the Rscreen build, which decays to -40 dB in 149 ms instead of
# 1347 ms -- i.e. it does not show the symptom this panel exists for.
FLX,_=R.rdwav(D+'120.blue.txts/FLX-trimmed-48k.wav')
X=R.spec_from_fr(D+'120.blue.txts/X801 (revised).txt')
good=np.fft.irfft(minphase(smooth_lf(np.fft.rfft(FLX),1/6.))*X,N)
good=np.roll(good,20000-int(np.argmax(np.abs(good))))

for h,c,lab in [(FLX,'#d62728','as deployed  (FLX, legacy 120.blue build)'),(good,'#1f77b4','rebuilt, 1/6 oct below 200 Hz')]:
    x,e=gated(h); m=(x>=-120)&(x<=1600); ax[1].plot(x[m],e[m],color=c,lw=1.3,label=lab)
ax[1].axvline(0,color='k',lw=1); ax[1].axhline(-40,color='k',ls=':',lw=1)
ax[1].annotate('note stops',(0,3),fontsize=8,ha='center')
ax[1].set_xlim(-120,1600); ax[1].set_ylim(-80,8)
ax[1].set_xlabel('ms relative to the note stopping'); ax[1].set_ylabel('dB re steady state')
ax[1].set_title('(b) The same sum, 28.7 Hz: the output keeps summing contributions long after the input stopped')
ax[1].grid(alpha=.3); ax[1].legend(fontsize=9)

plt.tight_layout(); plt.savefig('fig-convolution.png',dpi=105)
print('written')
