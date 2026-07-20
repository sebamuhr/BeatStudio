import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM","offscreen"); os.environ.setdefault("BEAT_NO_GL","1")
import numpy as np
from PySide6.QtWidgets import QApplication
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))+"/..")
from beatstudio.mainwindow import MainWindow
app=QApplication.instance() or QApplication(sys.argv)
w=MainWindow(); w.resize(1000,700); w.show(); app.processEvents()
w._open_separator(); b=w._board
for i in range(3):
    b.add_track()
    t=b.tracks[i]; t['kind']='drum'; t['sound']=['kick','snare','hat'][i]
    t['points'][:] = [{'id':f'p{i}{k}','t':0.1+k*0.2,'v':0.9,'midi':60,'hx':0,'hy':0,'tie':False,'glide':False} for k in range(3)]
    b._ensure_variations(t)
b.tracks[0]['color']  # keep colors
# add a variation to track 0
b.canvas.set_active(0); b.add_variation(b.tracks[0]); b.set_variation(b.tracks[0], 0)
# pad grid
w._toggle_padgrid(); print('pad grid visible:', w._padgrid.isVisible())
st = w._pad_state(); print('pad state: ntracks', st['ntracks'], 'nvar', st['nvar'])
w._padgrid.grab().save('scratchpad/padgrid.png')
# record performance
w._toggle_perf_record(); print('recording:', w._perf_recording)
# hit pad col0 row0 (index 0) -> opens a clip
w._pad_hit(0); print('after pad0: open clips', list(w._perf_openclips), 'total clips', len(w._clips))
# simulate ~1 second (2 beats at 120bpm) then hit pad col1
time.sleep(0.6)
w._pad_hit(1)   # col1 row0
time.sleep(0.6)
w._pad_hit(0)   # stop col0 (re-press)
w._toggle_perf_record()  # stop recording (closes col1)
print('final clips:', len(w._clips))
for c in w._clips: print('  clip col', c['col'], 'var', c['variation'], 'start', c['start'], 'len', c['length'])
print('OK')
