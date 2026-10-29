"""AI assistant of the app (Claude via the official Anthropic SDK).

The analysis computes, the model explains. Numbers come from tools that read the same JSON as the page
(app/web/data) and rank candidates with the study's own TOPSIS and budget plan (fi.decision), so the assistant
and the screen agree. It can open a club, position or tab on the page (show_in_app), knows football in general
and can search the web for what the data does not cover.

The answer streams to the page as server-sent events: thinking summary, tool steps, text, sources.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pandas as pd

from fi import decision as fd
from fi.matching import norm

log = logging.getLogger("fi.assistant")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "web" / "data"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 10
MAX_TURNS = 40                       # user messages per conversation
MAX_MESSAGE = 2000                   # characters
RATE = (30, 600)                     # messages per client per 10 minutes


def _load_env() -> None:
    """Minimal .env reader (KEY=VALUE lines); real environment variables win."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
DAILY = int(os.getenv("FI_AI_DAILY", "300"))   # questions per day from everyone: a public link spends the owner's key
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("ANTHROPIC_EFFORT", "medium")
WEB_SEARCH = os.getenv("FI_WEB_SEARCH", "1") != "0"


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


SLOT_RU = {
    "GK": "вратарь", "RB": "правый защитник", "RCB": "правый центральный защитник", "CB": "центральный защитник",
    "LCB": "левый центральный защитник", "LB": "левый защитник", "RWB": "правый латераль", "LWB": "левый латераль",
    "RDM": "правый опорный полузащитник", "CDM": "опорный полузащитник", "LDM": "левый опорный полузащитник",
    "RCM": "правый центральный полузащитник", "CM": "центральный полузащитник", "LCM": "левый центральный полузащитник",
    "RM": "правый полузащитник", "LM": "левый полузащитник", "RW": "правый вингер", "LW": "левый вингер",
    "RAM": "правый атакующий полузащитник", "CAM": "атакующий полузащитник", "LAM": "левый атакующий полузащитник",
    "RCF": "правый нападающий", "LCF": "левый нападающий", "ST": "нападающий", "SS": "второй нападающий",
}
TABS = {"club": "Клуб", "player": "Игрок", "replace": "Кем заменить", "plan": "План трансферов",
        "value": "Стоимость", "finance": "Доходность", "method": "Как это работает"}
VIEWS = {"lineup": "Состав", "network": "Сеть передач", "scored": "Где забиваем", "conceded": "Где пропускаем"}
X_BANDS = ["далеко от ворот (дальше 36 ярдов)", "перед штрафной (18–36 ярдов)", "в штрафной (6–18 ярдов)",
           "у ворот (вратарская)"]
SIDES = ["левый фланг", "левый полуфланг", "центр", "правый полуфланг", "правый фланг"]   # the shooting team's view


def money(v) -> Optional[str]:
    if v is None or pd.isna(v):
        return None
    return f"€{v / 1e6:.1f} млн" if v < 1e7 else f"€{v / 1e6:.0f} млн"


def pct(v) -> Optional[str]:
    return None if v is None else f"{v * 100:+.0f}%"


# ---- the app's data -------------------------------------------------------------------------

class Data:
    """The JSON the page reads, loaded once: index, candidate pool, every league's clubs."""

    def __init__(self, folder: Path = DATA):
        self.folder = folder
        self._lock = threading.Lock()
        self._ready = False

    def _read(self, name: str):
        return json.loads((self.folder / name).read_text(encoding="utf-8"))

    def load(self) -> "Data":
        with self._lock:
            if not self._ready:
                self.index = self._read("index.json")
                self.pool = pd.DataFrame(self._read("pool.json"))
                self.leagues = {l["name"]: self._read(l["file"]) for l in self.index["leagues"]}
                self.team_league = {t: n for n, lg in self.leagues.items() for t in lg["clubs"]}
                self.ru = {c["name"]: c["ru"] for c in self.index["candidate_leagues"]}
                self.metrics = {m: v["label"] for m, v in self.index["metrics"].items()}
                self._ready = True
        return self

    def team(self, name: str) -> str:
        if name in self.team_league:
            return name
        keys = {norm(t): t for t in self.team_league}
        k = norm(name)
        if k in keys:
            return keys[k]
        hits = [t for kk, t in keys.items() if k and (k in kk or kk in k)]
        if len(hits) == 1:
            return hits[0]
        close = difflib.get_close_matches(k, list(keys), n=3, cutoff=0.6)
        raise LookupError(f"Клуба «{name}» нет среди 80 клубов приложения (названия — по-английски, как в данных). "
                          f"Похожие: {', '.join(keys[c] for c in close) or 'нет'}. Полный список — list_clubs.")

    def club(self, name: str) -> Tuple[str, dict]:
        t = self.team(name)
        return t, self.leagues[self.team_league[t]]["clubs"][t]

    def card(self, club: dict, pid: int) -> Optional[dict]:
        return next((p for p in club["players"] if p["id"] == pid), None)


DATA_ = Data()


# ---- the same ranking as on the page --------------------------------------------------------

def need_weights(slot: dict, main: Optional[dict], compare: str) -> Dict[str, float]:
    """What the new player must be good at: the role's metrics, the current player's weak ones counting up to x2
    (compare = "player"), or the position's needs over all who played there (compare = "slot")."""
    ref = (main or {}).get("groups", {}).get(slot["group"], {}).get("top6")
    if compare != "player" or not ref:
        return slot["weights"]
    raw = {m: 1 + max(0.0, 50 - (ref.get(m) if ref.get(m) is not None else 50)) / 50 for m in slot["weights"]}
    tot = sum(raw.values())
    return {m: v / tot for m, v in raw.items()}


def fit_of(pct_: dict, w: Dict[str, float]) -> float:
    return sum((pct_.get(m) or 0) * x for m, x in w.items())


