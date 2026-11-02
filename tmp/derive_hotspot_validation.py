from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, mean_absolute_error, mean_squared_error
from monitoring.ml.train_model import prepare_data, _make_pipeline
from monitoring.ml.features import FEATURES
from monitoring.ml.train_model import train
m=pd.read_json('monitoring/ml/model_metrics.json', typ='series')
data=prepare_data(Path('datasets/integrated_monthly.csv'))
periods=sorted(data['period'].unique())
train_end=max(1,int(len(periods)*.60)); val_end=max(train_end+1,int(len(periods)*.80)); val_end=min(val_end,len(periods)-1)
trp=periods[:train_end]; vap=periods[train_end:val_end]; tep=periods[val_end:]
tr=data[data.period.isin(trp)]; va=data[data.period.isin(vap)]; te=data[data.period.isin(tep)]
candidates=[{'n_estimators':300,'min_samples_leaf':2,'max_features':0.8},{'n_estimators':400,'min_samples_leaf':3,'max_features':0.8},{'n_estimators':400,'min_samples_leaf':5,'max_features':1.0}]
sc=[]
for p in candidates:
 model=_make_pipeline(p); model.fit(tr[FEATURES],tr.target_next_cases); pred=np.maximum(0,model.predict(va[FEATURES])); sc.append((mean_absolute_error(va.target_next_cases,pred),mean_squared_error(va.target_next_cases,pred)**.5,p))
selected=min(sc,key=lambda x:(x[0],x[1]))[2]
fit=pd.concat([tr,va]).sort_values(['period','barangay']); model=_make_pipeline(selected); model.fit(fit[FEATURES],fit.target_next_cases); pred=np.maximum(0,model.predict(te[FEATURES])); actual=te.target_next_cases.to_numpy()
true=(actual>=6).astype(int); guessed=(pred>=6).astype(int)
print('split', pd.Timestamp(trp[0]).strftime('%Y-%m'),pd.Timestamp(trp[-1]).strftime('%Y-%m'),len(tr),pd.Timestamp(vap[0]).strftime('%Y-%m'),pd.Timestamp(vap[-1]).strftime('%Y-%m'),len(va),pd.Timestamp(tep[0]).strftime('%Y-%m'),pd.Timestamp(tep[-1]).strftime('%Y-%m'),len(te))
print('selected',selected,'validation',sc)
print('MAE/RMSE',mean_absolute_error(actual,pred),mean_squared_error(actual,pred)**.5)
print('baseline',mean_absolute_error(actual,te.case_count.to_numpy()),mean_squared_error(actual,te.case_count.to_numpy())**.5)
print('confusion matrix labels [no, hotspot]\\n',confusion_matrix(true,guessed,labels=[0,1]))
print(classification_report(true,guessed,labels=[0,1],target_names=['No hotspot','Hotspot'],zero_division=0,digits=4))
