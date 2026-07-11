"""Master extraction — split a whole-groove recording into instrument tracks.

Port of the web _multiExtract. Without a My Sounds gallery yet, uses the brightness
band-split fallback; matching against the gallery lands with task 9.
"""
from __future__ import annotations
import numpy as np
from .model import Lane, Event
from .analysis import seg_features, match_dist, MATCH_THRESH
from . import ai_match

MASTER_MAX = 16
_PALETTE = ["kick", "808", "tomL", "congaL", "tomM", "snare", "rim", "congaH",
            "clap", "cowbell", "hat", "shaker", "openhat", "cymbal"]


def _event(lane_id, o, spb, start_beat):
    return Event(lane_id=lane_id, beat=start_beat + o["t"] / spb,
                 vel=max(0.4, min(1.0, o["amp"])), length=o["dur"] / spb,
                 src_t=o["t"], src_dur=min(2.5, o["dur"]))


_LABEL_NAME = {k: k.capitalize() for k in
               ["kick", "808", "snare", "rim", "clap", "hat", "openhat", "cymbal",
                "tomM", "cowbell", "shaker"]}


def _hit_audio(buf, sr, o):
    # Grab a fuller window (attack + body/decay) so CLAP can identify the sound. A tight
    # 0.1s slice loses a kick's low body → mislabels. ~0.35s captures most drum tails.
    a = int(o["t"] * sr)
    b = min(len(buf), a + int(max(0.35, min(0.7, o.get("dur", 0.2) + 0.25)) * sr))
    return buf[a:b]


def clap_extract(onsets, buf, sr, spb, start_beat, library=None, use_ai=True):
    """AI matcher (CLAP): embed each hit and pick the most similar sound by AUDIO similarity —
    comparing against BOTH the built-in instrument voices AND the My Sounds gallery, whichever
    is closest. This is the "compare the waveforms, choose the nearest" approach."""
    if not (use_ai and ai_match.available() and ai_match.load()):
        return None                       # signal caller to fall back to DSP
    gallery = list(library.sounds) if library else []
    gal_emb = [(s, library.clap_embedding(s.id)) for s in gallery]
    gal_emb = [(s, e) for s, e in gal_emb if e is not None]

    lanes_by_key, order, hit_of = {}, [], []
    for o in onsets:
        emb = ai_match.embed(_hit_audio(buf, sr, o), sr)
        # nearest built-in instrument (always available as a baseline)
        ni = ai_match.nearest_instrument(emb) if emb is not None else None
        best_key = best_name = None
        if ni is not None:
            kind, sound, dist_i = ni
            best_key, best_name, best_dist = "instr:" + sound, _LABEL_NAME.get(sound, sound.capitalize()), dist_i
            best_kind, best_sound = kind, sound
        else:
            kind = "drum"; best_kind, best_sound = "drum", "kick"
            best_key, best_name, best_dist = "instr:kick", "Kick", 9.9
        # a My Sound only wins if it's genuinely closer than the best instrument
        if emb is not None:
            for s, e in gal_emb:
                d = ai_match.cosine_dist(emb, e)
                if d < best_dist:
                    best_dist = d; best_key = "mys:" + s.id; best_name = s.name
                    best_kind, best_sound = "sample", "mys:" + s.id
        if best_key not in lanes_by_key:
            lanes_by_key[best_key] = Lane(kind=best_kind, sound=best_sound, name=best_name, auto=True)
            order.append(best_key)
        hit_of.append((best_key, o))

    lanes = [lanes_by_key[k] for k in order]
    events = [_event(lanes_by_key[k].id, o, spb, start_beat) for k, o in hit_of]
    return lanes, events


