"use strict";
// Guided tour ("Гид"): the Chelsea summer-2016 story told through the page. Each step sets up the screen it talks about,
// dims everything except the parts to look at (they stay clickable) and may give the visitor a small task, with
// a "do it for me" fallback. The numbers in the texts come from the same data and functions as the page.

const TOUR = { on: false, i: 0, tok: 0, ok: false, steps: [], key: "", timer: 0, frame: 0, from: null, at: null, budget0: null, okText: "", cover: 0 };

const tq = (sel) => $(`#panel ${sel}`);
const val = (v) => (typeof v === "function" ? v() : v);
const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
};

function tourScene(view = "lineup", tab = "club") {
  // a clean screen: nothing moved, no candidate, the future hidden
  openAI(false); hideTip();
  S.fixed = {}; S.whatIf = {}; S.lastMoved = null; S.slot = null; S.player = null; S.cand = null;
  S.view = view; S.bench = "top6"; S.future = false;
  renderPitch(); setTab(tab);
}

function paceRank(ppg) {                     // where a whole season at this pace would have finished
  const pts = ppg * S.club.summary.matches;
  return 1 + Object.values(S.leagues[S.league].clubs).filter((c) => c !== S.club && c.summary.pts > pts).length;
}

function tourSteps() {
  const c = S.club, s = c.summary, rules = S.index.rules;
  const at = (code) => c.slots.findIndex((x) => x.code === code);
  const ST = at("ST"), GK = at("GK"), LB = at("LB");
  const first = (i) => nameOf(c.slots[i].players[0][0]);
  const costa = surname(first(ST));
  const mou = c.managers[0], hid = c.managers.find((m) => /Hiddink/.test(m.name)) ?? c.managers[c.managers.length - 1];
  const hidNet = c.managers.filter((m) => m.nodes).indexOf(hid);
  const replaceST = () => { if (S.tab !== "replace" || S.slot !== ST) { S.compare = "player"; selectSlot(ST, "replace"); } };
  const res = () => candidates(c.slots[ST], S.players.get(c.slots[ST].players[0][0]));
  const lei = S.leagues["Premier League"]?.clubs["Leicester City"];
  const nClubs = S.index.leagues.reduce((a, l) => a + l.clubs.length, 0);

  return [
    { ch: "Завязка", title: "Лето 2016. Вы — спортивный директор «Челси»",
      before: () => tourScene(),
      body: () => `<p>Год назад «Челси» стал чемпионом Англии. Сезон 2015/16 команда закончила ${s.place}-й, а тренера уволили ещё в декабре. Скоро откроется трансферное окно, и владелец ждёт от вас план: кого купить и за сколько.</p>
        <p>Гид покажет, где на этой странице искать ответы, а кое-где попросит нажать самим. ${TOUR.steps.length} ${plural(TOUR.steps.length, "шаг", "шага", "шагов")}, около трёх минут. Листайте кнопками или стрелками ← →, выйти — Esc.</p>
        ${TOUR.from ? `<p class="muted">Тур идёт на примере «Челси», к «${esc(TOUR.from[1])}» вернётесь в конце.</p>` : ""}` },

    { ch: "Диагноз", title: "Таблица против xG",
      before: () => tourScene(), el: () => [[tq(".kpis"), tq(".callout")]],
      body: () => `<p>${s.place}-е место и ${s.pts} очков у вчерашнего чемпиона. Но таблица — не вся правда.</p>
        <p><b>xG</b>, «ожидаемые голы», оценивает каждый удар: как часто из такого положения забивают. Сумма за сезон показывает, сколько моментов команда создала (xG) и сколько отдала соперникам (xGA).</p>
        <p>По разнице xG «Челси» ${s.xgd_rank}-й — играл лучше своего места. Часть провала — исполнение и невезение, а не только состав.</p>` },

    { ch: "Диагноз", title: "Один состав — два тренера",
      before: () => tourScene(), el: () => tq(".scroll-x"),
      body: () => {
        const r1 = paceRank(mou.ppg), r2 = paceRank(hid.ppg), extra = mou.ga - mou.xga, n = Math.round(extra);
        return `<p>При Моуринью — ${fmt(mou.ppg, 2)} очка за матч: в таком темпе «Челси» закончил бы сезон ${r1}-м${r1 >= 18 ? ", в зоне вылета" : ""}.
          В колонке «Пропуски» ${signed(extra)}: соперники забили на ${n} ${plural(n, "гол", "гола", "голов")} больше, чем «стоили» их удары. Так выглядят ошибки вратаря и защиты — или невезение.</p>
          <p>Хиддинк с теми же игроками набирал ${fmt(hid.ppg, 2)} — темп ${r2}-го места. Состав был не так плох, как казалось в декабре.</p>`;
      } },

    { ch: "Поле", title: "Сила каждой позиции",
      before: () => tourScene(), el: () => [[$("#pitch-tools"), $(".pitch-wrap"), $("#pitch-legend")]],
      body: () => `<p>Кружки — средние позиции игроков в схеме ${fmtFormation(c.formation)}, атака вверх. Число — насколько сильны игроки позиции на фоне той же роли в клубах топ-6 лиги: 50 — медиана, синий — сильнее, красный — слабее. У каждой роли свои показатели: у вратаря — спасённые голы, у нападающего — xG и удары.</p>
        <p>Обводка — <b>потребность</b>: позиция слабая или основному игроку ${rules.old}+ лет. Самое слабое место — вратарь: <b>${fmt(c.slots[GK].score_top6)}</b> из 100. Наведите на кружок, чтобы увидеть, кто там играл.</p>`,
      task: { text: "переключите над полем «Цвет — сила позиции к» на «всей лиге».",
        done: () => S.bench === "league", auto: () => { S.bench = "league"; renderPitch(); },
        ok: () => `к средней команде лиги вратарь уже ${fmt(c.slots[GK].score_league)}. Планка зависит от амбиций: для середняка позиция в порядке, для претендента на титул — нет.` } },

    { ch: "Поле", title: "Передвиньте игрока",
      before: () => tourScene(), el: () => [[$("#pitch-tools"), $(".pitch-wrap"), $("#pitch-note")]],
      body: () => { const m = shapeModel();
        return `<p>Кружки можно перетаскивать мышью или пальцем. Остальные сдвинутся так, как в среднем стояли команды со схемой ${fmtFormation(c.formation)}, когда игрок этой позиции стоял там же${m ? ` — модель выучена на ${fmt(m.parts)} отрезках реальных матчей ${m.teams} команд` : ""}.</p>
          <p>Это связь из данных, а не симулятор тактики, но смещения получаются правдоподобными.</p>`; },
      task: { text: () => `утащите левого защитника (${esc(surname(first(LB)))}) к штрафной соперника.`,
        done: () => Object.keys(S.fixed).length > 0,
        auto: () => { const b = S.base[LB]; S.fixed[LB] = [Math.min(110, b[0] + 32), b[1] + 4]; S.lastMoved = LB; renderPitch(); },
        ok: () => "под полем написано, кто и на сколько метров сдвинулся, пунктир показывает откуда. Вернуть всё можно кнопкой «Сбросить расстановку» над полем." } },

    { ch: "Поле", title: "Сеть передач: Моуринью или Хиддинк",
      before: () => { S.manager = 0; tourScene("network"); },
      el: () => [[$("#views"), $(".pitch-wrap"), $("#pitch-note")]],
      body: () => `<p>Кружок — позиция, линия — точные передачи между позициями: чем толще, тем чаще. Под полем — стиль игры. <b>PPDA</b> — сколько передач соперник успевает сделать до нашего отбора: чем меньше, тем выше прессинг.</p>
        <p>При Моуринью PPDA ${fmt(mou.style.ppda, 1)}: на соперника давили сильнее, чем при Хиддинке (${fmt(hid.style.ppda, 1)}), а очков набирали меньше. Прессинг сам по себе побед не приносит.</p>`,
      task: hidNet < 0 ? null : { text: "переключите на Хиддинка — кнопка «Hiddink» над полем.",
        done: () => S.manager === hidNet, auto: () => { S.manager = hidNet; renderPitch(); },
        ok: () => `сравните с Моуринью: у кого кружки стали крупнее (больше касаний) и как сдвинулись линии. Владение — ${fmt(mou.style.possession * 100)}% против ${fmt(hid.style.possession * 100)}%.` } },

    { ch: "Поле", title: "Откуда нам забивают",
      before: () => { S.shotMode = "zones"; tourScene("conceded"); },
      el: () => [[$("#views"), $(".pitch-wrap"), $("#pitch-legend")]],
      body: () => `<p>Теперь ворота «Челси» внизу. Клетки — зоны по разметке штрафной. Число — сколько xG за матч соперники набирали оттуда сверх среднего по лиге: красное — пропускаем больше обычного, синее — меньше.</p>
        <p>${fmt(c.conceded.set_piece_share * 100)}% опасности у ворот «Челси» пришлось на угловые и штрафные. Соседняя кнопка «Где забиваем» показывает то же для наших ударов.</p>`,
      task: { text: "нажмите «Удары» над полем.",
        done: () => S.shotMode === "shots", auto: () => { S.shotMode = "shots"; renderPitch(); },
        ok: () => { const n = c.conceded.shots.length, g = c.conceded.shots.filter((x) => x[3]).length;
          return `${n} ${plural(n, "удар", "удара", "ударов")} соперников за сезон, ${g} из них — голы (закрашены). Размер кружка — xG: крупные кружки у самых ворот спасти почти невозможно.`; } } },

    { ch: "Трансфер", title: "Слабое место в атаке",
      before: () => tourScene(), el: () => $(`#pitch .node[data-i="${ST}"]`), pad: 10,
      body: () => `<p>У нападающего (ST) оценка <b>${fmt(c.slots[ST].score_top6)}</b> — ниже медианы топ-6. Почти весь сезон там играл ${esc(first(ST))}. С него и начнём поиски.</p>`,
      task: { text: "нажмите на кружок ST — откроется карточка игрока.",
        done: () => S.slot === ST, auto: () => selectSlot(ST), ok: () => "карточка открылась справа." } },

    { ch: "Трансфер", title: "Карточка игрока",
      before: () => { tourScene(); S.pbench = "top6"; selectSlot(ST, "player"); },
      el: () => [[tq(".card"), tq(".bars")]],
      body: () => {
        const p = S.players.get(S.player), g = c.slots[ST].group, pc = p?.groups[g]?.top6 ?? {};
        const ms = S.index.role_metrics[g].filter((m) => pc[m] != null).sort((a, b) => pc[a] - pc[b]);
        const fair = playerFair(p?.id, S.team)?.fair, best = Math.max(...ms.map((m) => pc[m]));
        return `<p>Вверху — минуты, рыночная цена${fair ? ` (${money(p.value)})` : ""} и «справедливая» по модели${fair ? ` (${money(fair)})` : ""}: сколько рынок обычно платит за похожих по возрасту, роли и результативности.</p>
          <p>Полоски — <b>процентили</b> к нападающим топ-6: 50 — медиана, 80 — лучше 80% игроков той же роли. ${best < 50 ? `У ${esc(costa)} ни одного показателя выше медианы` : `Лучший показатель ${esc(costa)} — ${esc(label(ms[ms.length - 1]))}`}; слабее всего — ${ms.slice(0, 2).map((m) => `${esc(label(m))} (${fmt(pc[m])})`).join(" и ")}.</p>
          <p class="muted">Ниже — карта касаний и все его удары за сезон.</p>`;
      } },

    { ch: "Трансфер", title: "Кого ищем",
      before: () => { tourScene(); S.compare = "player"; selectSlot(ST, "replace"); },
      el: () => [[tq(".chips"), tq(".funnel")]],
      body: () => { const r = res();
        return `<p>Требования к новичку собраны из слабостей ${esc(costa)}: показатели, где он ниже медианы, весят больше — проценты на чипах.</p>
          <p>Воронка отсеивает ${r.funnel[0][1]} нападающих топ-5 лиг до ${r.list.length}: не из «Челси», не старше ${S.filters.maxAge} лет, до €${S.filters.maxPrice} млн и лучше ${esc(costa)} по этим требованиям. Ползунки и галочки меняют условия, список пересчитывается сразу.</p>`; } },

    { ch: "Трансфер", title: "Рейтинг: TOPSIS и устойчивость",
      before: () => { S.fixed = {}; S.whatIf = {}; S.lastMoved = null; renderPitch(); replaceST(); S.cand = null; renderPanel(); },
      el: () => tq("table"),
      body: () => `<p>Кандидатов сортирует <b>TOPSIS</b> — метод из Assignment 4. Побеждает тот, кто ближе всех к идеалу: высокое соответствие, большая недооценённость, молодость и много игрового времени.</p>
        <p>«Устойч.» — в скольких из 400 случайных наборов весов игрок остаётся в тройке. Высокая — лидер не держится на одной удачной настройке. Сейчас наверху: ${res().list.slice(0, 3).map((x) => `<b>${esc(x.name)}</b>`).join(", ")}.</p>`,
      task: { text: "нажмите на строку любого кандидата.",
        done: () => S.cand != null, auto: () => tq("tr[data-k]")?.click(),
        ok: () => `под таблицей появилось сравнение: серая точка — ${esc(costa)}, синяя — ${esc(surname(S.cand?.name ?? "кандидат"))}.` } },

    { ch: "Трансфер", title: "Примерьте в составе",
      before: () => {
        S.fixed = {}; S.whatIf = {}; S.lastMoved = null; S.view = "lineup";
        replaceST(); if (!S.cand) S.cand = res().list[0];
        renderPitch(); renderPanel();
      },
      el: () => [tq("#cand-detail .card"), $(".pitch-wrap")],
      body: () => `<p>Кнопка «Поставить в состав» выводит ${esc(S.cand?.name ?? "кандидата")} на поле вместо ${esc(costa)} — с поправкой на манеру: насколько выше и шире типичного нападающего он играл в своём клубе. Партнёры подстроятся по той же модели формы.</p>`,
      task: { text: "нажмите «Поставить в состав».",
        done: () => S.whatIf[ST] != null, auto: () => $("#in")?.click(),
        ok: () => `на поле пунктирный кружок. Число в нём — соответствие требованиям: ${fmt(S.whatIf[ST]?.fit)} против ${fmt(res().inc)} у ${esc(costa)}.` } },

    { ch: "Деньги", title: "Кто стоит дешевле, чем должен",
      before: () => tourScene("lineup", "value"), el: () => $("#vscatter")?.closest(".card"),
      body: () => {
        const u = S.pool.filter((p) => p.fair && p.value && p.fresh && p.age <= 29 && p.team !== S.team).sort((a, b) => b.gap - a.gap)[0];
        return `<p>Точка — игрок топ-5 лиг с 900+ минутами. По горизонтали — «справедливая» стоимость: модель учится, сколько рынок платит за похожих, и оценивает каждого, кого не видела при обучении. По вертикали — настоящая цена летом 2016.</p>
          <p>Ниже пунктира — рынок ценит игрока дешевле похожих, синие точки — «Челси». Наведите на точку, чтобы узнать, кто это.${u ? ` Самый большой разрыв у ${esc(u.name)} (${esc(u.team)}): ${money(u.value)} при справедливой ${money(u.fair)}.` : ""}</p>`;
      } },

    { ch: "Деньги", title: "Доходность состава",
      before: () => tourScene("lineup", "finance"), el: () => [[tq(".kpis"), $("#fchart")?.closest(".card")]],
      body: () => {
        const f = (c.finance?.seasons ?? []).find((x) => x.season === S.index.decision_season);
        return `<p>Представьте игроков портфелем акций. ${f && f.ret != null ? `За ${f.label} оставшиеся в «Челси» изменились в цене на <b>${pct(f.ret)}</b>, а медиана клубов лиги — на ${pct(f.median)}: ${f.rank}-е место из ${f.of}.${f.ret < f.median ? " Рынок разочаровался в составе чемпиона." : ""}` : ""}</p>
          <p>Это не выручка и не прибыль клуба — их нет в открытых данных. Считаются рыночные стоимости Transfermarkt; нажмите на столбик, чтобы увидеть, кто подорожал и кто подешевел.</p>`;
      } },

    { ch: "Деньги", title: "План на всё окно",
      before: () => { tourScene("lineup", "plan"); TOUR.budget0 = S.budget; }, el: () => [[tq(".controls"), tq("table")]],
      body: () => `<p>У «Челси» ${c.slots.filter((x) => x.need).length} позиций-потребностей. Алгоритм перебирает сочетания лучших кандидатов на каждую и берёт то, где сумма оценок TOPSIS максимальна, а общая цена укладывается в бюджет.</p>
        <p>Бюджет €${S.budget} млн → ${S.plan.best.length} ${plural(S.plan.best.length, "новичок", "новичка", "новичков")} за ${money(S.plan.spent)}.</p>`,
      task: { text: "сдвиньте ползунок бюджета.",
        done: () => S.plan.budget !== TOUR.budget0, auto: () => { S.budget = S.budget > 70 ? 60 : 200; renderPanel(); },
        ok: () => `план пересобран: €${S.plan.budget} млн → ${S.plan.best.length} ${plural(S.plan.best.length, "игрок", "игрока", "игроков")} за ${money(S.plan.spent)}. Кнопка «Показать состав на поле» расставит новичков.` } },

    { ch: "Машина времени", title: "Что было дальше",
      before: () => {
        tourScene("lineup", "plan");
        S.plan.best.forEach(([slot, cand]) => putIn(slot, cand));
        S.future = true; renderPitch(); renderPanel();
      },
      el: () => [tq("table"), $(".pitch-wrap")],
      body: () => `<p>До сих пор страница знала только то, что было известно летом 2016. Галочка «Что было дальше» под таблицей открывает колонку «2018» — рейтинг этих чисел не видит. На поле — состав из плана.</p>
        <p>План за ${money(S.plan.spent)} через два года стоил бы ${money(S.plan.later18)}. Весь шорт-лист (по 5 кандидатов на позицию, зафиксирован до проверки) подорожал в медиане в 2,1 раза, все игроки до 29 лет — в 1,1. Ван Дейк стоил €12 млн, а в январе 2018 «Ливерпуль» заплатил за него €85 млн.</p>` },

    { ch: "Машина времени", title: "А что сделал настоящий «Челси»?",
      before: () => openAI(false),
      body: () => `<p>Среди покупок лета 2016 — Батшуаи (€39 млн, в нашем рейтинге нападающих 38-й), Маркос Алонсо (€23 млн, 12-й среди левых защитников) и Н’Голо Канте из «Лестера» (€35,8 млн). Морату из нашего шорт-листа «Челси» купит годом позже — за €66 млн, хотя летом 2016 он стоил €30 млн.</p>
        <p>Канте в наших списках нет вовсе: центр поля не был потребностью. А сезон 2016/17 «Челси» выиграл: Антонио Конте перешёл на схему с тремя центральными защитниками, а Канте признали лучшим игроком сезона в Англии.</p>
        <p><b>Урок:</b> модель хорошо находит недооценённых на слабые позиции, но не видит, как новый тренер перестроит всю команду. Это помощник скаута, а не замена ему.</p>` },

    { ch: "Финал", title: "ИИ-помощник",
      before: () => { tourScene(); if (AI.status?.enabled) openAI(true); },
      el: () => (AI.status?.enabled ? $("#ai") : $("#ai-fab")),
      body: () => AI.status?.enabled
        ? `<p>Если что-то непонятно — спросите Claude. Он видит, что открыто на экране, считает теми же инструментами, что и страница (числа не выдумывает), и может сам открыть нужную вкладку или игрока. Факты вне данных ищет в интернете.</p>
           <p>Нажмите на подсказку или спросите своё, например: «Почему Куртуа так плохо сыграл?»</p>`
        : `<p>Кнопка «Спросить ИИ» открывает помощника: Claude отвечает на вопросы по данным страницы и сам открывает нужные вкладки.</p>
           <p>Здесь он не подключён: ключ API нельзя держать в браузере, нужен сервер. Локально — <code>python -m app.server</code>.</p>` },

    { ch: "Финал", title: "Дальше — сами",
      before: () => tourScene(), el: () => $(".pickers"),
      body: () => `<p>Выберите любой из ${nClubs} клубов ${S.index.leagues.length} лиг — всё пересчитается под него. Вкладка «Как это работает» объясняет каждую формулу, а кнопка «Гид» запустит тур заново.</p>
        ${lei ? `<p>Совет: откройте «Лестер» — чемпиона 2015/16, которому букмекеры перед сезоном давали шансы 5000 к 1. Мячом он владел всего ${fmt(lei.summary.possession * 100)}% времени. Как он выигрывал — видно на «Сети передач».</p>` : ""}
        <div class="row">${lei ? `<button class="btn" type="button" data-go="lei">Открыть «Лестер»</button>` : ""}${TOUR.from ? `<button class="btn secondary" type="button" data-go="back">Вернуться к «${esc(TOUR.from[1])}»</button>` : ""}</div>` },
  ];
}