def candidates(d: Data, team: str, slot: dict, *, compare: str = "player", max_age: float = 29,
               max_price: float = 50e6, leagues: Optional[List[str]] = None, only_better: bool = True,
               weights: Optional[Dict[str, float]] = None) -> Tuple[pd.DataFrame, list, Optional[float], dict]:
    """Replacement candidates for one position, ranked by TOPSIS - the page's rules (app/web/app.js candidates)."""
    _, club = d.club(team)
    main = d.card(club, slot["players"][0][0]) if slot["players"] else None
    g, rules = slot["group"], d.index["rules"]
    w = need_weights(slot, main, compare)
    eu = (main or {}).get("groups", {}).get(g, {}).get("europe")
    inc = fit_of(eu, w) if compare == "player" and eu else slot["incumbent_fit"]
    c = d.pool[d.pool["group"] == g]
    funnel = [(f"{d.index['groups'][g]} с ≥{rules['min_minutes']} мин", len(c))]

    def step(label, mask):
        nonlocal c
        c = c[mask]
        funnel.append((label, len(c)))

    step("не из своего клуба", c["team"] != team)
    if slot["side"]:
        step("играет справа" if slot["side"] == "right" else "играет слева", c[slot["side"]] >= rules["side_share"])
    allowed = leagues or [x["name"] for x in d.index["candidate_leagues"]]
    step("выбранные лиги", c["league"].isin(allowed))
    step("есть стоимость на лето 2016", c["fresh"] & c["fair"].notna() & c["age"].notna())
    step(f"не старше {max_age:g}", c["age"] <= max_age)
    step(f"до {money(max_price)}", c["value"] <= max_price)
    c = c.assign(fit=[fit_of(p, w) for p in c["pct"]], role_minutes=c["minutes"])
    if only_better:
        step("лучше текущего по потребности", c["fit"] > (inc if inc is not None else -1))
    base = {k: v["weight"] for k, v in d.index["criteria"].items()}
    crit = {k: (float((weights or base).get(k, base[k])), d.index["criteria"][k]["benefit"]) for k in base}
    if len(c):
        c = c.assign(score=fd.topsis(c, crit)).sort_values("score", ascending=False)
        c = c.assign(stability=fd.stability(c, n=400))
    return c, funnel, inc, w


def candidate_row(d: Data, p, w: Dict[str, float], future: bool) -> dict:
    row = {"name": p.name, "team": p.team, "league": d.ru.get(p.league, p.league), "team_place": int(p.team_place),
           "age": round(p.age, 1), "value": money(p.value), "fair_value": money(p.fair),
           "fair_to_price": round(p.fair / p.value, 2), "fit": round(p.fit, 1), "topsis": round(p.score, 3),
           "top3_share_random_weights": round(float(p.stability), 2), "minutes_in_role": int(p.minutes),
           "percentiles_europe": {d.metrics[m]: p.pct.get(m) for m in w}}
    if future:
        row["value_2017"], row["value_2018"] = money(p.v2017), money(p.v2018)
    return row


def slot_by_code(club: dict, code: str) -> dict:
    s = next((x for x in club["slots"] if x["code"].upper() == str(code).upper()), None)
    if s is None:
        raise LookupError(f"Позиции {code} нет в схеме клуба. Есть: " + ", ".join(x["code"] for x in club["slots"]))
    return s


# ---- system prompt --------------------------------------------------------------------------

def _glossary(d: Data) -> str:
    rows = []
    for g, ms in d.index["role_metrics"].items():
        rows.append(f"- {d.index['groups'][g]} ({g}): " + "; ".join(f"`{m}` — {d.metrics[m]}" for m in ms))
    return "\n".join(rows)


def _report(name: str) -> str:
    f = ROOT / "reports" / name
    return f.read_text(encoding="utf-8").strip() if f.exists() else "(отчёт ещё не построен)"


