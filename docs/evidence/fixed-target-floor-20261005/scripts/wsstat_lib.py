import json, glob, sys, statistics as st
from pathlib import Path

def rank(v):
    order = sorted(v, key=lambda c: -v[c]); r = {}
    i = 0
    while i < len(order):  # average ranks for ties
        j = i
        while j + 1 < len(order) and abs(v[order[j + 1]] - v[order[i]]) < 1e-3: j += 1
        for k in range(i, j + 1): r[order[k]] = (i + j) / 2
        i = j + 1
    return r
def spearman(a, b):
    keys = [k for k in a if k in b]
    if len(keys) < 3: return None
    ra, rb = rank({k: a[k] for k in keys}), rank({k: b[k] for k in keys})
    ma, mb = st.mean(ra.values()), st.mean(rb.values())
    num = sum((ra[k] - ma) * (rb[k] - mb) for k in keys)
    den = (sum((ra[k] - ma) ** 2 for k in keys) * sum((rb[k] - mb) ** 2 for k in keys)) ** .5
    return num / den if den else 0.
def top(v, n=3): return set(sorted(v, key=lambda c: -v[c])[:n])
def flat(v):  # share of damage stats with identical value (breakpoint/rate-limited)
    d = [v[c] for c in ('0', '1', 'D', '4', 'CO', 'VI', 'W', 'Y') if c in v]
    return max(sum(abs(x - y) < 1e-3 for y in d) for x in d) / len(d)

