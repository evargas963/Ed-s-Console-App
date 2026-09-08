import json, sqlite3, statistics, time
from collections import defaultdict
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

phase8=json.load(open('data/phase8_calibration_global_v1.json'))
readiness=json.load(open('data/ticker_readiness_matrix_v1.json'))
allowed=sorted(r['ticker'] for r in readiness['tickers'] if r['final_readiness_verdict']=='READY_GLOBAL_STANDARD' and r['policy_status']=='POLICY_ELIGIBLE')
excluded=set(tuple(s.split(':')) for s in phase8.get('excluded_family_horizon',[]))
horizons=['1c','3c','5c','8c','13c','15c','60c']

def deciles(pred,y):
    n=len(pred)
    if n<10: return []
    order=sorted(range(n), key=lambda i: pred[i])
    out=[]
    for d in range(10):
        lo=int(d*n/10); hi=int((d+1)*n/10)
        idx=order[lo:hi]
        if not idx: continue
        ps=[pred[i] for i in idx]; ys=[y[i] for i in idx]
        out.append({'decile':d+1,'n':len(idx),'pred_mean':float(statistics.fmean(ps)),'emp_rate':float(statistics.fmean(ys))})
    return out

def mono(emp):
    return all(emp[i] <= emp[i+1]+1e-12 for i in range(len(emp)-1))

def brier(pred,y):
    return float(statistics.fmean((pred[i]-y[i])**2 for i in range(len(pred)))) if pred else float('nan')