// ---------------------------------------------------------------- engine
async function startTour() {
  if (!S.club || TOUR.on) return;
  const pl = S.index.leagues.find((l) => l.name === "Premier League");
  if (!pl?.clubs.some((x) => x.team === "Chelsea")) return;
  store.set("fi-tour", "seen"); $("#tour-btn").classList.remove("pulse");
  TOUR.from = S.team !== "Chelsea" ? [S.league, S.team] : null;
  if (TOUR.from && !await selectClub("Premier League", "Chelsea")) return;
  resetChoices(); S.shotMode = "zones"; S.manager = 0; S.pbench = "top6";
  TOUR.steps = tourSteps(); TOUR.on = true; TOUR.key = ""; TOUR.at = null;
  $("#tour").hidden = false;
  TOUR.timer = setInterval(() => { tourLayout(); tourCheck(); }, 150);
  addEventListener("resize", tourRelayout); addEventListener("scroll", tourRelayout, true);
  document.addEventListener("keydown", tourKey);
  tourGo(0);
}

function endTour() {
  if (!TOUR.on) return;
  TOUR.on = false; TOUR.tok++;
  clearInterval(TOUR.timer); cancelAnimationFrame(TOUR.frame);
  removeEventListener("resize", tourRelayout); removeEventListener("scroll", tourRelayout, true);
  document.removeEventListener("keydown", tourKey);
  $("#tour").hidden = true;
}