def system_prompt(d: Data) -> str:
    r, vm = d.index["rules"], d.index["value_model"]
    best = vm[vm["chosen"]]
    leagues = "; ".join(f"{l['ru']} ({l['name']}): " + ", ".join(c["team"] for c in l["clubs"]) for l in d.index["leagues"])
    return f"""Ты — ИИ-помощник внутри веб-приложения «Football Intelligence: от тактики к трансферам». Это командный проект Assignment 5 курса «Когнитивные технологии» (магистратура). Смотрят его студенты, преподаватель и одногруппники; многие плохо знают футбол, поэтому объясняй просто. Отвечай на любые вопросы: про приложение и его расчёты, про клубы и игроков, про методы, про футбол вообще.

## Вопрос исследования и «машина времени»
Лето 2016 года: спортивный директор готовит трансферное окно. Какие позиции у клуба слабые, какой игрок нужен на каждую и кто из подходящих стоит дешевле, чем должен? Решение принимается только по тому, что клуб мог знать тогда: события матчей сезона 2015/16 (StatsBomb Open Data) и рыночные стоимости Transfermarkt до {d.index['decision_date']}. Главный пример — «Челси» (чемпион 2014/15, 10-е место в 2015/16). Будущее (стоимости 2017 и 2018, доходность составов 2016/17–2017/18) отложено для проверки и спрятано за переключателем «Что было дальше».

## Данные
Полные сезоны 2015/16 четырёх лиг: {leagues}. Бундеслига в открытых данных — только «Байер», поэтому её игроки есть лишь среди кандидатов. Координаты StatsBomb: поле 120×80 ярдов, каждая команда атакует к x = 120. Игроки сопоставлены с Transfermarkt по клубу, имени и гражданству (99–100 % минут).

## Метод (шаги)
1. Расстановка: основная схема клуба (больше всего игрового времени), точка игрока — среднее место его действий с мячом.
2. Сила позиции: у каждой роли свои показатели на 90 минут; каждый — процентиль среди игроков той же роли с ≥{r['min_minutes']} мин; оценка позиции — среднее по игрокам, взвешенное по минутам. Эталон по умолчанию — топ-6 своей лиги (50 = медиана топ-6), можно переключить на всю лигу.
3. Потребность: позиция ниже медианы топ-6 больше чем на {50 - r['weak']} пунктов (оценка < {r['weak']}) или основному игроку {r['old']}+ лет. Требования к новичку — показатели роли; слабые места текущего игрока весят до ×2.
4. Кандидаты: игроки этой роли из пяти лиг, не из своего клуба, нужной стороны (≥{r['side_share'] * 100:.0f}% минут справа/слева), не старше {r['max_age']}, дешевле €{r['max_price'] / 1e6:.0f} млн, с оценкой лета 2016 и лучше текущего по потребности. Соответствие (fit) = Σ вес показателя × процентиль среди игроков топ-5 лиг.
5. Справедливая стоимость: {'градиентный бустинг' if vm['chosen'] == 'boosting' else 'гребневая регрессия'} по возрасту, минутам, роли, результативности, команде и лиге; оценка каждого игрока — от модели, которая его не видела (5-кратная кросс-валидация). R² {best['r2']:.2f}, типичная ошибка ×{best['median_x']:.2f}, {vm['n']} игроков. Недооценённость gap = log10(справедливая / рыночная).
6. Рейтинг: TOPSIS (метод из Assignment 4) с min-max нормализацией по критериям: соответствие 45 %, недооценённость 30 %, минуты в роли 15 %, возраст 10 % (меньше — лучше). Устойчивость — доля случайных наборов весов, при которых игрок в тройке. План трансферов — по одному игроку на каждую позицию-потребность, максимум суммы TOPSIS в пределах бюджета (перебор).
7. Перестроение при перетаскивании игрока: модель формы команды (средние позиции по отрезкам матчей и их ковариация; условное среднее остальных при закреплённом игроке). Это статистическая связь, не симулятор тактики.
8. Доходность состава: состав на конец сезона — игроки, чей последний матч сезона был за клуб; доходность — на сколько за сезон изменилась рыночная стоимость тех, кто остался, в сравнении с медианой клубов лиги. Это не выручка и не прибыль: их нет в открытых данных, а таблица трансферов Transfermarkt неполная.

## Показатели ролей
{_glossary(d)}

## Интерфейс
Сверху выбор лиги и клуба. Слева поле (вид сверху), виды: «Состав» (кружки — позиции схемы, число и цвет — оценка позиции к эталону, синий сильнее, красный слабее, обведены потребности; игрока можно перетащить, остальные сместятся), «Сеть передач» (по тренерам), «Где забиваем» и «Где пропускаем» (xG по зонам к среднему по лиге или все удары). Справа вкладки: «Клуб» (итоги сезона, потребности, тренеры), «Игрок» (показатели и процентили, стоимость, карта касаний), «Кем заменить» (кандидаты, фильтры, веса, устойчивость, «Поставить в состав»), «План трансферов» (бюджет), «Стоимость» (модель справедливой стоимости), «Доходность» (состав как актив), «Как это работает». Переключатель «Что было дальше» показывает стоимости 2018 и сезоны после решения. Кнопка «Гид» в шапке запускает пошаговый тур по сайту на примере «Челси» — предлагай её, если человек не знает, с чего начать.

## Результаты исследования для «Челси» (до решения)
Это зафиксированный отчёт исследования: кандидаты в нём сравнивались с позицией в целом и с весами по умолчанию. Экран по умолчанию сравнивает с основным игроком позиции и может стоять на других фильтрах, поэтому для соответствия, мест и баллов TOPSIS, устойчивости и плана всегда вызывай инструменты — они считают так же, как экран. Отчёт — для контекста и цитат «что зафиксировало исследование».
{_report('chelsea_candidates.txt')}

## Проверка временем (это будущее относительно решения — используй, только когда спрашивают, что было дальше, подтвердилось ли, или когда включён «Что было дальше»)
{_report('chelsea_backtest.txt')}
Честные ограничения: Канте метод бы не нашёл (центр поля не был слабым, успех 2016/17 пришёл от смены схемы на 3-4-3); тревога по вратарю оказалась ложной (Куртуа в 2016/17 — один из лучших в АПЛ; оценка вратаря за сезон по открытым данным шумная); поправки на силу лиги нет; шорт-лист мал (25 игроков); в таблице трансферов не все сделки.

## Как отвечать
- Каждое сообщение пользователя начинается с блока <ui_state> — что сейчас на экране (клуб, вкладка, выбранная позиция и игрок, фильтры, веса, бюджет, «Что было дальше»). «Этот игрок», «здесь», «на экране» — оттуда. Инструменты по умолчанию берут фильтры и веса с экрана.
- Числа про клубы, игроков, кандидатов, план и доходность бери только из инструментов (не из отчётов выше и не по памяти). Не придумывай чисел; если нужного нет — скажи, чего нет в данных. Сравнение кандидатов на замену — через find_replacements (там и соответствие текущего игрока).
- Машина времени: рекомендации — только по данным до лета 2016. Будущие стоимости и сезоны (include_future=true) — когда спрашивают про «что было дальше», проверку, или когда переключатель включён. Если упоминаешь то, что случилось после лета 2016 (из инструментов, своих знаний или поиска), явно помечай это как знание из будущего.
- Вопросы вне данных приложения (другие сезоны, правила, тактика, история, текущие новости) — отвечай из общих знаний; для свежих фактов (текущая стоимость, где сейчас играет) используй веб-поиск и говори, откуда сведения.
- Клубы и игроки в инструментах — английские названия, как в данных («Chelsea», «Atlético Madrid», «Paulo Dybala»). Пользователь может писать по-русски — переводи сам.
- show_in_app — когда пользователь просит показать или открыть что-то в интерфейсе («покажи», «открой», «поставь»). Коротко скажи, что открыл.
- Пиши по-русски, просто: сначала короткий ответ (1–3 предложения), потом пояснение. Позиции называй по-русски с кодом в скобках: «правый защитник (RB)». Деньги — «€12 млн». Процентиль объясняй как «лучше X % игроков той же роли».
- Оформление: короткие абзацы, списки, **жирный** для главного. Таблица markdown — только для сравнения 2–6 игроков или вариантов. Без заголовков первого уровня и без эмодзи.
- Рекомендации — отправная точка для скаутов: модель не видит травм, характера, контракта и того, продаст ли клуб игрока.
"""


# ---- tools --------------------------------------------------------------------------------

