#!/usr/bin/env python3
"""
ai-sports-autobet - Agente AI autonomo per pronostici sportivi
Flusso dell'agente:
1. Raccolta dati: Richiede dati sportivi da API esterne (statistiche, quote, form)
2. Analisi AI: Analizza i dati raccolti utilizzando algoritmi di machine learning
3. Selezione giocate: Sceglie le 3 migliori scommesse giornaliere in base all'analisi
4. Invio Telegram: Formatta e invia i pronostici al canale/gruppo Telegram
5. Scheduling: Esegue automaticamente il processo ogni giorno a un orario prestabilito
"""
import os
import logging
from datetime import datetime, date
from typing import List, Dict, Any

# API e comunicazione
import requests
from telegram import Bot

# Scheduling
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# Data processing e AI (euristiche)
import numpy as np

# ============================================================================
# CONFIGURAZIONE
# ============================================================================
API_FOOTBALL_KEY = os.getenv('API_FOOTBALL_KEY', 'YOUR_API_FOOTBALL_KEY_HERE')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN_HERE')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_TELEGRAM_CHAT_ID_HERE')

API_FOOTBALL_BASE_URL = 'https://v3.football.api-sports.io'
API_BASKET_BASE_URL = 'https://v1.basketball.api-sports.io'
API_VOLLEY_BASE_URL = 'https://v1.volleyball.api-sports.io'
API_SPORTS_HEADERS = {
    'x-apisports-key': API_FOOTBALL_KEY
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# RACCOLTA DATI
# ============================================================================

def fetch_football_matches(date_str: str) -> List[Dict[str, Any]]:
    try:
        url = f'{API_FOOTBALL_BASE_URL}/fixtures'
        params = {'date': date_str}
        r = requests.get(url, headers=API_SPORTS_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get('response', [])
    except Exception as e:
        logger.error(f"Errore nel recupero partite calcio: {e}")
        return []


def fetch_basketball_games(date_str: str) -> List[Dict[str, Any]]:
    try:
        url = f'{API_BASKET_BASE_URL}/games'
        params = {'date': date_str}
        r = requests.get(url, headers=API_SPORTS_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get('response', [])
    except Exception as e:
        logger.error(f"Errore nel recupero partite basket: {e}")
        return []


def fetch_tennis_matches(date_str: str) -> List[Dict[str, Any]]:
    logger.info(f"Recupero partite tennis per {date_str} - PLACEHOLDER")
    return []


def fetch_volleyball_matches(date_str: str) -> List[Dict[str, Any]]:
    try:
        url = f'{API_VOLLEY_BASE_URL}/games'
        params = {'date': date_str}
        r = requests.get(url, headers=API_SPORTS_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get('response', [])
    except Exception as e:
        logger.error(f"Errore nel recupero partite volley: {e}")
        return []

# ============================================================================
# ANALISI/SCORING
# ============================================================================

def safe_get(d: Dict[str, Any], path: List[Any], default=None):
    cur = d
    for p in path:
        if isinstance(p, int):
            if isinstance(cur, list) and 0 <= p < len(cur):
                cur = cur[p]
            else:
                return default
        else:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
    return cur


def compute_moneyline_probs(odds_home: float | None, odds_away: float | None) -> Dict[str, float]:
    probs = {'home': 0.5, 'away': 0.5}
    vals = {}
    if odds_home and odds_home > 1.0:
        vals['home'] = 1.0 / odds_home
    if odds_away and odds_away > 1.0:
        vals['away'] = 1.0 / odds_away
    if vals:
        s = sum(vals.values())
        probs = {k: v / s for k, v in vals.items()}
        if 'home' not in probs:
            probs['home'] = 1 - probs.get('away', 0.5)
        if 'away' not in probs:
            probs['away'] = 1 - probs.get('home', 0.5)
    return probs


def value_score(prob: float, odds: float | None) -> float:
    if not odds or odds <= 1.0:
        return 0.0
    ev = prob * (odds - 1) - (1 - prob)
    return float(1 / (1 + np.exp(-ev * 4)))


def build_event_candidates(dati: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    # Football
    for fx in dati.get('football', []) or []:
        league = safe_get(fx, ['league', 'name'], '')
        home = safe_get(fx, ['teams', 'home', 'name'], 'Home')
        away = safe_get(fx, ['teams', 'away', 'name'], 'Away')
        fixture_time = safe_get(fx, ['fixture', 'date'], None)
        odds_home = safe_get(fx, ['odds', 'bookmakers', 0, 'bets', 0, 'values', 0, 'odd'], None)
        odds_away = safe_get(fx, ['odds', 'bookmakers', 0, 'bets', 0, 'values', 1, 'odd'], None)
        try:
            odds_home = float(odds_home) if odds_home else None
            odds_away = float(odds_away) if odds_away else None
        except Exception:
            odds_home, odds_away = None, None
        probs = compute_moneyline_probs(odds_home, odds_away)
        home_form = 0.5
        away_form = 0.5
        league_weight = 0.55 if ('Serie' in league or 'Premier' in league) else 0.5
        p_home = 0.6 * probs['home'] + 0.3 * home_form + 0.1 * league_weight
        p_away = 0.6 * probs['away'] + 0.3 * away_form + 0.1 * (1 - league_weight)
        vh = value_score(p_home, odds_home)
        va = value_score(p_away, odds_away)
        if vh >= va:
            candidates.append({
                'sport': 'football', 'market': '1X2', 'pick': '1',
                'event': f"{home} vs {away}", 'league': league, 'start': fixture_time,
                'odds': odds_home, 'prob': round(p_home, 3),
                'confidence': round(0.5 * p_home + 0.5 * vh, 3),
                'rationale': f"Probabilità implicita e contesto favorevoli a {home}. Value={vh:.2f}"
            })
        else:
            candidates.append({
                'sport': 'football', 'market': '1X2', 'pick': '2',
                'event': f"{home} vs {away}", 'league': league, 'start': fixture_time,
                'odds': odds_away, 'prob': round(p_away, 3),
                'confidence': round(0.5 * p_away + 0.5 * va, 3),
                'rationale': f"Probabilità/quote migliori su {away}. Value={va:.2f}"
            })

    # Basketball
    for bx in dati.get('basketball', []) or []:
        league = safe_get(bx, ['league', 'name'], '')
        home = safe_get(bx, ['teams', 'home', 'name'], 'Home')
        away = safe_get(bx, ['teams', 'away', 'name'], 'Away')
        game_time = safe_get(bx, ['date'], None) or safe_get(bx, ['game', 'date'], None)
        odds_home = safe_get(bx, ['odds', 'bookmakers', 0, 'bets', 0, 'values', 0, 'odd'], None)
        odds_away = safe_get(bx, ['odds', 'bookmakers', 0, 'bets', 0, 'values', 1, 'odd'], None)
        try:
            odds_home = float(odds_home) if odds_home else None
            odds_away = float(odds_away) if odds_away else None
        except Exception:
            odds_home, odds_away = None, None
        probs = compute_moneyline_probs(odds_home, odds_away)
        home_form, away_form = 0.5, 0.5
        league_weight = 0.5
        p_home = 0.6 * probs['home'] + 0.3 * home_form + 0.1 * league_weight
        p_away = 0.6 * probs['away'] + 0.3 * away_form + 0.1 * (1 - league_weight)
        vh = value_score(p_home, odds_home)
        va = value_score(p_away, odds_away)
        if vh >= va:
            candidates.append({
                'sport': 'basketball', 'market': 'ML', 'pick': 'Home',
                'event': f"{home} vs {away}", 'league': league, 'start': game_time,
                'odds': odds_home, 'prob': round(p_home, 3),
                'confidence': round(0.5 * p_home + 0.5 * vh, 3),
                'rationale': f"Moneyline favorevole a {home}. Value={vh:.2f}"
            })
        else:
            candidates.append({
                'sport': 'basketball', 'market': 'ML', 'pick': 'Away',
                'event': f"{home} vs {away}", 'league': league, 'start': game_time,
                'odds': odds_away, 'prob': round(p_away, 3),
                'confidence': round(0.5 * p_away + 0.5 * va, 3),
                'rationale': f"Moneyline favorevole a {away}. Value={va:.2f}"
            })

    # Volleyball
    for vx in dati.get('volleyball', []) or []:
        league = safe_get(vx, ['league', 'name'], '')
        home = safe_get(vx, ['teams', 'home', 'name'], 'Home')
        away = safe_get(vx, ['teams', 'away', 'name'], 'Away')
        game_time = safe_get(vx, ['date'], None)
        odds_home = safe_get(vx, ['odds', 'bookmakers', 0, 'bets', 0, 'values', 0, 'odd'], None)
        odds_away = safe_get(vx, ['odds', 'bookmakers', 0, 'bets', 0, 'values', 1, 'odd'], None)
        try:
            odds_home = float(odds_home) if odds_home else None
            odds_away = float(odds_away) if odds_away else None
        except Exception:
            odds_home, odds_away = None, None
        probs = compute_moneyline_probs(odds_home, odds_away)
        home_form, away_form = 0.5, 0.5
        league_weight = 0.5
        p_home = 0.6 * probs['home'] + 0.3 * home_form + 0.1 * league_weight
        p_away = 0.6 * probs['away'] + 0.3 * away_form + 0.1 * (1 - league_weight)
        vh = value_score(p_home, odds_home)
        va = value_score(p_away, odds_away)
        if vh >= va:
            candidates.append({
                'sport': 'volleyball', 'market': 'ML', 'pick': 'Home',
                'event': f"{home} vs {away}", 'league': league, 'start': game_time,
                'odds': odds_home, 'prob': round(p_home, 3),
                'confidence': round(0.5 * p_home + 0.5 * vh, 3),
                'rationale': f"Favorita squadra di casa. Value={vh:.2f}"
            })
        else:
            candidates.append({
                'sport': 'volleyball', 'market': 'ML', 'pick': 'Away',
                'event': f"{home} vs {away}", 'league': league, 'start': game_time,
                'odds': odds_away, 'prob': round(p_away, 3),
                'confidence': round(0.5 * p_away + 0.5 * va, 3),
                'rationale': f"Favorita squadra ospite. Value={va:.2f}"
            })

    return candidates


def raccolta_dati() -> Dict[str, Any]:
    logger.info("Inizio raccolta dati sportivi...")
    today = date.today().isoformat()
    logger.info(f"Recupero eventi per la data: {today}")
    eventi = {
        'football': fetch_football_matches(today),
        'basketball': fetch_basketball_games(today),
        'tennis': fetch_tennis_matches(today),
        'volleyball': fetch_volleyball_matches(today),
        'data_raccolta': today,
    }
    total_events = sum(len(eventi[s]) for s in ['football', 'basketball', 'tennis', 'volleyball'])
    logger.info(f"Totale eventi raccolti: {total_events}")
    return eventi


def analisi_dati(dati: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Inizio analisi dati con AI (euristiche)...")
    candidates = build_event_candidates(dati)
    for c in candidates:
        odds = c.get('odds') or 0
        penalty = 0.0
        if odds and odds < 1.3:
            penalty = 0.1
        elif odds and odds > 5.0:
            penalty = 0.05
        c['confidence'] = round(max(0.0, c['confidence'] - penalty), 3)
    return {'eventi_analizzati': len(candidates), 'timestamp': datetime.now().isoformat(), 'predizioni': candidates}


def seleziona_giocate(analisi: Dict[str, Any]) -> List[Dict[str, Any]]:
    logger.info("Selezione delle 3 migliori giocate...")
    preds = list(analisi.get('predizioni', []))
    preds.sort(key=lambda x: x.get('confidence', 0), reverse=True)
    result: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for p in preds:
        sport = p.get('sport', 'unknown')
        if counts.get(sport, 0) >= 2 and len(result) < 3:
            continue
        result.append(p)
        counts[sport] = counts.get(sport, 0) + 1
        if len(result) == 3:
            break
    return result


def format_telegram_message(giocate: List[Dict[str, Any]], data_str: str) -> str:
    if not giocate:
        return f"📅 {data_str}\nNessuna giocata consigliata oggi."
    lines = [f"📅 {data_str} - Top 3 giocate AI", ""]
    for i, g in enumerate(giocate, start=1):
        lines.append(
           
