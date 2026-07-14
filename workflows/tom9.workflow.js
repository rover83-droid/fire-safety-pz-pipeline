export const meta = {
  name: 'mpb-tom9',
  description: 'Том 9 ПЗ МПБ: заморозка паспорта → fan-out разделов → механический гейт → сводный том',
  phases: [
    { title: 'Исходные данные' }, // Фаза 1 — сходится (барьер)
    { title: 'Разделы' },         // Фаза 2 — fan-out (агенты, суждение)
    { title: 'Гейт' },            // Фаза 3 — код, НЕ агент
    { title: 'Сводка' },          // Фаза 4 — маршрутизация правок + сборка
  ],
}

// ── Параметры ─────────────────────────────────────────────────────────────
const PROJECT = (args && args.project) || './projects/bmk'
const CLI = 'python -m mpb_pz_flow.cli'

// Норм-несущие текстовые разделы тома 9 (ПП РФ №87) — на них идёт fan-out.
// Деривативные разделы («Общие положения», «Характеристика объекта», перечни
// сокращений и НД) НЕ фанятся: их детерминированно строит `cli consolidate`
// из паспорта и принятых редакций в Фазе 4.
const SECTIONS = [
  { name: 'Категорирование',                docs: ['СП 12.13130'] },
  { name: 'ОПР / степень ОО / КПО',         docs: ['СП 2.13130'] },
  { name: 'Противопожарные расстояния',     docs: ['СП 4.13130'] },
  { name: 'Наружное ВПС и проезды',         docs: ['СП 8.13130', 'СП 4.13130'] },
  { name: 'Безопасность людей (эвакуация)', docs: ['СП 1.13130'] },
  { name: 'Безопасность пожарных',          docs: ['СП 4.13130'] },
  { name: 'Противопожарная защита',         docs: ['СП 486.1311500', 'СП 484.1311500', 'СП 10.13130', 'СП 3.13130', 'СП 7.13130', 'СП 89.13330'] },
  { name: 'Перечень помещений под АУПТ/СПС', docs: ['СП 486.1311500'] },
  { name: 'Организационные мероприятия',     docs: ['ФЗ-123'] },
  // Раздел рисков включать, только если расчёт пожарных рисков реально требуется
  // (например, при отступлениях от норм). По умолчанию оставлен закомментированным.
  // { name: 'Расчёт пожарных рисков',      docs: ['ФЗ-123'] },
]

// ── Схемы структурированного вывода ──────────────────────────────────────
const SETUP_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['ready', 'stage', 'corpus_ok', 'missing'],
  properties: {
    ready: { type: 'boolean' },
    stage: { type: 'string' },
    corpus_ok: { type: 'boolean' },
    missing: { type: 'array', items: { type: 'string' } },
  },
}
const BUILD_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['section', 'norms_count', 'lacunae'],
  properties: {
    section: { type: 'string' },
    norms_count: { type: 'integer' },
    lacunae: { type: 'array', items: { type: 'string' } },
  },
}
const GATE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['passed', 'errors'],
  properties: {
    passed: { type: 'boolean' },
    errors: { type: 'array', items: { type: 'string' } }, // дословные коды валидатора
  },
}
const CONSOLIDATE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['md_path', 'sections_included'],
  properties: {
    md_path: { type: 'string' },
    docx_path: { type: 'string' },
    sections_included: { type: 'array', items: { type: 'string' } },
  },
}

// ── ФАЗА 1: заморозка исходных данных (барьер) ───────────────────────────
phase('Исходные данные')
const setup = await agent(
  `Ты — контролёр исходных данных проекта ${PROJECT} в конвейере mpb-pz-flow.
   Проверь ЧЕРЕЗ CLI (не выдумывай ничего):
     ${CLI} status        --project-dir ${PROJECT}
     ${CLI} corpus-verify --project-dir ${PROJECT}
     ${CLI} calc-run      --project-dir ${PROJECT}
   Условие готовности: стадия = passport_ready (или выше) И корпус целостен.
   Если паспорт не готов — верни ready:false и перечисли недостающие поля.
   НЕ заполняй паспорт сам: недостающие инженерные данные — это лакуны для заказчика.`,
  { schema: SETUP_SCHEMA, phase: 'Исходные данные', effort: 'low' }
)

if (!setup.ready) {
  log('Паспорт не заморожен — fan-out остановлен. Не хватает: ' + setup.missing.join(', '))
  return { verdict: 'НЕТ ИСХОДНЫХ ДАННЫХ', missing: setup.missing }
}
log(`Исходные данные заморожены (стадия ${setup.stage}). Разворачиваю ${SECTIONS.length} разделов.`)

