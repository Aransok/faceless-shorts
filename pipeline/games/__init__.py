"""Game-night round modules (Phase 16). Each module (higher_or_lower,
memory, what_changed, risk_or_safe, prediction) exposes
generate_round(session, avoid_topics, round_index) -> (beats, session) --
see base.py for the shared session/scoring, round-selector, beat schema,
and fact-verification helper every module builds on.
"""
