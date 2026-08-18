import numpy as np, rewio as R, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
FS=48000.0; N=131072
D='/home/giacomo/devel/DRC/DRC-120.blue/'
H0=R.spec_from_fr(D+'LEFT-measured.csv'); f=np.fft.rfftfreq(N,1/FS)
h0=np.fft.irfft(H0,N); h0=np.roll(h0,-int(np.argmax(np.abs(h0))))
t=((np.arange(N)+N//2)%N-N//2)/FS                      # centred time axis

def fdw(h,freqs,ncyc):
    """True frequency-dependent window: Gaussian of FWHM ncyc/f, per frequency."""
    out=np.empty(len(freqs),dtype=complex)
    for i,f0 in enumerate(freqs):
        sig=ncyc/(f0*2.3548)
        w=np.exp(-0.5*(t/sig)**2)
        out[i]=np.dot(h*w,np.exp(-2j*np.pi*f0*t))   # phase referenced to the SAME centred axis as w
    return out

fq=np.logspace(np.log10(18),np.log10(300),500)
fig,ax=plt.subplots(3,1,figsize=(11,13))

# (a) the FDW in time, at several frequencies
for f0,c in [(25,'#d62728'),(50,'#ff7f0e'),(100,'#2ca02c'),(200,'#1f77b4')]:
    sig=12/(f0*2.3548); tt=np.linspace(-0.6,0.6,2000)
    ax[0].plot(tt*1000,np.exp(-0.5*(tt/sig)**2),color=c,lw=1.6,
               label='%d Hz  → width %.0f ms'%(f0,12/f0*1000))
ax[0].set_xlim(-600,600); ax[0].set_xlabel('ms relative to the impulse peak')
ax[0].set_ylabel('amplitude')
ax[0].set_title('(a) The FDW in TIME at 12 cycles — one window per frequency, width = N/f')
ax[0].grid(alpha=.3); ax[0].legend(fontsize=9)

# (b) the same windows as frequency kernels, on a log axis
for f0,c in [(25,'#d62728'),(50,'#ff7f0e'),(100,'#2ca02c'),(200,'#1f77b4')]:
    df=f0/12.0; x=np.logspace(np.log10(f0/4),np.log10(f0*4),1500)
    ax[1].semilogx(x,20*np.log10(np.exp(-0.5*((x-f0)/(df/2.3548))**2)+1e-12),color=c,lw=1.6,
                   label='%d Hz  → kernel %.1f Hz wide'%(f0,df))
ax[1].set_xlim(15,400); ax[1].set_ylim(-45,3); ax[1].set_xlabel('Hz')
ax[1].set_ylabel('dB')
ax[1].set_title('(b) …the same windows in FREQUENCY. Equal width on a LOG axis = constant fractional bandwidth (1/N)')
ax[1].grid(alpha=.3,which='both'); ax[1].legend(fontsize=9)

# (c) applied to the real measurement
S0=20*np.log10(np.abs(H0)+1e-30)
m=(f>=18)&(f<=300)
ax[2].semilogx(f[m],S0[m],color='k',lw=0.6,alpha=.45,label='no FDW (raw)')
for ncyc,c in [(30,'#9467bd'),(12,'#1f77b4'),(4,'#d62728')]:
    Y=20*np.log10(np.abs(fdw(h0,fq,ncyc))+1e-30)
    ax[2].semilogx(fq,Y,color=c,lw=1.6,label='FDW %d cycles  (= 1/%d octave)'%(ncyc,ncyc))
ax[2].axvline(28.93,color='k',ls=':',lw=1); ax[2].annotate('28.93 Hz\nnull',(28.93,54),fontsize=8,ha='center')
ax[2].axvline(51.27,color='k',ls=':',lw=1); ax[2].annotate('51.27 Hz\npeak',(51.27,54),fontsize=8,ha='center')
ax[2].set_xlim(18,300); ax[2].set_ylim(50,90)
ax[2].set_xlabel('Hz'); ax[2].set_ylabel('SPL (dB)')
ax[2].set_title('(c) L.120.Blue through the FDW. 12 cycles keeps the modes and refuses the razor null')
ax[2].grid(alpha=.3,which='both'); ax[2].legend(fontsize=9)
plt.tight_layout()
plt.savefig('fig-fdw.png',dpi=105)
print('written')

# --- quantitative: window width and longest representable decay ---
print()
print('%6s'%'N'+''.join('%22s'%('%d Hz'%x) for x in [25,50,100,200]))
for n in [4,8,12,20,30]:
    print('%6d'%n+''.join('%12.0f ms /%6.0f'%(n/x*1000,2200.0*n/x) for x in [25,50,100,200]))
print('(window FWHM  /  longest T60 it can represent, ms)')
