"""Small calibrated cabinet-state classifier; reject nonmatching camera crops."""
import numpy as np


def calibrated_safe_state(image, calibration):
    if not calibration:
        return {'open':None,'method':'unavailable'}
    w,h=image.size
    zone=calibration['zone']
    bounds=tuple(int(v*s) for v,s in zip(zone,[w,h,w,h]))
    if bounds[2]-bounds[0]<30 or bounds[3]-bounds[1]<45:
        return {'open':None,'method':'too_small'}
    feature=np.asarray(image.crop(bounds).resize(tuple(calibration['size'])).convert('L'),dtype=float).flatten()
    scores=sorted((float(np.mean(np.abs(feature-np.asarray(row['values'])))),row['open']) for row in calibration['prototypes'])
    accepted=scores[0][0]<=calibration['max_mae'] and scores[1][0]-scores[0][0]>=calibration['margin']
    return {'open':scores[0][1] if accepted else None,'method':'calibrated_crop',
            'distance':round(scores[0][0],2),'margin':round(scores[1][0]-scores[0][0],2)}
