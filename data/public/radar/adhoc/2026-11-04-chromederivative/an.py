import json,glob,statistics as S
def ser(n,key='serie_0'):
    j=json.load(open(n+'.json'))
    if j['status']!=200: return None
    return j['response']['result'][key]
def mean(s,k,lo,hi):
    ts=s['timestamps']; v=[float(x) for t,x in zip(ts,s.get(k,['0']*len(ts))) if lo<=t[:10]<=hi]
    return sum(v)/len(v) if v else 0
# volumes: same weekdays, Mon-Fri Aug31-Sep4 vs Sep14-18, and Mon Sep7? use two full weeks Sep1-7 vs Sep 15-21
print("== Volume (MIN0_MAX, mean of Sep 1-7 vs Sep 15-21 vs Sep 29-Oct 5)")
for n in ['v_ALL','vf_FIREFOX','vf_SAFARI','vf_CHROME','vf_EDGE']:
    s=ser(n); s={'timestamps':s['timestamps'],'v':s['values']}
    a,b,c=mean(s,'v','2026-09-01','2026-09-07'),mean(s,'v','2026-09-15','2026-09-21'),mean(s,'v','2026-09-29','2026-10-05')
    print(f"{n:12} {a:.3f} {b:.3f} {c:.3f}  {100*(b/a-1):+.1f}% {100*(c/a-1):+.1f}%")
print("== Browser family daily share")
s=ser('gf_ALL')
for i,t in enumerate(s['timestamps']):
    if '2026-09-05'<=t[:10]<='2026-09-14': print(t[:10],' '.join(f"{k}:{float(s[k][i]):.2f}" for k in ['chrome','safari','edge','firefox','samsung','opera']))
print("== ChromeDerivative share by country / OS: Sep1-7 -> Sep15-21; and Firefox, Safari, Chrome relative change")
rows=[]
for f in sorted(glob.glob('gb_*.json')):
    n=f[:-5]; s=ser(n)
    if not s: print(n,'ERR'); continue
    pre=lambda k:mean(s,k,'2026-09-01','2026-09-07'); post=lambda k:mean(s,k,'2026-09-15','2026-09-21')
    cd0,cd1=pre('ChromeDerivative'),post('ChromeDerivative')
    ch=lambda k:(100*(post(k)/pre(k)-1) if pre(k)>0.05 else float('nan'))
    # step day: first day CD > half of post level
    ts=s['timestamps']; step=next((t[:10] for t,x in zip(ts,s['ChromeDerivative']) if float(x)>cd0+(cd1-cd0)/2),'-') if 'ChromeDerivative' in s else '-'
    rows.append((cd1-cd0,n[3:],cd0,cd1,step,ch('Chrome'),ch('ChromeMobile'),ch('Edge'),ch('Firefox'),ch('Safari'),ch('MobileSafari'),ch('SamsungInternet'),pre('Firefox'),pre('Safari')))
print(f"{'':12}{'CD pre':>7}{'CD post':>8} {'step':10}{'Chrome':>7}{'ChrMob':>7}{'Edge':>7}{'FF':>7}{'Safari':>7}{'MSaf':>7}{'Samsg':>7}  FF%  Saf%")
for r in sorted(rows,reverse=True):
    print(f"{r[1]:12}{r[2]:7.2f}{r[3]:8.2f} {r[4]:10}"+''.join(f"{x:+7.1f}" for x in r[5:12])+f"  {r[12]:.1f}  {r[13]:.1f}")