FUTURE = {"type": "boolean", "description": "добавить будущие значения (стоимость 2017/2018, сезоны после решения)"}
TOOLS: List[Dict[str, Any]] = [
    {"name": "list_clubs",
     "description": "Клубы приложения с местом, очками, голами, xG/xGA и схемой: все 80 клубов кратко или одна лига "
                    "подробно. Нужен, чтобы найти точное название клуба или сравнить клубы лиги.",
     "input_schema": {"type": "object", "properties": {
         "league": {"type": "string", "description": "Premier League, La Liga, Serie A или Ligue 1; пусто — все лиги"}}}},
    {"name": "get_club",
     "description": "Всё о клубе в сезоне 2015/16: итоги и стиль, схема, каждая позиция (игроки и минуты, оценка к "
                    "топ-6 и к лиге, потребность и причина), тренеры, где забивает и где пропускает (зоны к среднему "
                    "по лиге, стандарты), доходность состава по сезонам с медианой лиги.",
     "input_schema": {"type": "object", "properties": {"team": {"type": "string"}, "include_future": FUTURE},
                      "required": ["team"]}},
    {"name": "get_player",
     "description": "Карточка игрока: клуб, возраст, минуты, позиции в схеме, показатели на 90 минут и процентили к "
                    "топ-6, лиге и топ-5 лигам, рыночная и справедливая стоимость. Поиск по имени (можно часть).",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "team": {"type": "string", "description": "клуб, если имя неоднозначно"},
         "include_future": FUTURE}, "required": ["name"]}},
    {"name": "find_replacements",
     "description": "Кем заменить игрока на позиции: кандидаты из пяти лиг по правилам страницы (фильтры, "
                    "соответствие, TOPSIS, устойчивость). Без параметров фильтров и весов берёт их с экрана.",
     "input_schema": {"type": "object", "properties": {
         "team": {"type": "string"}, "slot": {"type": "string", "description": "код позиции схемы: GK, RB, LCB, ST…"},
         "compare": {"type": "string", "enum": ["player", "slot"],
                     "description": "player — к основному игроку позиции, slot — к позиции в целом (как в плане)"},
         "max_age": {"type": "number"}, "max_price_m": {"type": "number", "description": "цена не выше, € млн"},
         "leagues": {"type": "array", "items": {"type": "string"},
                     "description": "Premier League, La Liga, Serie A, Ligue 1, 1. Bundesliga"},
         "only_better": {"type": "boolean", "description": "только лучше текущего по потребности (по умолчанию да)"},
         "weights": {"type": "object", "description": "веса TOPSIS: fit, gap, age, role_minutes (любые числа)",
                     "properties": {k: {"type": "number"} for k in fd.CRITERIA}},
         "top": {"type": "integer", "description": "сколько кандидатов вернуть, 1–15 (по умолчанию 8)"},
         "include_future": FUTURE}, "required": ["team", "slot"]}},
    {"name": "transfer_plan",
     "description": "План трансферов: по одному игроку на каждую позицию-потребность, максимум суммы TOPSIS в "
                    "пределах бюджета. С include_future — стоимость в 2018 и годовая доходность плана.",
     "input_schema": {"type": "object", "properties": {
         "team": {"type": "string"}, "budget_m": {"type": "number", "description": "бюджет, € млн (по умолчанию с экрана)"},
         "include_future": FUTURE}, "required": ["team"]}},
    {"name": "search_players",
     "description": "Поиск по пулу из ~1300 игроков пяти лиг с ≥900 минут в роли: по роли, лиге, возрасту, цене; "
                    "сортировка по недооценённости, силе в роли, стоимости или одному показателю.",
     "input_schema": {"type": "object", "properties": {
         "group": {"type": "string", "enum": ["GK", "CB", "FB", "CM", "AM", "W", "CF"]},
         "leagues": {"type": "array", "items": {"type": "string"}},
         "max_age": {"type": "number"}, "max_price_m": {"type": "number"}, "min_price_m": {"type": "number"},
         "sort_by": {"type": "string", "enum": ["undervalued", "role_score", "value", "cheapest", "metric", "growth_2018"],
                     "description": "metric — по процентилю показателя metric; growth_2018 — рост к 2018 (будущее)"},
         "metric": {"type": "string", "description": "ключ показателя для sort_by = metric"},
         "top": {"type": "integer", "description": "1–25 (по умолчанию 10)"},
         "include_future": FUTURE}}},
    {"name": "show_in_app",
     "description": "Открыть в интерфейсе пользователя клуб, позицию, вкладку или вид поля. Только когда пользователь "
                    "просит показать или открыть.",
     "input_schema": {"type": "object", "properties": {
         "team": {"type": "string"}, "slot": {"type": "string", "description": "код позиции"},
         "tab": {"type": "string", "enum": list(TABS)}, "view": {"type": "string", "enum": list(VIEWS)},
         "future": {"type": "boolean", "description": "включить или выключить «Что было дальше»"}}}},
]
for _t in TOOLS:
    _t["eager_input_streaming"] = True      # inputs stream as generated; validated below before use
SERVER_TOOLS = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}] if WEB_SEARCH else []

TOOL_LABELS = {
    "list_clubs": "Смотрю список клубов", "get_club": "Смотрю клуб {team}", "get_player": "Ищу игрока {name}",
    "find_replacements": "Подбираю замену: {team}, {slot}", "transfer_plan": "Считаю план трансферов: {team}",
    "search_players": "Ищу игроков по условиям", "show_in_app": "Открываю на экране",
    "web_search": "Ищу в интернете", "web_fetch": "Читаю страницу", "code_execution": "Разбираю результаты поиска",
}
STRINGS = {"team", "slot", "name", "league", "group", "metric", "compare", "sort_by", "tab", "view"}
NUMBERS = {"max_age", "max_price_m", "min_price_m", "budget_m", "top"}
BOOLS = {"include_future", "only_better", "future"}


def _validate(name: str, args: Any) -> Optional[str]:
    """Inputs stream eagerly, so the server did not check them against the schema - do it here."""
    if not isinstance(args, dict):
        return "аргументы должны быть объектом"
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        return "неизвестный инструмент"
    props = tool["input_schema"]["properties"]
    for k in tool["input_schema"].get("required", []):
        if not isinstance(args.get(k), str) or not args[k].strip():
            return f"нужен параметр {k} (строка)"
    for k, v in args.items():
        if k not in props:
            return f"лишний параметр {k}; есть: {', '.join(props)}"
        if v is None:
            continue
        if k in STRINGS and not isinstance(v, str) or k in NUMBERS and not isinstance(v, (int, float)) \
                or k in BOOLS and not isinstance(v, bool):
            return f"неверный тип параметра {k}"
        if "enum" in props[k] and v not in props[k]["enum"]:
            return f"{k} — одно из: {', '.join(props[k]['enum'])}"
    if "leagues" in args and args["leagues"] is not None and not (
            isinstance(args["leagues"], list) and all(isinstance(x, str) for x in args["leagues"])):
        return "leagues — список названий лиг"
    if "weights" in args and args["weights"] is not None and not (
            isinstance(args["weights"], dict) and all(k in fd.CRITERIA and isinstance(v, (int, float)) and v >= 0
                                                      for k, v in args["weights"].items())):
        return "weights — {fit, gap, age, role_minutes: неотрицательные числа}"
    return None