const tourNext = () => (TOUR.i < TOUR.steps.length - 1 ? tourGo(TOUR.i + 1) : endTour());
const tourBack = () => { if (TOUR.i > 0) tourGo(TOUR.i - 1); };
const tourRelayout = () => { cancelAnimationFrame(TOUR.frame); TOUR.frame = requestAnimationFrame(() => tourLayout()); };

function tourKey(e) {
  if (e.target.closest?.("input, textarea, select")) return;
  if (e.key === "Escape") endTour();
  else if (e.key === "ArrowRight") { e.preventDefault(); tourNext(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); tourBack(); }
}

async function tourGo(i) {
  const tok = ++TOUR.tok, st = TOUR.steps[i];
  TOUR.i = i; TOUR.ok = false;
  await st.before?.();
  if (tok !== TOUR.tok || !TOUR.on) return;
  const n = TOUR.steps.length;
  $("#tour-chapter").textContent = st.ch;
  $("#tour-count").textContent = `${i + 1} / ${n}`;
  $("#tour-bar").style.width = `${(i + 1) / n * 100}%`;
  $("#tour-title").textContent = st.title;
  $("#tour-body").innerHTML = st.body();
  $$("#tour-body [data-go]").forEach((b) => b.onclick = async () => {
    const to = b.dataset.go === "lei" ? ["Premier League", "Leicester City"] : TOUR.from;
    endTour();
    if (await selectClub(...to) && b.dataset.go === "lei") { S.view = "network"; renderPitch(); }
  });
  $("#tour-back").disabled = i === 0;
  $("#tour-next").textContent = i === n - 1 ? "Завершить" : i === 0 ? "Начать →" : "Дальше →";
  tourTask();
  const g = tourGroups(st)[0];
  if (g) {
    const r = tourRect(g, 0);
    if (r.y < 8 || r.y + r.h > innerHeight - 8) g[0].scrollIntoView({ block: r.h > innerHeight * 0.7 ? "start" : "center" });
  }
  TOUR.at = null;
  tourLayout(true);
  if (g && TOUR.cover > 0) {                         // no free place for the card: bring the target up and look again
    scrollBy(0, tourRect(g, 0).y - 12);
    TOUR.at = null;
    tourLayout(true);
  }
  $("#tour-next").focus({ preventScroll: true });
}

