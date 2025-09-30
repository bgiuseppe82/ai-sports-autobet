#!/usr/bin/env python3
"""
ai-sports-autobet - Agente AI autonomo per pronostici sportivi
"""
import os
import logging
from datetime import datetime, date
from typing import List, Dict, Any
import requests
from telegram import Bot
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import numpy as np

API_FOOTBALL_KEY = os.getenv('API_FOOTBALL_KEY', 'YOUR_API_FOOTBALL_KEY_HERE')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN_HERE')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_TELEGRAM_CHAT_ID_HERE')

API_FOOTBALL_BASE_URL = 'https://v3.football.api-sports.io'
API_BASKET_BASE_URL = 'https://v1.basketball.api-sports.io'
API_VOLLEY_BASE_URL = 'https://v1.volleyball.api-sports.io'
API_SPORTS_HEADERS = {'x-apisports-key': API_FOOTBALL_KEY}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_football_matches(date_str: str) -> List[Dict[str, Any]]:
    try:
        r = requests.get(f'{API_FOOTBALL_BASE_URL}/fixtures', headers=API_SPORTS_HEADERS, params={'date': date_str}, timeout=15)
        r.raise_for_status(); return r.json().get('response', [])
    except Exception as e:
        logger.error(f"Errore nel recupero partite calcio: {e}"); return []

def fetch_basketball_games(date_str: str) -> List[Dict[str, Any]]:
    try:
        r = requests.get(f'{API_BASKET_BASE_URL}/games', headers=API_SPORTS_HEADERS, params={'date': date_str}, timeout=15)
        r.raise_for_status(); return r.json().get('response', [])
    except Exception as e:
        logger.error(f"Errore nel recupero partite basket: {e}"); return []

def fetch_tennis_matches(date_str: str) -> List[Dict[str, Any]]:
    logger.info(f"Recupero partite tennis per {date_str} - PLACEHOLDER"); return []

def fetch_volleyball_matches(date_str: str) -> List[Dict[str, Any]]:
    try:
        r = requests.get(f'{API_VOLLEY_BASE_URL}/games', headers=API_SPORTS_HEADERS, params={'date': date_str}, timeout=15)
        r.raise_for_status(); return r.json().get('response', [])
    except Exception as e:
        logger.error(f"Errore nel recupero partite volley: {e}"); return []

def safe_get(d: Dict[str, Any], path: List[Any], default=None):
    cur = d
    for p in path:
        if isinstance(p, int):
            if isinstance(cur, list) and 0 <= p < len(cur): cur = cur[p]
            else: return default
        else:
            if isinstance(cur, dict) and p in cur: cur = cur[p]
            else: return default
    return cur

def compute_moneyline_probs(odds_home: float | None, odds_away: float | None) -> Dict[str, float]:
    probs = {'home': 0.5, 'away': 0.5}
    vals = {}
    if odds_home and odds_home > 1.0: vals['home'] = 1.0 / odds_home
    if odds_away and odds_away > 1.0: vals['away'] = 1.0 / odds_away
    if vals:
        s = sum(vals.values()); probs = {k: v / s for k, v in vals.items()}
        if 'home' not in probs: probs['home'] = 1 - probs.get('away', 0.5)
        if 'away' not in probs: probs['away'] = 1 - probs.get('home', 0.5)
    return probs

def value_score(prob: float, odds: float | None) -> float:
    if not odds or odds <= 1.0: return 0.0
    ev = prob * (odds - 1) - (1 - prob)
    return float(1 / (1 + np.exp(-ev * 4)))