# ---- state of one conversation ------------------------------------------------------------

@dataclass
class Session:
    id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)      # what the page shows, sent with every question
    turns: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    touched: float = field(default_factory=time.time)


_sessions: "OrderedDict[str, Session]" = OrderedDict()
_hits: Dict[str, deque] = defaultdict(deque)
_day: deque = deque()                # every question of the last 24 hours
_glock = threading.Lock()


def session(chat_id: Optional[str]) -> Session:
    with _glock:
        s = _sessions.get(chat_id or "")
        if s is None or time.time() - s.touched > 3 * 3600:
            s = Session(uuid.uuid4().hex[:12])
            _sessions[s.id] = s
        _sessions.move_to_end(s.id)
        while len(_sessions) > 100:
            _sessions.popitem(last=False)
        s.touched = time.time()
        return s


def refusal(client: str) -> Optional[str]:
    """Why this question cannot be asked now (rate limits), or None."""
    limit, window = RATE
    now = time.time()
    with _glock:
        q = _hits[client]
        while q and now - q[0] > window:
            q.popleft()
        while _day and now - _day[0] > 86400:
            _day.popleft()
        if len(_day) >= DAILY:
            return "Лимит вопросов к помощнику на сегодня исчерпан — попробуйте завтра."
        if len(q) >= limit:
            return "Слишком много вопросов подряд — подождите несколько минут."
        q.append(now)
        _day.append(now)
        return None


def ui_state(d: Data, st: Dict[str, Any]) -> str:
    """What is on the screen right now, compactly."""
    lines = []
    team = st.get("team")
    if team in d.team_league:
        club = d.leagues[d.team_league[team]]["clubs"][team]
        s = club["summary"]
        lines.append(f"Клуб: {team} ({d.ru.get(d.team_league[team])}, {s['place']}-е место, {s['pts']} очков, "
                     f"схема {club['formation']}).")
    lines.append(f"Вкладка: {TABS.get(st.get('tab'), st.get('tab') or 'Клуб')}. "
                 f"Вид поля: {VIEWS.get(st.get('view'), st.get('view') or 'Состав')}. "
                 f"Эталон цвета позиций: {'вся лига' if st.get('bench') == 'league' else 'топ-6 лиги'}.")
    if st.get("slot"):
        lines.append(f"Выбрана позиция {st['slot']} ({SLOT_RU.get(st['slot'], '')}); игрок на экране: "
                     f"{st.get('player') or '—'}; сравнение кандидатов — "
                     f"{'с этим игроком' if st.get('compare') == 'player' else 'с позицией в целом'}.")
    if st.get("candidate"):
        lines.append(f"Выбран кандидат: {st['candidate']}.")
    if st.get("lineup_changes"):
        lines.append("На поле подставлены: " + "; ".join(st["lineup_changes"]) + ".")
    if st.get("moved"):
        lines.append("Перетащены вручную: " + ", ".join(st["moved"]) + ".")
    f = st.get("filters") or {}
    if f:
        lines.append(f"Фильтры кандидатов: не старше {f.get('max_age')}, до €{f.get('max_price_m')} млн, лиги: "
                     f"{', '.join(f.get('leagues') or [])}, только лучше текущего: {'да' if f.get('only_better') else 'нет'}.")
    if st.get("weights"):
        lines.append("Веса TOPSIS на экране: " + ", ".join(f"{k} {v}" for k, v in st["weights"].items()) + ".")
    lines.append(f"Бюджет плана: €{st.get('budget', 120)} млн. «Что было дальше»: {'включено' if st.get('future') else 'выключено'}.")
    return "<ui_state>\n" + "\n".join(lines) + "\n</ui_state>"


# ---- the tools themselves -----------------------------------------------------------------

