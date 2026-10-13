"""Request-local search accounting; never shared across combat contexts."""
from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps
import hashlib
import os
import pickle
import time
from dataclasses import replace
from collections.abc import Mapping

SESSION = ContextVar('riven_search_session', default=None)
# A live request (the build page re-solves on every edit) that a newer one
# from the same page has replaced: the HTTP layer sets this predicate, and the
# search stops at its next heartbeat instead of finishing for nobody.
CANCEL = ContextVar('search_cancel', default=None)


class SearchCancelled(BaseException):
    """A newer request superseded this one.

    A BaseException, like asyncio's CancelledError, so the engine's
    ``except Exception`` fallbacks cannot swallow it and carry on.
    """


def check_cancelled():
    cancelled = CANCEL.get()
    if cancelled is not None and cancelled():
        raise SearchCancelled()


# A long search (the riven analysis) that lets waiting build-page requests use
# the engine between two evaluations: the HTTP layer sets the hook, which
# hands the engine over and takes it back.
YIELD = ContextVar('search_yield', default=None)


def session_request(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        request = args[1] if len(args) > 1 else kwargs['request']
        if not isinstance(request, Mapping):
            return fn(*args, **kwargs)  # Preserve the engine's input error.
        if request.get('_bakeStaticsOnly'):
            # A bake has no interactive budget (its statics must not depend on
            # the machine's load) but shares the request's search memo.
            token = SESSION.set(dict(start=time.monotonic(), deadline=float('inf'), phaseSeconds=float('inf'),
                                     stage='baseline', hook=None, evaluations=0, memoHits=0, memo=OrderedDict(),
                                     searches=OrderedDict(), limited=0, lastBeat=0.))
            try:
                return fn(*args, **kwargs)
            finally:
                SESSION.reset(token)
        profile = str(request.get('profile') or 'standard').strip().casefold()
        state = dict(start=time.monotonic(), deadline=time.monotonic() +
                     {'fast':45., 'standard':90., 'deep':240.}.get(profile,90.),
                     phaseSeconds={'fast':8.,'standard':15.,'deep':45.}.get(profile,15.),
                     stage='baseline', hook=kwargs.get('progress_hook'), evaluations=0,
                     memoHits=0, memo=OrderedDict(), searches=OrderedDict(), limited=0,
                     lastBeat=0.)
        token = SESSION.set(state)
        try:
            result = fn(*args, **kwargs)
            result['searchWork'] = {key: state[key] for key in ('evaluations','memoHits','limited')}
            result['searchWork'].update(elapsedSeconds=time.monotonic()-state['start'],
                budgetSeconds=state['deadline']-state['start'],
                status='heuristic-budget-limited' if state['limited'] else 'heuristic-best-found')
            result['searchStatus']['work'] = result['searchWork']
            if state['limited']:
                result['searchStatus']['status'] = 'heuristic-budget-limited'
                result['skipped'].append('搜索达到交互预算，返回已找到的合法配装；未证明全局最优')
            return result
        finally:
            SESSION.reset(token)
    return run


def heartbeat(count=0):
    check_cancelled()
    hand_over = YIELD.get()
    if hand_over is not None:
        hand_over()
    state = SESSION.get()
    if state is None:
        return
    state['evaluations'] += count
    now = time.monotonic()
    if state['hook'] and now - state['lastBeat'] > 1.:
        state['lastBeat'] = now
        try:
            state['hook'](f"{state['stage']}|{state['evaluations']}")
        except Exception:
            pass  # Progress reporting is never part of numerical evaluation.


def memoized_search(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        state = SESSION.get()
        if state is None:
            return fn(*args, **kwargs)
        wire_kwargs = dict(kwargs)
        scenario = wire_kwargs.get('scenario')
        if scenario is not None:
            wire_kwargs['scenario'] = replace(scenario, conditional_stacks=dict(scenario.conditional_stacks))
        try:
            key = hashlib.sha256(pickle.dumps((args, wire_kwargs), protocol=5)).digest()
        except (TypeError, pickle.PicklingError):
            return fn(*args, **kwargs)
        memo = state['searches']
        if key in memo:
            state['memoHits'] += 1
            return memo[key]
        result = fn(*args, **kwargs)
        memo[key] = result
        if len(memo) > 256:
            memo.popitem(last=False)
        return result
    return run


# Benchmarks and exact-output comparisons turn the interactive budget off: with
# it, how far a search gets depends on the machine's speed and load.
UNBOUNDED = os.environ.get('WF_SEARCH_NO_DEADLINE') == '1'


def phase_deadline():
    state = SESSION.get()
    if UNBOUNDED:
        return float('inf')
    return min(state['deadline'],time.monotonic()+state['phaseSeconds']) if state else float('inf')


def expired(deadline):
    if UNBOUNDED or time.monotonic() < deadline:
        return False
    state = SESSION.get()
    if state is not None:
        state['limited'] += 1
    return True