function tourTask() {
  const t = TOUR.steps[TOUR.i].task, box = $("#tour-task");
  box.hidden = !t;
  if (!t) return;
  box.className = "tour-task" + (TOUR.ok ? " ok" : "");
  if (TOUR.ok) { TOUR.okText = t.ok(); box.innerHTML = `<b>Получилось:</b> ${TOUR.okText}`; return; }
  box.innerHTML = `<b>Ваш ход:</b> ${val(t.text)} <button type="button" class="link" id="tour-auto">Сделайте за меня</button>`;
  $("#tour-auto").onclick = () => { t.auto(); tourCheck(); };
}

function tourCheck() {
  // once done, a task stays done; its text follows the page (another budget, another candidate)
  const t = TOUR.on && TOUR.steps[TOUR.i].task;
  if (!t) return;
  if (!TOUR.ok) { if (t.done()) { TOUR.ok = true; tourTask(); tourLayout(true); } }
  else if (t.ok() !== TOUR.okText) tourTask();
}

function tourGroups(st) {
  // el() gives an element, a list of elements (one hole each) or lists of elements (one hole around each list)
  const raw = st.el ? st.el() : null;
  return (Array.isArray(raw) ? raw : [raw]).map((g) => (Array.isArray(g) ? g : [g]).filter((e) => e && e.getClientRects().length))
    .filter((g) => g.length);
}