class Tools:
    def __init__(self, d: Data, s: Session, emit: Callable[[dict], None]):
        self.d, self.s, self.emit = d, s, emit

    def run(self, name: str, args: Dict[str, Any]) -> Any:
        return getattr(self, name)(**{k: v for k, v in args.items() if v is not None})

    def _screen(self) -> Dict[str, Any]:
        return self.s.state or {}

    def list_clubs(self, league: str = "") -> dict:
        d = self.d
        if not league:
            return {"leagues": [{"league": l["name"], "ru": l["ru"], "top6": l["top6"],
                                 "clubs": [f"{c['place']}. {c['team']} ({c['pts']} очк.)" for c in l["clubs"]]}
                                for l in d.index["leagues"]],
                    "candidates_only": "1. Bundesliga (только «Байер», его игроки — среди кандидатов)"}
        key = league.strip().lower()
        name = next((n for n in d.leagues if key in (n.lower(), d.ru[n].lower())), None)
        if name is None:
            return {"error": f"Лиги {league} нет; есть: {', '.join(d.leagues)}"}
        rows = []
        for t, c in sorted(d.leagues[name]["clubs"].items(), key=lambda kv: kv[1]["summary"]["place"]):
            s = c["summary"]
            rows.append({"place": s["place"], "team": t, "pts": s["pts"], "goals": f"{s['gf']}–{s['ga']}",
                         "xg": s["xg"], "xga": s["xga"], "xgd_rank": s["xgd_rank"], "formation": c["formation"],
                         "needs": [x["code"] for x in c["slots"] if x["need"]]})
        return {"league": name, "ru": d.ru[name], "clubs": rows}

    def get_club(self, team: str, include_future: bool = False) -> dict:
        d = self.d
        t, c = d.club(team)
        names = {int(k): v for k, v in c["names"].items()}
        slots = [{"code": x["code"], "position": SLOT_RU.get(x["code"], x["code"]), "group": x["group"],
                  "players_minutes": [[names.get(p, str(p)), int(m)] for p, m in x["players"][:3]],
                  "score_vs_top6": x["score_top6"], "score_vs_league": x["score_league"],
                  "need": x["need"], "reason": x["reason"] or None,
                  "need_metrics": {d.metrics[m]: w for m, w in x["weights"].items()}} for x in c["slots"]]
        managers = [{k: m[k] for k in ("name", "matches", "ppg", "gf", "ga", "xg", "xga", "from", "to")}
                    | ({"style": m["style"]} if m.get("style") else {}) for m in c["managers"]]
        fin = [s for s in c["finance"]["seasons"] if include_future or s["season"] <= d.index["decision_season"]]
        return {"team": t, "league": d.ru[d.team_league[t]], "summary": c["summary"],
                "formation": c["formation"], "formation_share": c["formation_share"], "positions": slots,
                "managers": managers, "scored": self._shots(c["scored"], ours=True),
                "conceded": self._shots(c["conceded"], ours=False),
                "squad_return": [{"season": s["label"], "squad_value_end": money(s["value"]), "players": s["squad"],
                                  "return_of_stayers": pct(s["ret"]), "league_median": pct(s["median"]),
                                  "rank": f"{s['rank']} из {s['of']}" if s["rank"] else None,
                                  "joined": [s["joined"], money(s["joined_value"])],
                                  "left": [s["left"], money(s["left_value"])],
                                  "rose_most": [[n, money(a), money(b)] for n, a, b in s["up"]],
                                  "fell_most": [[n, money(a), money(b)] for n, a, b in s["down"]],
                                  "after_decision": s["season"] > d.index["decision_season"]} for s in fin],
                "squad_return_note": "доходность — изменение рыночной стоимости оставшихся игроков за сезон; "
                                     "пришли/ушли — число игроков и их рыночная стоимость, не суммы сделок"}

    @staticmethod
    def _shots(side: dict, ours: bool) -> dict:
        zones = []
        for i, row in enumerate(side["zone_diff"]):
            for j, v in enumerate(row):
                if v is None:
                    continue
                # the opponents' left flank is our right one
                where = SIDES[j] if ours else "наш " + SIDES[len(SIDES) - 1 - j]
                zones.append((v, f"{X_BANDS[i]}, {where}"))
        zones.sort(reverse=True)
        goals = sum(s[3] for s in side["shots"])
        return {"xg_per_match": side["xg_pm"], "shots": len(side["shots"]), "goals_from_shots": goals,
                "set_piece_xg_share": side["set_piece_share"],
                "zones_above_league": [[z, round(v, 3)] for v, z in zones[:4] if v > 0],
                "zones_below_league": [[z, round(v, 3)] for v, z in zones[::-1][:3] if v < 0],
                "note": "xG за матч из зоны минус среднее одной команды лиги; фланги — "
                        + ("с точки зрения нашей атаки" if ours else "наши, у наших ворот")}

    def _find(self, name: str, team: str = "") -> List[Tuple[str, dict]]:
        d, q = self.d, norm(name)
        if not q:                        # Cyrillic or punctuation only: the data has Latin names
            return []
        teams = [d.team(team)] if team else list(d.team_league)
        scored = []
        for t in teams:
            for p in d.leagues[d.team_league[t]]["clubs"][t]["players"]:
                keys = [norm(p["name"]), norm(p["full_name"])]
                if q in keys:
                    s = 3
                elif all(any(tok == k or k.startswith(tok) for k in " ".join(keys).split()) for tok in q.split()):
                    s = 2
                elif max(difflib.SequenceMatcher(None, q, k).ratio() for k in keys) > 0.82:
                    s = 1
                else:
                    continue
                scored.append((s, p["minutes"], t, p))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        best = [x for x in scored if x[0] == scored[0][0]] if scored else []
        return [(t, p) for _, _, t, p in best]

    def get_player(self, name: str, team: str = "", include_future: bool = False) -> dict:
        d = self.d
        if not norm(name):
            return {"error": "Имя игрока нужно латиницей, как в данных (например, Paulo Dybala)."}
        hits = self._find(name, team)
        if not hits:
            pool = d.pool[d.pool["name"].map(norm).str.contains(norm(name), regex=False)]
            if len(pool):          # a Bundesliga candidate or a player only in the pool
                return {"pool_rows": [self._pool_row(p, include_future) for p in pool.head(5).itertuples()],
                        "note": "игрок есть только в пуле кандидатов (у его клуба нет полного сезона в данных)"}
            return {"error": f"Игрока «{name}» нет в данных 2015/16 этих лиг. Проверьте написание (латиницей)."}
        if len({p["id"] for _, p in hits}) > 1:
            return {"ambiguous": [{"name": p["full_name"], "team": t, "minutes": p["minutes"]} for t, p in hits[:8]],
                    "note": "уточните клуб параметром team"}
        out = []
        for t, p in hits[:2]:          # the same player at two clubs (moved in January)
            club = d.leagues[d.team_league[t]]["clubs"][t]
            slots = [[x["code"], int(m)] for x in club["slots"] for pid, m in x["players"] if pid == p["id"]]
            groups = {}
            for g, e in p["groups"].items():
                groups[d.index["groups"][g]] = {
                    "minutes": e["minutes"], "score_vs_top6": e.get("score_top6"), "score_vs_league": e.get("score_league"),
                    "score_vs_europe": e.get("score_europe"),
                    "metrics": [{"metric": d.metrics[m], "per90": e["per90"].get(m),
                                 "pct_top6": (e.get("top6") or {}).get(m), "pct_league": (e.get("league") or {}).get(m),
                                 "pct_europe": (e.get("europe") or {}).get(m)} for m in e["per90"]]}
            pr = d.pool[(d.pool["id"] == p["id"]) & (d.pool["team"] == t)]
            row = {"name": p["name"], "full_name": p["full_name"], "team": t, "league": d.ru[d.team_league[t]],
                   "country": p.get("country"), "age_summer_2016": p.get("age"), "minutes": p["minutes"],
                   "positions_in_scheme_minutes": slots, "roles": groups, "market_value": money(p.get("value")),
                   "value_date": p.get("value_date")}
            if len(pr):
                q = pr.iloc[0]
                row |= {"fair_value": money(q["fair"]), "fair_to_price": round(q["fair"] / q["value"], 2)
                        if q["value"] else None}
                if include_future:
                    row |= {"value_2017": money(q["v2017"]), "value_2018": money(q["v2018"])}
            else:
                row["fair_value"] = "нет: меньше 900 минут в роли или нет свежей оценки"
            out.append(row)
        return {"players": out, "percentile_note": "процентиль 70 = лучше 70 % игроков той же роли с ≥900 мин"}

    def _pool_row(self, p, future: bool) -> dict:
        d = self.d
        row = {"name": p.name, "team": p.team, "league": d.ru.get(p.league, p.league), "role": d.index["groups"][p.group],
               "age": p.age, "minutes_in_role": p.minutes, "market_value": money(p.value), "fair_value": money(p.fair),
               "fair_to_price": round(p.fair / p.value, 2) if p.value and p.fair else None,
               "role_score_vs_europe": p.score, "team_place": p.team_place,
               "percentiles_europe": {d.metrics[m]: v for m, v in p.pct.items()}}
        if future:
            row |= {"value_2017": money(p.v2017), "value_2018": money(p.v2018)}
        return row

    def _filters(self, max_age, max_price_m, leagues, only_better, weights):
        f = self._screen().get("filters") or {}
        return dict(max_age=max_age if max_age is not None else f.get("max_age", 29),
                    max_price=1e6 * (max_price_m if max_price_m is not None else f.get("max_price_m", 50)),
                    leagues=leagues or f.get("leagues") or None,
                    only_better=only_better if only_better is not None else f.get("only_better", True),
                    weights=weights or self._screen().get("weights") or None)

    def find_replacements(self, team: str, slot: str, compare: str = "", max_age: float = None,
                          max_price_m: float = None, leagues: List[str] = None, only_better: bool = None,
                          weights: Dict[str, float] = None, top: int = 8, include_future: bool = False) -> dict:
        d = self.d
        t, club = d.club(team)
        s = slot_by_code(club, slot)
        compare = compare or self._screen().get("compare") or "player"
        opts = self._filters(max_age, max_price_m, leagues, only_better, weights)
        c, funnel, inc, w = candidates(d, t, s, compare=compare, **opts)
        names = {int(k): v for k, v in club["names"].items()}
        main = names.get(s["players"][0][0]) if s["players"] else None
        return {"team": t, "slot": f"{s['code']} ({SLOT_RU.get(s['code'], '')})", "current_main_player": main,
                "compared_with": "основной игрок позиции" if compare == "player" else "позиция в целом",
                "position_score_vs_top6": s["score_top6"], "need": s["need"], "reason": s["reason"] or None,
                "need_weights": {d.metrics[m]: round(v, 3) for m, v in w.items()},
                "current_fit": None if inc is None else round(inc, 1),
                "filters": {"max_age": opts["max_age"], "max_price": money(opts["max_price"]),
                            "leagues": opts["leagues"] or "все пять", "only_better": opts["only_better"]},
                "topsis_weights": opts["weights"] or {k: v["weight"] for k, v in d.index["criteria"].items()},
                "funnel": funnel,
                "candidates": [candidate_row(d, p, w, include_future) for p in c.head(max(1, min(int(top), 15))).itertuples()],
                "notes": "fit — соответствие потребности (средний процентиль к топ-5 лигам с весами); fair_to_price > 1 — "
                         "стоит дешевле похожих; top3_share_random_weights — устойчивость к выбору весов"}

    def transfer_plan(self, team: str, budget_m: float = None, include_future: bool = False) -> dict:
        d = self.d
        t, club = d.club(team)
        budget = 1e6 * (budget_m if budget_m is not None else self._screen().get("budget", 120))
        needs = [s for s in club["slots"] if s["need"]]
        if not needs:
            return {"team": t, "plan": [], "note": "у клуба нет позиций-потребностей по правилу"}
        opts = self._filters(None, None, None, None, None)
        depth = 4 if len(needs) > 5 else 6
        ranked, ws = {}, {}
        for s in needs:
            c, _, _, w = candidates(d, t, s, compare="slot", **opts)
            ranked[s["code"]], ws[s["code"]] = c.head(depth), w
        picks = fd.budget_plan(ranked, budget, depth=depth)
        rows, spent, fair, later = [], 0.0, 0.0, 0.0
        for code, i in picks:
            p = next(ranked[code].loc[[i]].itertuples())       # a row as attributes (Series.name is the index)
            s = next(x for x in needs if x["code"] == code)
            rows.append({"slot": f"{code} ({SLOT_RU.get(code, '')})", "reason": s["reason"],
                         "current_fit": s["incumbent_fit"]} | candidate_row(d, p, ws[code], include_future))
            spent, fair, later = spent + p.value, fair + p.fair, later + (p.v2018 if pd.notna(p.v2018) else 0)
        out = {"team": t, "budget": money(budget), "spent": money(spent), "fair_value_sum": money(fair), "plan": rows,
               "not_filled": [s["code"] for s in needs if s["code"] not in {c for c, _ in picks}]}
        if include_future and spent:
            out |= {"value_2018_sum": money(later), "annual_return": pct((later / spent) ** 0.5 - 1)}
        return out

    def search_players(self, group: str = "", leagues: List[str] = None, max_age: float = None,
                       max_price_m: float = None, min_price_m: float = None, sort_by: str = "undervalued",
                       metric: str = "", top: int = 10, include_future: bool = False) -> dict:
        d = self.d
        p = d.pool[d.pool["fresh"] & d.pool["fair"].notna()]
        if group:
            p = p[p["group"] == group]
        if leagues:
            p = p[p["league"].isin(leagues)]
        if max_age is not None:
            p = p[p["age"] <= max_age]
        if max_price_m is not None:
            p = p[p["value"] <= max_price_m * 1e6]
        if min_price_m is not None:
            p = p[p["value"] >= min_price_m * 1e6]
        if sort_by == "metric":
            if metric not in d.metrics:
                return {"error": f"Показатель {metric} неизвестен. Ключи по ролям: {d.index['role_metrics']}"}
            p = p.assign(_k=[x.get(metric) if x.get(metric) is not None else -1 for x in p["pct"]])
            p = p[p["_k"] >= 0]
        elif sort_by == "growth_2018":
            include_future = True
            p = p.assign(_k=p["v2018"] / p["value"]).dropna(subset=["_k"])
        else:
            p = p.assign(_k={"undervalued": p["gap"], "role_score": p["score"], "value": p["value"],
                             "cheapest": -p["value"]}.get(sort_by, p["gap"]))
        p = p.sort_values("_k", ascending=False).drop_duplicates("id")
        return {"found": int(len(p)), "sort_by": sort_by,
                "players": [self._pool_row(x, include_future) for x in p.head(max(1, min(int(top), 25))).itertuples()]}

    def show_in_app(self, team: str = "", slot: str = "", tab: str = "", view: str = "", future: bool = None) -> dict:
        d = self.d
        ev: Dict[str, Any] = {"type": "show"}
        t = d.team(team) if team else self._screen().get("team")
        if team:
            ev |= {"team": t, "league": d.team_league[t]}
        if slot:
            if t not in d.team_league:
                return {"error": "сначала нужен клуб"}
            ev["slot"] = slot_by_code(d.leagues[d.team_league[t]]["clubs"][t], slot)["code"]
        if tab:
            ev["tab"] = tab
        if view:
            ev["view"] = view
        if future is not None:
            ev["future"] = future
        self.emit(ev)
        return {"shown": True, **{k: v for k, v in ev.items() if k != "type"}}


