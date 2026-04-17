from . import zamco, bnf, jadecap, marci, nbb, umar, kane, liquidity_hunter, alpha_x
from . import fvg, ote, cvd_divergence, wyckoff, cbg, bb_trend, band_rider

MULTI_STRATEGIES = {
    "zamco": zamco.signal,
    "bnf": bnf.signal,
    "jadecap": jadecap.signal,
    "marci": marci.signal,
    "nbb": nbb.signal,
    "umar": umar.signal,
    "kane": kane.signal,
    "fvg": fvg.signal,
    "ote": ote.signal,
    "cvd_divergence": cvd_divergence.signal,
    "wyckoff": wyckoff.signal,
    "cbg": cbg.signal,
    "bb_trend": bb_trend.signal,
    "band_rider": band_rider.signal,
    "liquidity_hunter": liquidity_hunter.signal,
    "alpha_x": alpha_x.signal,
}