def rankdiff(pred,y):
    n=len(pred)
    if n<20: return None
    order=sorted(range(n), key=lambda i: pred[i]); k=max(1,n//10)
    bot=order[:k]; top=order[-k:]
    br=float(statistics.fmean(y[i] for i in bot)); tr=float(statistics.fmean(y[i] for i in top))
    return tr-br

def method_preds(name,p,y):
    x=np.array(p).reshape(-1,1); yy=np.array(y)
    if name=='isotonic':
        iso=IsotonicRegression(y_min=0,y_max=1,increasing=True,out_of_bounds='clip').fit(p,y)
        pred=[float(iso.predict([v])[0]) for v in p]
        model={'type':'isotonic','x_thresholds':[float(v) for v in iso.X_thresholds_],'y_thresholds':[float(v) for v in iso.y_thresholds_]}
        return pred,model
    if name=='platt':
        lr=LogisticRegression(solver='lbfgs',max_iter=200).fit(x,yy)
        pred=[float(v) for v in lr.predict_proba(x)[:,1]]
        model={'type':'platt','coef':float(lr.coef_[0][0]),'intercept':float(lr.intercept_[0])}
        return pred,model
    if name=='bin_mono':
        b=deciles(p,y)
        cx=[bb['pred_mean'] for bb in b]
        cy=[bb['emp_rate'] for bb in b]
        iso=IsotonicRegression(y_min=0,y_max=1,increasing=True,out_of_bounds='clip').fit(cx,cy)
        pred=[float(iso.predict([v])[0]) for v in p]
        model={'type':'bin_mono','bin_pred_means':cx,'bin_emp_rates':cy,'x_thresholds':[float(v) for v in iso.X_thresholds_],'y_thresholds':[float(v) for v in iso.y_thresholds_]}
        return pred,model
    raise ValueError

conn=sqlite3.connect('data/ed_console.db'); conn.row_factory=sqlite3.Row
results=[]; final_funcs={}; thresholds=[]; robustness=[]
for family,colp,colo,valdir in [('move','pred_move_prob','outcome_move',False),('dir','pred_dir_up_prob','outcome_dir',True)]:
  final_funcs[family]={}
  for hz in horizons:
    if (family,hz) in excluded:
      continue
    q=f"SELECT ticker,{colp}_{hz} p,{colo}_{hz} y FROM snapshots WHERE ticker IN ({','.join(['?']*len(allowed))}) AND {colp}_{hz} IS NOT NULL AND {colo}_{hz} IS NOT NULL"
    if valdir: q += f" AND CAST(valid_dir_{hz} AS INTEGER)=1"
    rows=conn.execute(q,tuple(allowed)).fetchall()
    p=[float(r['p']) for r in rows]
    y=[1 if str(r['y']).lower()==('move' if family=='move' else 'up') else 0 for r in rows]
    n=len(y)
    if n<200:
      continue
    base_rank=rankdiff(p,y)
    by=defaultdict(lambda: {'p':[],'y':[]})
    for r,pp,yy in zip(rows,p,y):
      by[r['ticker']]['p'].append(pp); by[r['ticker']]['y'].append(yy)
    per=[rankdiff(v['p'],v['y']) for v in by.values() if len(v['y'])>=40 and rankdiff(v['p'],v['y']) is not None]
    med=float(statistics.median(per)) if per else None
    var=float(statistics.pstdev(per)) if len(per)>1 else 0.0
    robust = (len(per)>=5 and med is not None and med>0 and var<0.22)
    robustness.append({'family':family,'horizon':hz,'per_ticker_n':len(per),'median_rank_diff':med,'std_rank_diff':var,'robust':robust})

    methods={}
    for m in ['isotonic','bin_mono','platt']:
      cp,model=method_preds(m,p,y)
      d=deciles(cp,y)
      emp=[bb['emp_rate'] for bb in d]
      rd=rankdiff(cp,y)
      br=brier(cp,y)
      methods[m]={'monotonic':mono(emp),'brier':br,'rank_diff':rd,'rank_preserved':(rd is not None and base_rank is not None and rd>=base_rank-0.005),'model':model}
    cands=[(m,v) for m,v in methods.items() if v['rank_preserved']]
    best=min(cands,key=lambda kv: kv[1]['brier'])[0] if cands else max(methods.items(), key=lambda kv: kv[1]['rank_diff'] if kv[1]['rank_diff'] is not None else -9)[0]
    b=methods[best]
    brier_raw=brier(p,y); bdelta=brier_raw-b['brier']
    classif='RESEARCH_ONLY'; verdict='FAIL'
    if b['rank_diff'] is not None and b['rank_diff']>0.08 and bdelta>0 and robust:
      classif='POLICY_CALIBRATED' if b['monotonic'] else 'POLICY_RANK_ONLY'; verdict='PASS'
    elif b['rank_diff'] is not None and b['rank_diff']>0.04 and bdelta>0:
      classif='POLICY_RANK_ONLY'; verdict='PASS'

    results.append({'horizon':hz,'head':family,'monotonic':b['monotonic'],'brier_delta':bdelta,'ranking_delta':b['rank_diff'],'sample_size':n,'cross_ticker_std':var,'best_method':best,'verdict':verdict,'classification':classif,'methods':methods})
    final_funcs[family][hz]={'method':best,'classification':classif,'mapping':methods[best]['model'],'rank_preserved':methods[best]['rank_preserved'],'monotonic':methods[best]['monotonic'],'brier_delta':bdelta}

    cp,_=method_preds(best,p,y)
    base=float(statistics.fmean(y))
    for th in [0.55,0.6,0.65,0.7,0.75,0.8,0.85]:
      idx=[i for i,v in enumerate(cp) if v>=th]
      if len(idx)<120: continue
      rate=float(statistics.fmean(y[i] for i in idx)); edge=rate-base
      if edge>0.02:
        thresholds.append({'horizon':hz,'head':family,'threshold':th,'sample_size':len(idx),'outcome_rate':rate,'edge_delta':edge})

conn.close()
sets={'movement':{'POLICY_CALIBRATED':[],'POLICY_RANK_ONLY':[],'RESEARCH_ONLY':[]},'direction':{'POLICY_CALIBRATED':[],'POLICY_RANK_ONLY':[],'RESEARCH_ONLY':[]}}
for r in results:
  k='movement' if r['head']=='move' else 'direction'
  sets[k][r['classification']].append(r['horizon'])
pass_cond=(len(sets['movement']['POLICY_CALIBRATED'])+len(sets['movement']['POLICY_RANK_ONLY'])>=1)
out={'created_ts_utc':time.time(),'ticker_set_used':allowed,'excluded_family_horizon':sorted(':'.join(x) for x in excluded),'diagnostic':results,'horizon_sets':sets,'final_calibration_functions':final_funcs,'thresholds':thresholds,'cross_ticker_robustness':robustness,'final_verdict':'PASS' if pass_cond else 'FAIL'}
open('data/phase8_calibration_remediation_v1.json','w',encoding='utf-8').write(json.dumps(out,indent=2))
print(json.dumps({'wrote':'data/phase8_calibration_remediation_v1.json','verdict':out['final_verdict'],'diag_rows':len(results),'thresholds':len(thresholds)},indent=2))