// ── ФАЗЫ 2+3: по разделу — сборка агентом, затем МЕХАНИЧЕСКИЙ гейт ─────────
// pipeline без барьера: раздел уходит на гейт, как только собран его черновик.
const perSection = await pipeline(
  SECTIONS,

  // Стадия A — СУЖДЕНИЕ (агент): подбор норм под характеристики объекта
  (sec) => agent(
    `Ты — Агент сборки раздела «${sec.name}» тома 9 для проекта ${PROJECT}.
     Читай ТОЛЬКО подтверждённые характеристики: ${PROJECT}/artifacts/passport.json (блок confirmed)
     и источники из ${PROJECT}/standards/ (файлы, перечисленные в manifest.json). Внешние знания не используй.
     Работай с документами: ${sec.docs.join(', ')}.
     1) Подбери нормы, релевантные характеристикам объекта (ФКП, степень, категория, объём, габариты, люди).
     2) Для КАЖДОЙ нормы дай ДОСЛОВНУЮ цитату из источника (запрещён пересказ), точный локатор
        (пункт/таблица) и edition_year; source_file — из манифеста.
     3) Собери нормы в JSONL-файл и установи их валидацией:
          ${CLI} norms-add --project-dir ${PROJECT} --section "${sec.name}" --file <твой.jsonl>
        (команда проверит обязательные поля и сразу отчитается, какие цитаты НЕ верифицированы —
         почини их до сборки). Затем:
          ${CLI} build-matrix --project-dir ${PROJECT} --section "${sec.name}"
          ${CLI} assemble     --project-dir ${PROJECT} --section "${sec.name}"
     4) Доведи прозу черновика: типы абзацев А/Б/В/Г, видимая ссылка (документ+год+пункт) в каждом абзаце,
        числа с единицами — только из паспорта/расчётов/цитат.
     ЖЁСТКОЕ ПРАВИЛО: если точной цитаты в источнике нет — НЕ выдумывай, оформи как лакуну (decisions.lacunae).`,
    { label: `build:${sec.name}`, phase: 'Разделы', schema: BUILD_SCHEMA, effort: 'high' }
  ),

  // Стадия B — КОД (агент только запускает детерминированную проверку и возвращает её вердикт)
  (build, sec) => agent(
    `Ты запускаешь ДЕТЕРМИНИРОВАННУЮ проверку раздела «${sec.name}». Свою оценку текста НЕ выноси.
     Выполни строго по порядку и верни то, что сказал КОД:
       ${CLI} validate --project-dir ${PROJECT} --section "${sec.name}"
       ${CLI} audit    --project-dir ${PROJECT} --section "${sec.name}"
       ${CLI} gate     --project-dir ${PROJECT} --section "${sec.name}"
     passed = (gate завершился с кодом 0). errors = дословные коды валидатора (напр. norms.quote_unverified).
     Никакой интерпретации — только машинный вывод.`,
    { label: `gate:${sec.name}`, phase: 'Гейт', schema: GATE_SCHEMA, effort: 'low' }
  ).then((gate) => ({ section: sec.name, build, gate }))
)

// ── ФАЗА 4: маршрутизация правок (лимит 3 итерации) + сводный том ──────────
phase('Сводка')
let pending = perSection.filter((r) => r && !r.gate.passed)
let iter = 0
while (pending.length && iter < 3) {
  iter++
  log(`Итерация правок ${iter}/3: на доработку ${pending.length} раздел(ов).`)
  const retried = await parallel(
    pending.map((r) => () =>
      agent(
        `Раздел «${r.section}» НЕ прошёл гейт. Коды ошибок: ${JSON.stringify(r.gate.errors)}.
         Устрани ТОЛЬКО причину, не ослабляя проверок и не выдумывая текст:
           - quote_unverified   → приведи цитату к дословной по источнику (сверь по ${PROJECT}/standards/);
           - visible_norm_reference → добавь точный локатор рядом с «документ+год»;
           - number_unverified  → убери/обоснуй число через паспорт или расчёт;
           - trigger_mismatch   → согласуй статус матрицы с паспортом или добавь override_justification.
         Затем перезапусти: ${CLI} validate/audit/gate --project-dir ${PROJECT} --section "${r.section}".`,
        { label: `fix:${r.section}`, phase: 'Сводка', schema: GATE_SCHEMA, effort: 'high' }
      ).then((gate) => ({ section: r.section, gate }))
    )
  )
  pending = retried.filter(Boolean).filter((r) => !r.gate.passed)
}

if (pending.length) {
  return {
    verdict: 'ЭСКАЛАЦИЯ ПОЛЬЗОВАТЕЛЮ',
    unresolved: pending.map((p) => ({ section: p.section, errors: p.gate.errors })),
    note: 'Разделы не сошлись за 3 итерации — нужны решения заказчика или исходные данные.',
  }
}

// Все разделы зелёные → финализация и сводный том 9
const consolidated = await agent(
  `Все разделы прошли гейт. Сначала финализируй каждый раздел (нужны свежие final.md):
     для каждого имени раздела — ${CLI} finalize --project-dir ${PROJECT} --section "<имя>".
   Затем одной командой собери сводный том 9 по ПП РФ №87:
     ${CLI} consolidate --project-dir ${PROJECT}
   Команда сама строит «Общие положения» и «Характеристику объекта» из паспорта, обвязку —
   из принятых редакций, вставляет содержательные разделы из проверенных final.md в порядке
   ПП-87 (для неразработанных — честный плейсхолдер) и пишет tom9_svod.md + tom9_svod.docx (ГОСТ).
   НЕ переписывай содержимое разделов — они уже прошли аудит и хэш-привязаны.
   Верни пути к файлам и список включённых разделов из вывода команды.`,
  { phase: 'Сводка', schema: CONSOLIDATE_SCHEMA, effort: 'low' }
)

return {
  verdict: 'КОНВЕЙЕР ЗАВЕРШЁН',
  sections_built: perSection.length,
  fix_iterations: iter,
  files: consolidated,
}