def build_event_candidates(dati: Dict[str, Any]) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    for fx in dati.get('football', []) or []:
        league = safe_get(fx, ['league','name'], '')
        home = safe_get(fx, ['teams','home','name'], 'Home')
        away = safe_get(fx, ['teams','away','name'], 'Away')
        t = safe_get(fx, ['fixture','date'], None)
        oh = safe_get(fx, ['odds','bookmakers',0,'bets',0,'values',0,'odd'], None)
        oa = safe_get(fx, ['odds','bookmakers',0,'bets',0,'values',1,'odd'], None)
        try: oh = float(oh) if oh else None; oa = float(oa) if oa else None
        except Exception: oh, oa = None, None
        probs = compute_moneyline_probs(oh, oa)
        home_form = away_form = 0.5
        lw = 0.55 if ('Serie' in league or 'Premier' in league) else 0.5
        ph = 0.6*probs['home'] + 0.3*home_form + 0.1*lw
        pa = 0.6*probs['away'] + 0.3*away_form + 0.1*(1-lw)
        vh, va = value_score(ph, oh), value_score(pa, oa)
        if vh >= va:
            cands.append({'sport':'football','market':'1X2','pick':'1','event':f"{home} vs {away}", 'league':league,'start':t,'odds':oh,'prob':round(ph,3),'confidence':round(0.5*ph+0.5*vh,3),'rationale':f"Prob./contesto favorevoli a {home}. Value={vh:.2f}"})
        else:
            cands.append({'sport':'football','market':'1X2','pick':'2','event':f"{home} vs {away}", 'league':league,'start':t,'odds':oa,'prob':round(pa,3),'confidence':round(0.5*pa+0.5*va,3),'rationale':f"Miglior value su {away}. Value={va:.2f}"})
    for bx in dati.get('basketball', []) or []:
        league = safe_get(bx, ['league','name'], '')
        home = safe_get(bx, ['teams','home','name'], 'Home')
        away = safe_get(bx, ['teams','away','name'], 'Away')
        t = safe_get(bx, ['date'], None) or safe_get(bx, ['game','date'], None)
        oh = safe_get(bx, ['odds','bookmakers',0,'bets',0,'values',0,'odd'], None)
        oa = safe_get(bx, ['odds','bookmakers',0,'bets',0,'values',1,'odd'], None)
        try: oh = float(oh) if oh else None; oa = float(oa) if oa else None
        except Exception: oh, oa = None, None
        probs = compute_moneyline_probs(oh, oa)
        ph = 0.6*probs['home'] + 0.3*0.5 + 0.1*0.5
        pa = 0.6*probs['away'] + 0.3*0.5 + 0.1*0.5
        vh, va = value_score(ph, oh), value_score(pa, oa)
        if vh >= va:
            cands.append({'sport':'basketball','market':'ML','pick':'Home','event':f"{home} vs {away}", 'league':league,'start':t,'odds':oh,'prob':round(ph,3),'confidence':round(0.5*ph+0.5*vh,3),'rationale':f"Moneyline favorevole a {home}. Value={vh:.2f}"})
        else:
            cands.append({'sport':'basketball','market':'ML','pick':'Away','event':f"{home} vs {away}", 'league':league,'start':t,'odds':oa,'prob':round(pa,3),'confidence':round(0.5*pa+0.5*va,3),'rationale':f"Moneyline favorevole a {away}. Value={va:.2f}"})
    for vx in dati.get('volleyball', []) or []:
        league = safe_get(vx, ['league','name'], '')
        home = safe_get(vx, ['teams','home','name'], 'Home')
        away = safe_get(vx, ['teams','away','name'], 'Away')
        t = safe_get(vx, ['date'], None)
        oh = safe_get(vx, ['odds','bookmakers',0,'bets',0,'values',0,'odd'], None)
        oa = safe_get(vx, ['odds','bookmakers',0,'bets',0,'values',1,'odd'], None)
        try: oh = float(oh) if oh else None; oa = float(oa) if oa else None
        except Exception: oh, oa = None, None
        probs = compute_moneyline_probs(oh, oa)
        ph = 0.6*probs['home'] + 0.3*0.5 + 0.1*0.5
        pa = 0.6*probs['away'] + 0.3*0.5 + 0.1*0.5
        vh, va = value_score(ph, oh), value_score(pa, oa)
        if vh >= va:
            cands.append({'sport':'volleyball','market':'ML','pick':'Home','event':f"{home} vs {away}", 'league':league,'start':t,'odds':oh,'prob':round(ph,3),'confidence':round(0.5*ph+0.5*vh,3),'rationale':f"Favorita squadra di casa. Value={vh:.2f}"})
        else:
            cands.append({'sport':'volleyball','market':'ML','pick':'Away','event':f"{home} vs {away}", 'league':league,'start':t,'odds':oa,'prob':round(pa,3),'confidence':round(0.5*pa+0.5*va,3),'rationale':f"Favorita squadra ospite. Value={va:.2f}"})
    return cands