def analyze_clusters(buf, sr, start_beat, usermodel=None):
    """Phase 1 for the review flow: detect + tempo + quantize + cluster, and for each cluster
    return a representative sound to preview and a SUGGESTED category (from what you've labelled
    before, else an acoustic guess). Returns (bpm, clusters, hp_buf). No tracks yet."""
    from . import groove, ai_match
    hp = groove.highpass(buf, sr)
    # Split into a sustained-tone layer and a percussion layer. Percussion hits come from the
    # percussive layer; the held background melody is read from the harmonic layer as ONE
    # continuous line (never chopped at each ts/pf). "Musical, not exact."
    harm, perc = groove.hpss(hp, sr)
    onsets = groove.onsets_from(hp, sr, groove.gate_lin(10))
    if not onsets:
        return None, [], hp
    times = [o["t"] for o in onsets]
    bpm = groove.detect_tempo(hp, sr, times)
    beats = groove.quantize(times, bpm)
    beat_len = 60.0 / bpm
    ai_on = ai_match.available() and ai_match.load()
    embs = [ai_match.embed(_hit_audio(hp, sr, o), sr) if ai_on else None for o in onsets]
    labels = (groove.cluster(embs, thresh=0.28)
              if ai_on and all(e is not None for e in embs) else list(range(len(onsets))))
    pitches = [groove.detect_pitch(_hit_audio(hp, sr, o), sr) for o in onsets]

    def _wide(o):
        a = int(o["t"] * sr)
        return hp[a:min(len(hp), a + int(max(0.5, o.get("dur", 0.2) + 0.3) * sr))]

    clusters = []
    for lab in sorted(set(labels)):
        idxs = [i for i, l in enumerate(labels) if l == lab]
        rep = max(idxs, key=lambda i: onsets[i]["amp"])       # clearest example
        cen = None
        if ai_on and all(embs[i] is not None for i in idxs):
            cen = np.mean([embs[i] for i in idxs], axis=0)
            cen = cen / (np.linalg.norm(cen) + 1e-9)
        # suggestion: learned model first, else acoustic, else pitch→melody
        suggest, conf = (usermodel.predict(cen) if (usermodel and cen is not None) else (None, 0.0))
        if not suggest:
            if sum(1 for i in idxs if pitches[i][1]) >= max(1, len(idxs) // 2):
                suggest = "melody"
            else:
                key = groove.classify_acoustic(_hit_audio(hp, sr, onsets[rep]), sr)
                suggest = {"tomM": "tom"}.get(key, key)
        ra = int(onsets[rep]["t"] * sr)
        rep_audio = hp[ra:min(len(hp), ra + int(0.5 * sr))].copy()
        # per-hit melody note (robust, wide window) + a clean synth timbre matched to the sound
        preset = groove.pick_preset(_wide(onsets[rep]), sr)
        hits = []
        for i in idxs:
            note = groove.note_of(_wide(onsets[i]), sr) or pitches[i][0]
            hits.append({"beat": start_beat + beats[i], "amp": onsets[i]["amp"],
                         "len": max(0.25, round((onsets[i]["dur"] / beat_len) * 4) / 4),
                         "src_t": onsets[i]["t"], "src_dur": min(2.5, onsets[i]["dur"]),
                         "pitch": note})
        clusters.append({"id": int(lab), "centroid": cen, "suggest": suggest,
                         "suggest_conf": conf, "rep_audio": rep_audio, "hits": hits,
                         "n": len(idxs), "preset": preset})
    # Held background melody from the harmonic layer → one melody cluster of sustained notes.
    mel_hits = groove.melody_line(harm, sr, bpm, start_beat)
    if len(mel_hits) >= 2:
        ma = int(mel_hits[0]["src_t"] * sr)
        mrep = harm[ma:min(len(harm), ma + int(0.6 * sr))].copy()
        clusters.append({"id": max((c["id"] for c in clusters), default=-1) + 1,
                         "centroid": None, "suggest": "melody", "suggest_conf": 1.0,
                         "rep_audio": mrep, "hits": mel_hits, "n": len(mel_hits),
                         "preset": groove.pick_preset(mrep, sr), "is_melody": True})
    clusters.sort(key=lambda c: -c["n"])
    return bpm, clusters, hp


def build_from_review(clusters, decisions, usermodel=None):
    """Phase 2: turn the user's questionnaire answers into tracks, and LEARN from them
    (store each labelled fingerprint so future suggestions improve). `decisions` = {cluster_id:
    category_id}. Returns (lanes, events)."""
    from .usermodel import CAT_BY_ID
    lanes, events = [], []
    for c in clusters:
        cat = decisions.get(c["id"], c["suggest"])
        if cat == "skip" or cat not in CAT_BY_ID:
            continue
        _id, _lbl, kind, sound, play_orig = CAT_BY_ID[cat]
        if kind is None:
            continue
        melodic = (kind == "synth")
        # For melody/lead: use a CLEAN synth timbre matched to the real sound, and follow the
        # detected melody note-for-note (median note if a hit had none).
        if melodic and cat == "melody":
            sound = c.get("preset", sound)
            notes = [h["pitch"] for h in c["hits"] if h["pitch"]]
            fallback = int(round(sum(notes) / len(notes))) if notes else 60
        else:
            fallback = 60
        lane = Lane(kind=kind, sound=sound, name=_lbl.split(" (")[0], auto=True)
        lane.has_original = True
        lane.play_original = bool(play_orig)
        lanes.append(lane)
        for h in c["hits"]:
            events.append(Event(lane_id=lane.id, beat=h["beat"], vel=max(0.4, min(1.0, h["amp"])),
                               length=h["len"], pitch=(h["pitch"] or fallback) if melodic else None,
                               src_t=h["src_t"], src_dur=h["src_dur"]))
        if usermodel is not None and c["centroid"] is not None and cat not in ("skip",):
            usermodel.add(c["centroid"], cat)      # train-along: remember this labelled sound
    if usermodel is not None:
        usermodel.save()
    return lanes, events


def smart_extract(buf, sr, start_beat, library=None, use_ai=True):
    """Full musical pipeline: onsets → tempo → quantize to grid → cluster by timbre → one
    track per sound, each placed on the beat. Returns (bpm, lanes, events)."""
    from . import groove, ai_match
    buf = groove.highpass(buf, sr)               # kill DC/subsonic rumble first
    onsets = groove.onsets_from(buf, sr, groove.gate_lin(10))
    if not onsets:
        return None, [], []
    times = [o["t"] for o in onsets]
    bpm = groove.detect_tempo(buf, sr, times)
    beats = groove.quantize(times, bpm)          # quantized beat position per hit
    beat_len = 60.0 / bpm

    ai_on = use_ai and ai_match.available() and ai_match.load()
    embs = [ai_match.embed(_hit_audio(buf, sr, o), sr) if ai_on else None for o in onsets]
    valid = [e for e in embs if e is not None]
    if ai_on and len(valid) == len(onsets):
        labels = groove.cluster(embs, thresh=0.28)   # group same-sounding hits (~6-8 for beatbox)
    else:
        labels = list(range(len(onsets)))        # no AI → keep separate, DSP will band it

    # per-hit pitch (melodic sounds carry a real note)
    pitches = [groove.detect_pitch(_hit_audio(buf, sr, o), sr) for o in onsets]

    # one lane per cluster, interpreted: melodic → pitched synth; clean drum → that drum;
    # unusual/effect sound → keep the REAL recording (play_original) so it's authentic.
    gal_emb = []
    if library:
        gal_emb = [(s, library.clap_embedding(s.id)) for s in library.sounds]
        gal_emb = [(s, e) for s, e in gal_emb if e is not None]
    lane_of, lane_melodic, order = {}, {}, []
    POOR_MATCH = 0.55            # CLAP cosine dist above which a sound is "not a clean instrument"
    for lab in labels:
        if lab in lane_of:
            continue
        idxs = [i for i, l in enumerate(labels) if l == lab]
        melodic = sum(1 for i in idxs if pitches[i][1]) >= max(1, len(idxs) // 2)
        if melodic:
            # a pitched line → real synth so you HEAR the melody with an instrument
            kind, sound, name = "synth", "saw", "Melody"
        else:
            # guess the drum from the cluster's typical acoustic profile → assign a REAL
            # instrument (this is what lets you hear your beatbox as actual drums).
            rep = max(idxs, key=lambda i: onsets[i]["amp"])          # loudest = clearest example
            key = groove.classify_acoustic(_hit_audio(buf, sr, onsets[rep]), sr)
            kind, sound, name = "drum", key, _LABEL_NAME.get(key, key.capitalize())
        lane = Lane(kind=kind, sound=sound, name=name, auto=True)
        pitched_lane = (kind == "synth")
        lane.play_original = False           # default: play the assigned REAL instrument
        lane_of[lab] = lane; lane_melodic[lab] = pitched_lane
        order.append(lab)

    lanes = [lane_of[l] for l in order]
    events = []
    for i, (o, b, lab) in enumerate(zip(onsets, beats, labels)):
        dur_beats = max(0.25, round((o["dur"] / beat_len) * 4) / 4)   # quantize length to 16ths
        pitch = (pitches[i][0] or 60) if lane_melodic[lab] else None   # synth lanes always pitched
        events.append(Event(lane_id=lane_of[lab].id, beat=start_beat + b,
                            vel=max(0.4, min(1.0, o["amp"])), length=dur_beats,
                            pitch=pitch, src_t=o["t"], src_dur=min(2.5, o["dur"])))
    return bpm, lanes, events


def _label_centroid(cen, gal_emb, ai_match):
    """Return (kind, sound, name, distance) for the nearest instrument / My Sound to a centroid."""
    ni = ai_match.nearest_instrument(cen)
    if ni is None:
        return "drum", "kick", "Kick", 1.0
    kind, sound, dist = ni
    name = _LABEL_NAME.get(sound, sound.capitalize()); k2, s2 = kind, sound
    for s, e in gal_emb:
        d = ai_match.cosine_dist(cen, e)
        if d < dist:
            dist = d; name = s.name; k2, s2 = "sample", "mys:" + s.id
    return k2, s2, name, dist


def multi_extract(onsets, buf, sr, spb, start_beat, library=None, use_ai=True):
    """AI (CLAP) matching when available, else DSP gallery-match, else brightness band-split."""
    if not onsets:
        return [], []
    ai = clap_extract(onsets, buf, sr, spb, start_beat, library, use_ai)
    if ai is not None:
        return ai
    if not (library and library.sounds):
        return band_split(onsets, spb, start_beat)

    lanes, events = [], []
    groups = {}          # 'mys:<id>' -> lane
    unknown = []
    for o in onsets:
        f = seg_features(buf, int(o["t"] * sr), sr)
        best, bd = None, 1e9
        for s in library.sounds:
            sf = library.features(s.id)
            if sf is None:
                continue
            d = match_dist(f, sf)
            if d < bd:
                bd, best = d, s
        if best is not None and bd <= MATCH_THRESH:
            key = "mys:" + best.id
            if key not in groups:
                lane = Lane(kind="sample", sound=key, name=best.name, auto=True)
                groups[key] = lane
                lanes.append(lane)
            events.append(_event(groups[key].id, o, spb, start_beat))
        else:
            unknown.append(o)

    if unknown:
        u_lanes, u_events = band_split(unknown, spb, start_beat)
        lanes += u_lanes
        events += u_events
    return lanes, events


def band_split(onsets, spb, start_beat):
    """Return (new_lanes, new_events). Groups hits into brightness bands, one track each."""
    if not onsets:
        return [], []
    brights = [o["bright"] for o in onsets]
    mn, mx = min(brights), max(brights)
    span = max(1e-3, mx - mn)
    K = max(2, min(MASTER_MAX, round(span / 0.045)))
    band_lane = {}
    lanes, events = [], []
    for o in onsets:
        b = int((o["bright"] - mn) / span * K)
        b = max(0, min(K - 1, b))
        if b not in band_lane:
            sound = _PALETTE[min(len(_PALETTE) - 1, round(b / max(1, K - 1) * (len(_PALETTE) - 1)))]
            lane = Lane(kind="drum", sound=sound, name=sound.capitalize(), auto=True)
            band_lane[b] = lane
            lanes.append(lane)
        lane = band_lane[b]
        events.append(Event(lane_id=lane.id,
                            beat=start_beat + o["t"] / spb,
                            vel=max(0.4, min(1.0, o["amp"])),
                            length=o["dur"] / spb,
                            src_t=o["t"], src_dur=min(2.5, o["dur"])))
    return lanes, events