# ---- the conversation loop ------------------------------------------------------------------

_client = None
_system: Optional[str] = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(timeout=180.0, max_retries=2)
    return _client


def _label(name: str, args: Dict[str, Any]) -> str:
    label = TOOL_LABELS.get(name, name)
    try:
        return label.format(**{k: args.get(k, "") for k in ("team", "slot", "name")}).rstrip(": ,")
    except (KeyError, IndexError):
        return label


def chat(s: Session, state: Dict[str, Any], message: str) -> Iterator[dict]:
    """Yields events: chat, thinking, step, text, show, sources, done, error."""
    import anthropic
    global _system

    yield {"type": "chat", "chat_id": s.id}
    if not enabled():
        yield {"type": "error", "message": "ИИ-помощник не настроен: добавьте ANTHROPIC_API_KEY в файл .env проекта."}
        return
    if s.turns >= MAX_TURNS:
        yield {"type": "error", "message": "Диалог получился длинным — начните новый (кнопка «Новый диалог»)."}
        return
    d = DATA_.load()
    if _system is None:
        _system = system_prompt(d)
    s.turns += 1
    s.state = state or {}
    events: List[dict] = []
    tools = Tools(d, s, events.append)
    s.messages.append({"role": "user", "content": [{"type": "text", "text": ui_state(d, s.state)},
                                                   {"type": "text", "text": message}]})
    system = [{"type": "text", "text": _system, "cache_control": {"type": "ephemeral"}}]
    sources: Dict[str, str] = {}

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            # history is append-only; the top-level cache marker moves to the newest block by itself
            with client().beta.messages.stream(
                    model=MODEL, max_tokens=16000, system=system, messages=s.messages, tools=TOOLS + SERVER_TOOLS,
                    cache_control={"type": "ephemeral"},
                    thinking={"type": "adaptive", "display": "summarized"}, output_config={"effort": EFFORT},
                    betas=[FALLBACK_BETA], fallbacks="default") as stream:
                for ev in stream:
                    if ev.type == "content_block_start":
                        b = ev.content_block
                        if b.type in ("tool_use", "server_tool_use"):
                            yield {"type": "step", "id": b.id, "name": b.name, "status": "start",
                                   "label": TOOL_LABELS.get(b.name, b.name).split(" {")[0].rstrip(":")}
                        elif b.type.endswith("_tool_result") and getattr(b, "tool_use_id", None):
                            yield {"type": "step", "id": b.tool_use_id, "status": "done"}
                    elif ev.type == "content_block_delta":
                        if ev.delta.type == "text_delta":
                            yield {"type": "text", "text": ev.delta.text}
                        elif ev.delta.type == "thinking_delta" and ev.delta.thinking:
                            yield {"type": "thinking", "text": ev.delta.thinking}
                final = stream.get_final_message()
        except ValueError:
            # tool input JSON the SDK could not parse at all - nothing to answer; ask the model to retry
            continue
        except anthropic.RateLimitError:
            yield {"type": "error", "message": "Слишком много запросов к модели — попробуйте через минуту."}
            return
        except anthropic.APIStatusError as e:
            log.warning("LLM error %s: %s", e.status_code, e)
            yield {"type": "error", "message": f"Ошибка модели (HTTP {e.status_code}). Попробуйте ещё раз."}
            return
        except anthropic.APIConnectionError:
            yield {"type": "error", "message": "Нет связи с API Anthropic. Проверьте интернет."}
            return

        s.messages.append({"role": "assistant", "content": final.content})
        for b in final.content:
            # search with dynamic filtering runs inside code execution and leaves no citations in the text,
            # so the pages come from the search results themselves
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                for res in b.content:
                    if getattr(res, "url", None):
                        sources.setdefault(res.url, res.title or res.url)
            elif b.type == "server_tool_use":
                yield {"type": "step", "id": b.id, "status": "done"}
        if final.stop_reason == "refusal":
            yield {"type": "text", "text": "\n\nНа этот запрос я ответить не могу."}
            break
        if final.stop_reason == "pause_turn":       # the server-side search loop paused: send it back to go on
            continue
        uses = [b for b in final.content if b.type == "tool_use"]
        if final.stop_reason == "max_tokens" and uses:
            s.messages.pop()                    # a truncated tool call must not be run or kept
            yield {"type": "error", "message": "Ответ оборвался — переформулируйте вопрос короче."}
            return
        if not uses:
            break
        results = []
        for b in uses:
            args = b.input if isinstance(b.input, dict) else {}
            problem = _validate(b.name, b.input)
            if problem:
                out, err = {"error": problem}, True
            else:
                try:
                    out, err = tools.run(b.name, args), False
                except LookupError as e:
                    out, err = {"error": str(e).strip("'\"")}, True
                except Exception as e:                    # a tool bug must not end the conversation
                    log.exception("tool %s failed", b.name)
                    out, err = {"error": f"{type(e).__name__}: {e}"}, True
            for e in events:
                yield e
            events.clear()
            yield {"type": "step", "id": b.id, "name": b.name, "label": _label(b.name, args),
                   "status": "error" if err else "done"}
            results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": err,
                            "content": json.dumps(out, ensure_ascii=False, default=str)})
        s.messages.append({"role": "user", "content": results})
    if sources:
        yield {"type": "sources", "items": [{"url": u, "title": t} for u, t in list(sources.items())[:6]]}
    yield {"type": "done"}