def raccolta_dati() -> Dict[str, Any]:
    today = date.today().isoformat()
    logger.info(f"Recupero eventi per la data: {today}")
    eventi = {'football': fetch_football_matches(today), 'basketball': fetch_basketball_games(today), 'tennis': fetch_tennis_matches(today), 'volleyball': fetch_volleyball_matches(today), 'data_raccolta': today}
    logger.info(f"Totale eventi raccolti: {sum(len(eventi[s]) for s in ['football','basketball','tennis','volleyball'])}")
    return eventi

def analisi_dati(dati: Dict[str, Any]) -> Dict[str, Any]:
    cands = build_event_candidates(dati)
    for c in cands:
        odds = c.get('odds') or 0; pen = 0.0
        if odds and odds < 1.3: pen = 0.1
        elif odds and odds > 5.0: pen = 0.05
        c['confidence'] = round(max(0.0, c['confidence'] - pen), 3)
    return {'eventi_analizzati': len(cands), 'timestamp': datetime.now().isoformat(), 'predizioni': cands}

def seleziona_giocate(analisi: Dict[str, Any]) -> List[Dict[str, Any]]:
    preds = sorted(list(analisi.get('predizioni', [])), key=lambda x: x.get('confidence',0), reverse=True)
    res: List[Dict[str, Any]] = []; counts: Dict[str,int] = {}
    for p in preds:
        s = p.get('sport','unknown')
        if counts.get(s,0) >= 2 and len(res) < 3: continue
        res.append(p); counts[s] = counts.get(s,0)+1
        if len(res) == 3: break
    return res

def format_telegram_message(giocate: List[Dict[str, Any]], data_str: str) -> str:
    if not giocate: return f"📅 {data_str}\nNessuna giocata consigliata oggi."
    lines = [f"📅 {data_str} - Top 3 giocate AI", ""]
    for i,g in enumerate(giocate, start=1):
        lines.append(f"{i}) {g['sport'].title()} • {g['event']}\n   Pick: {g['market']} {g['pick']} @ {g.get('odds','-')}\n   Prob: {g.get('prob',0):.2f} • Conf: {g.get('confidence',0):.2f}\n   Motivo: {g.get('rationale','-')}")
    return "\n".join(lines)

def invia_telegram(giocate: List[Dict[str, Any]], data_str: str) -> None:
    if TELEGRAM_BOT_TOKEN.startswith('YOUR_') or TELEGRAM_CHAT_ID.startswith('YOUR_'):
        logger.warning("Telegram non configurato: salta invio."); return
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        msg = format_telegram_message(giocate, data_str)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        logger.info("Messaggio Telegram inviato")
    except Exception as e:
        logger.error(f"Errore invio Telegram: {e}")

def processo_giornaliero():
    try:
        logger.info("="*50); logger.info("Avvio processo giornaliero"); logger.info("="*50)
        dati = raccolta_dati()
        analisi = analisi_dati(dati)
        giocate = seleziona_giocate(analisi)
        invia_telegram(giocate, dati.get('data_raccolta', date.today().isoformat()))
        logger.info("Processo giornaliero completato con successo")
    except Exception as e:
        logger.error(f"Errore durante il processo giornaliero: {e}")

def main():
    logger.info("Avvio AI Sports Autobet Agent")
    if API_FOOTBALL_KEY == 'YOUR_API_FOOTBALL_KEY_HERE':
        logger.warning("ATTENZIONE: API Football key non configurata!")
    scheduler = BlockingScheduler()
    scheduler.add_job(processo_giornaliero, trigger=CronTrigger(hour=10, minute=0), id='processo_giornaliero', name='Processo giornaliero pronostici')
    logger.info("Scheduler configurato. In attesa di esecuzione...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown richiesto. Arresto scheduler..."); scheduler.shutdown()

if __name__ == '__main__':
    main()