function tourRect(els, pad) {
  const rs = els.map((e) => e.getBoundingClientRect());
  const x0 = Math.min(...rs.map((r) => r.left)) - pad, y0 = Math.min(...rs.map((r) => r.top)) - pad;
  const x1 = Math.max(...rs.map((r) => r.right)) + pad, y1 = Math.max(...rs.map((r) => r.bottom)) + pad;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function tourLayout(force = false) {
  if (!TOUR.on) return;
  const st = TOUR.steps[TOUR.i], vw = innerWidth, vh = innerHeight;
  // holes clipped to the screen; holes that touch merge, so the dim never covers what it should show
  let holes = tourGroups(st).map((g) => tourRect(g, st.pad ?? 6)).map((r) => {
    const x0 = Math.max(r.x, -4), y0 = Math.max(r.y, -4), x1 = Math.min(r.x + r.w, vw + 4), y1 = Math.min(r.y + r.h, vh + 4);
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }).filter((r) => r.w > 4 && r.h > 4);
  for (let k = 0; k < holes.length; k++) for (let j = k + 1; j < holes.length; j++) {
    const a = holes[k], b = holes[j];
    if (a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h) {
      const x0 = Math.min(a.x, b.x), y0 = Math.min(a.y, b.y);
      holes[k] = { x: x0, y: y0, w: Math.max(a.x + a.w, b.x + b.w) - x0, h: Math.max(a.y + a.h, b.y + b.h) - y0 };
      holes.splice(j, 1); j = k;
    }
  }
  const key = holes.map((h) => [h.x, h.y, h.w, h.h].map(Math.round).join(",")).join(";") + `|${vw}x${vh}|${$("#tour-card").offsetHeight}`;
  if (!force && key === TOUR.key) return;
  TOUR.key = key;
  const rr = ({ x, y, w, h }) => { const r = Math.min(10, w / 2, h / 2);
    return `M${x + r},${y}H${x + w - r}A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h - r}A${r},${r} 0 0 1 ${x + w - r},${y + h}H${x + r}A${r},${r} 0 0 1 ${x},${y + h - r}V${y + r}A${r},${r} 0 0 1 ${x + r},${y}Z`; };
  $("#tour-dim path").setAttribute("d", `M-10,-10H${vw + 10}V${vh + 10}H-10Z` + holes.map(rr).join(""));
  $("#tour-rings").innerHTML = holes.map((h) => `<rect x="${h.x}" y="${h.y}" width="${h.w}" height="${h.h}" rx="${Math.min(10, h.w / 2, h.h / 2)}"/>`).join("");
  tourPlace(holes);
}

function tourPlace(holes) {
  // the card goes beside the first hole, else into a corner, wherever it covers the least of the holes;
  // the first hole is what the step is about, so covering the others costs less
  const card = $("#tour-card"), vw = innerWidth, vh = innerHeight, m = 10, gap = 14;
  const w = card.offsetWidth, h = card.offsetHeight, r = holes[0];
  let spots;
  if (!r) spots = [[(vw - w) / 2, (vh - h) / 2]];
  else if (vw < 640) spots = [[m, vh - h - m], [m, m]];
  else spots = [[r.x + r.w + gap, r.y], [r.x - gap - w, r.y], [r.x, r.y + r.h + gap], [r.x, r.y - gap - h],
    [vw - w - m, vh - h - m], [m, vh - h - m], [vw - w - m, m], [m, m]];
  if (TOUR.at) spots.unshift(TOUR.at);                 // keep the card still while it does not get in the way
  const cover = (x, y) => holes.reduce((a, b, k) => a + (k ? 0.2 : 1)
    * Math.max(0, Math.min(x + w, b.x + b.w) - Math.max(x, b.x)) * Math.max(0, Math.min(y + h, b.y + b.h) - Math.max(y, b.y)), 0);
  let best = null;
  for (const [x0, y0] of spots) {
    const x = clamp(x0, m, Math.max(m, vw - w - m)), y = clamp(y0, m, Math.max(m, vh - h - m)), c = cover(x, y);
    if (!best || c < best.c - 1) best = { x, y, c };
  }
  TOUR.at = [best.x, best.y]; TOUR.cover = best.c;
  card.style.left = `${best.x}px`; card.style.top = `${best.y}px`;
}

$("#tour-btn").onclick = startTour;
$("#tour-x").onclick = endTour;
$("#tour-next").onclick = tourNext;
$("#tour-back").onclick = tourBack;
$("#tour-dim path").addEventListener("pointerdown", () => {     // a click on the dim: point at the card
  const card = $("#tour-card");
  card.classList.remove("nudge"); void card.offsetWidth; card.classList.add("nudge");
});
if (!store.get("fi-tour")) $("#tour-btn").classList.add("pulse");
